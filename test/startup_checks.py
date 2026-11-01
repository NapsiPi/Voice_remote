#!/usr/bin/env python3
"""Startup checks that run before the voice remote starts.

The Pi talks you through four checks, and you answer each question by saying yes or no:
  1. Microphone loopback  - record a few seconds and play them back
  2. TV connection        - find the TV on HDMI and play a message on its speakers
  3. Speech recognition   - Whisper transcribes a sentence and reads it back
  4. TV control           - turn the TV volume up and back down (webOS on the network, else HDMI-CEC)
Then it announces that the voice remote is launching.
"""

import argparse
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import sounddevice as sd

from sanity_test import (
    BLOCK_MS, WHISPER_RATE, add_common_args, build_audio, calibrate, normalise,
    record_utterance, resample, rms, to_wav_bytes,
)
from tv_link import UI_VOLUME_DOWN, UI_VOLUME_UP
from webos_link import connect_webos

YES = {"yes", "yeah", "yep", "yup", "yah", "yeh", "correct", "right", "sure", "ok", "okay"}
NO = {"no", "nope", "nah", "wrong", "incorrect"}
ANSWER_WAIT_S = 8
ECHO_TAIL_S = 0.4  # let the room go quiet after we speak before listening (BUG-003)
TV_ON = (None, "on", "to-on")

INTRO = ("Welcome to the voice remote. Before it starts, we will run four quick checks: "
         "the microphone, the TV connection, speech recognition, and TV control. "
         "Answer each question by saying yes or no.")


@dataclass
class Result:
    name: str
    passed: bool | None  # None = skipped
    detail: str


class StartupChecks:
    def __init__(self, args):
        self.args = args
        self.transcriber, self.speaker, self.mic = build_audio(args)
        self.router = self.speaker.router
        self.threshold = None

    # --- speaking and listening -------------------------------------------------

    def say(self, text):
        print(f"[say] {text}")
        self.speaker.start(text)
        self.speaker.wait()
        time.sleep(ECHO_TAIL_S)
        self.mic.flush()  # drop our own voice picked up by the mics

    def listen(self, preroll=(), wait_s=ANSWER_WAIT_S):
        audio = record_utterance(self.mic, self.threshold, self.args, list(preroll), wait_s)
        if audio is None:
            print("[heard] (nothing)")
            return ""
        text = self.transcriber.transcribe(resample(audio, self.mic.rate, WHISPER_RATE))
        print(f"[heard] {text!r}")
        return text

    def ask_yes_no(self, question, attempts=3):
        """Ask a question, then listen; True for yes, False for no or no clear answer.

        The whole question is spoken before listening (no barge-in): otherwise the Pi's
        own voice from the speaker was taken as the answer (BUG-003)."""
        for attempt in range(1, attempts + 1):
            self.say(question)
            print(f"[listening] say yes or no (attempt {attempt}/{attempts}, {ANSWER_WAIT_S}s)...")
            words = set(normalise(self.listen()).split())
            if words & YES and not words & NO:
                return True
            if words & NO and not words & YES:
                return False
            question = "Sorry, I didn't catch that. Please say yes or no."
        return False

    def record_seconds(self, seconds):
        self.mic.flush()
        blocks = [self.mic.read() for _ in range(int(seconds * 1000 / BLOCK_MS))]
        return np.concatenate(blocks), max(rms(b) for b in blocks)

    # --- the four checks --------------------------------------------------------

    def check_mic_loopback(self):
        name = "1. Microphone loopback"
        self.say("Check one: microphone. When I say go, talk for a few seconds, "
                 "and I will play it back to you. Go.")
        audio, peak = self.record_seconds(self.args.loopback_seconds)
        if peak <= self.threshold:
            self.say("I did not pick up any sound from the microphone.")
            return Result(name, False, f"no speech captured (peak {peak:.4f} <= threshold {self.threshold:.4f})")

        wav = Path(tempfile.gettempdir()) / "voice_remote_loopback.wav"
        wav.write_bytes(to_wav_bytes(audio, self.mic.rate))
        self.say("Here is your recording.")
        self.speaker.play(wav)
        self.speaker.wait()
        self.mic.flush()
        heard = self.ask_yes_no("Did you hear yourself clearly?")
        return Result(name, heard, f"peak level {peak:.4f}, user {'confirmed' if heard else 'did not confirm'}")

    def check_tv(self):
        name = "2. TV connection"
        self.say("Check two: TV connection.")
        port, power = self.router.tv_status()
        if port is None:
            self.say("I cannot find a TV on either HDMI port, so I will use the HAT speaker.")
            return Result(name, False, "no display connected on HDMI")

        if power not in TV_ON:
            self.say(f"A TV is connected to HDMI {port}, but it is in {power}. "
                     "Please turn it on with its remote.")
            self.ask_yes_no("Say yes when the TV is on.")
            port, power = self.router.tv_status()
            if power not in TV_ON:
                return Result(name, False, f"TV on HDMI {port} is still {power}")

        self.router.refresh()
        output = self.router.current()
        if output.name != "tv":
            self.say("The TV is connected, but its HDMI audio is not available, "
                     "so sound stays on the HAT speaker.")
            return Result(name, False, output.reason)

        heard = self.ask_yes_no("This message is playing on the TV speakers. Can you hear it from the TV?")
        if not heard:
            self.router.tv_failed()  # the user can't hear the TV: use the HAT for now
        return Result(name, heard, f"{output.reason}; user {'confirmed' if heard else 'did not hear it'}")

    def check_speech(self):
        name = "3. Speech recognition"
        self.say("Check three: speech recognition. Please say a short sentence.")
        text = self.listen(wait_s=10)
        if not text:
            self.say("I did not hear anything.")
            return Result(name, False, "nothing transcribed")
        right = self.ask_yes_no(f"I heard: {text}. Is that right?")
        return Result(name, right, f"heard {text!r}")

    def check_tv_control(self):
        """Volume up/down over webOS (the LG TV ignores CEC keys, BUG-002), else over CEC."""
        name = "4. TV control"
        self.say("Check four: TV control. If the TV asks to pair with the voice remote, "
                 "accept it with the TV remote.")
        tv = connect_webos(self.args.tv_ip)
        if tv is not None:
            via = "webOS"

            def press(up):
                try:
                    tv.volume_up() if up else tv.volume_down()
                    return True
                except (OSError, ConnectionError, RuntimeError) as e:
                    print(f"[webos] {e}")
                    return False
        else:
            port, _ = self.router.tv_status()
            cec = self.router.cec(port) if port is not None else None
            if cec is None or not cec.available:
                self.say("I cannot reach the TV over the network or over HDMI CEC, so check four is skipped.")
                return Result(name, None, "skipped: no webOS TV found and no CEC")
            via = "CEC"

            def press(up):
                return cec.press(UI_VOLUME_UP if up else UI_VOLUME_DOWN) == "sent"

        self.say("Watch the TV volume. I will turn it up two steps, then back down.")
        sent = True
        for up in (True, True, False, False):
            time.sleep(0.6)
            sent = press(up) and sent
        worked = self.ask_yes_no("Did the TV volume go up and then back down?")
        if not worked:
            self.say("Turn on LG Connect Apps in the TV's network settings." if via == "webOS"
                     else "Make sure SIMPLINK, LG's HDMI CEC setting, is turned on in the TV settings.")
        if tv is not None:
            tv.close()
        return Result(name, worked, f"via {via}; volume commands {'sent' if sent else 'failed to send'}")

    # --- run --------------------------------------------------------------------

    def run(self):
        with self.mic.stream:
            noise = calibrate(self.mic, self.args.calibrate)
            self.threshold = max(noise * self.args.threshold_factor, self.args.min_threshold)
            print(f"Noise floor {noise:.4f} RMS, speech threshold {self.threshold:.4f} RMS")

            self.say(INTRO)
            results = [self.check_mic_loopback()]
            results.append(self.check_tv())
            results.append(self.check_speech())
            results.append(self.check_tv_control())

            print("\n== Startup check results ==")
            for r in results:
                status = {True: "PASS", False: "FAIL", None: "SKIP"}[r.passed]
                print(f"  {status}  {r.name}: {r.detail}")

            failed = [r.name.split(". ", 1)[1] for r in results if r.passed is False]
            if not failed:
                self.say("All checks passed.")
            else:
                self.say(f"{len(failed)} of {len(results)} checks failed: {', '.join(failed)}.")
                if not self.ask_yes_no("Do you want to launch the voice remote anyway?"):
                    self.say("Please fix the failed checks and run them again. Goodbye.")
                    return 1
            self.say("We are launching the voice remote. You can now use your voice to control the TV.")
        return self.launch()

    def launch(self):
        if self.args.then:
            return subprocess.call(shlex.split(self.args.then))
        print("Startup checks done. (The voice remote app isn't written yet; "
              "pass --then '<command>' to start it after the checks.)")
        return 0


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(p)
    p.add_argument("--loopback-seconds", type=float, default=4.0,
                   help="length of the microphone loopback recording (default: 4)")
    p.add_argument("--then", default=None, help="command to run after the checks, e.g. the voice remote app")
    args = p.parse_args()
    if args.list_devices:
        print(sd.query_devices())
        return 0

    checks = StartupChecks(args)
    try:
        return checks.run()
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    finally:
        checks.speaker.stop()


if __name__ == "__main__":
    sys.exit(main())
