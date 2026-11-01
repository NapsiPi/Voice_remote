#!/usr/bin/env python3
"""WM8960 Audio HAT sanity test: speak, and the Pi says it back.

Captures speech from the WM8960 microphones, transcribes it with Whisper (STT) and
reads the text back with espeak-ng (TTS). Talking over the reply interrupts it
(barge-in) and the new speech is transcribed instead. Replies play on the TV when
it is connected and on, otherwise on the HAT speaker (see audio_output.py).

Say "stop test" or press Ctrl+C to quit.
"""

import argparse
import collections
import io
import queue
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from audio_output import AudioRouter

WHISPER_RATE = 16000
BLOCK_MS = 30
START_BLOCKS = 3   # consecutive loud blocks (~90 ms) that count as speech starting
BARGE_BLOCKS = 5   # consecutive loud blocks (~150 ms) that interrupt playback
PREROLL_S = 0.3    # audio kept from before speech starts, so the first syllable isn't clipped
EXIT_PHRASE = "stop test"


def rms(block):
    return float(np.sqrt(np.mean(block * block)))


def resample(audio, src_rate, dst_rate):
    if src_rate == dst_rate:
        return audio
    if src_rate > dst_rate:
        # Box filter to reduce aliasing before decimating.
        k = max(1, int(src_rate // dst_rate))
        audio = np.convolve(audio, np.ones(k) / k, mode="same")
    n = int(round(len(audio) * dst_rate / src_rate))
    x_old = np.arange(len(audio)) / src_rate
    x_new = np.arange(n) / dst_rate
    return np.interp(x_new, x_old, audio).astype(np.float32)


def to_wav_bytes(audio, rate):
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def normalise(text):
    return "".join(c for c in text.lower() if c.isalnum() or c == " ").strip()


class LocalWhisper:
    """Runs Whisper on the Pi with faster-whisper (offline after the model download)."""

    def __init__(self, model_size, language):
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            sys.exit("faster-whisper is not installed. It needs 64-bit Raspberry Pi OS; "
                     "on 32-bit use --backend openai (see README, Build 101).")

        print(f"Loading Whisper model '{model_size}' (the first run downloads it)...")
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.language = language

    def transcribe(self, audio):
        segments, _ = self.model.transcribe(audio, language=self.language, beam_size=1)
        return " ".join(seg.text.strip() for seg in segments).strip()


class OpenAIWhisper:
    """Sends audio to the OpenAI Whisper API (needs OPENAI_API_KEY)."""

    def __init__(self, language):
        from openai import OpenAI

        self.client = OpenAI()
        self.language = language

    def transcribe(self, audio):
        kwargs = {"language": self.language} if self.language else {}
        result = self.client.audio.transcriptions.create(
            model="whisper-1",
            file=("speech.wav", to_wav_bytes(audio, WHISPER_RATE)),
            **kwargs,
        )
        return result.text.strip()


class Mic:
    """Continuous capture from the input device as mono float32 blocks."""

    def __init__(self, device, rate):
        info = sd.query_devices(device, "input")
        self.rate = rate or int(info["default_samplerate"])
        channels = min(2, info["max_input_channels"])
        print(f"Microphone: {info['name']} @ {self.rate} Hz, {channels} ch")
        self.blocks = queue.Queue()
        self.stream = sd.InputStream(
            device=device,
            samplerate=self.rate,
            channels=channels,
            dtype="float32",
            blocksize=int(self.rate * BLOCK_MS / 1000),
            callback=self._callback,
        )

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        # The HAT has two mics; average them to mono.
        self.blocks.put(indata.mean(axis=1).copy())

    def read(self, timeout=2.0):
        try:
            return self.blocks.get(timeout=timeout)
        except queue.Empty:
            sys.exit("No audio from the microphone. Run test/mic_check.sh to check the HAT.")

    def flush(self):
        while True:
            try:
                self.blocks.get_nowait()
            except queue.Empty:
                return


class Speaker:
    """espeak-ng renders speech to a WAV file and aplay plays it in the background,
    on whichever output the router picks (TV or HAT speaker)."""

    def __init__(self, router, voice, speed):
        for tool in ("espeak-ng", "aplay"):
            if not shutil.which(tool):
                sys.exit(f"'{tool}' not found. Run test/setup_test_env.sh first.")
        self.router = router
        self.voice = voice
        self.speed = speed
        self.wav = Path(tempfile.gettempdir()) / "voice_remote_tts.wav"
        self.proc = None

    def start(self, text):
        subprocess.run(
            ["espeak-ng", "-v", self.voice, "-s", str(self.speed), "-w", str(self.wav), text],
            check=True,
        )
        self.play(self.wav)

    def play(self, wav):
        output = self.router.current()
        self.proc = self._aplay(output.device, wav)
        if output.name == "tv":
            # HDMI audio can be missing even with the TV on; fall back to the HAT if aplay dies.
            time.sleep(0.3)
            if self.proc.poll() not in (None, 0):
                print("[audio] TV HDMI audio failed, switching to the HAT speaker")
                self.router.tv_failed()
                self.proc = self._aplay(self.router.current().device, wav)

    @staticmethod
    def _aplay(device, wav):
        cmd = ["aplay", "-q"]
        if device:
            cmd += ["-D", device]
        cmd.append(str(wav))
        return subprocess.Popen(cmd)

    def playing(self):
        return self.proc is not None and self.proc.poll() is None

    def wait(self):
        if self.proc is not None:
            self.proc.wait()

    def stop(self):
        if self.playing():
            self.proc.terminate()
            self.proc.wait()


def find_input_device(hint):
    if hint is None:
        return None
    if hint.isdigit():
        return int(hint)
    for idx, dev in enumerate(sd.query_devices()):
        if hint.lower() in dev["name"].lower() and dev["max_input_channels"] > 0:
            return idx
    sys.exit(f"No input device matching '{hint}'. Use --list-devices to see what is available.")


def calibrate(mic, seconds):
    print(f"Measuring background noise for {seconds:.1f}s, please stay quiet...")
    levels = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        levels.append(rms(mic.read()))
    return float(np.median(levels))


def record_utterance(mic, threshold, args, preroll, wait_s=None):
    """Wait for speech, then record until the speaker goes quiet.

    preroll holds blocks already known to be speech (from a barge-in); when given,
    recording starts straight away. Returns None if nobody speaks within wait_s.
    """
    frames = list(preroll)
    if not frames:
        history = collections.deque(maxlen=int(PREROLL_S * 1000 / BLOCK_MS))
        loud_run = 0
        deadline = None if wait_s is None else time.monotonic() + wait_s
        while loud_run < START_BLOCKS:
            if deadline is not None and time.monotonic() > deadline:
                return None
            block = mic.read()
            history.append(block)
            loud_run = loud_run + 1 if rms(block) > threshold else 0
        frames = list(history)

    max_blocks = int(args.max_seconds * 1000 / BLOCK_MS)
    end_blocks = int(args.silence_ms / BLOCK_MS)
    silent = 0
    while len(frames) < max_blocks and silent < end_blocks:
        block = mic.read()
        frames.append(block)
        silent = silent + 1 if rms(block) <= threshold else 0
    return np.concatenate(frames)


def speak_with_barge_in(mic, speaker, text, threshold, args):
    """Speak text. Returns the interrupting speech blocks on barge-in, else None."""
    mic.flush()
    speaker.start(text)
    started = time.monotonic()
    history = collections.deque(maxlen=int(PREROLL_S * 1000 / BLOCK_MS))
    loud_run = 0
    while speaker.playing():
        try:
            block = mic.blocks.get(timeout=0.1)
        except queue.Empty:
            continue
        # Ignore the first moments of playback, when our own voice hits the mics hardest.
        if not args.barge_in or time.monotonic() - started < args.barge_in_delay:
            continue
        history.append(block)
        loud_run = loud_run + 1 if rms(block) > threshold * args.barge_in_factor else 0
        if loud_run >= BARGE_BLOCKS:
            speaker.stop()
            print("[barge-in] Stopped talking, listening to you...")
            return list(history)
    mic.flush()  # drop the tail of our own voice
    return None


def add_common_args(p):
    """Audio, Whisper and barge-in options shared with startup_checks.py."""
    p.add_argument("--list-devices", action="store_true", help="list audio devices and exit")
    p.add_argument("--backend", choices=["local", "openai"], default="local",
                   help="local = faster-whisper on the Pi (default), openai = OpenAI Whisper API")
    p.add_argument("--model", default="base.en",
                   help="faster-whisper model size: tiny.en, base.en, small.en, ... (default: base.en)")
    p.add_argument("--language", default="en", help="spoken language code (default: en)")
    p.add_argument("--input-device", default="wm8960",
                   help="input device index or part of its name (default: wm8960)")
    p.add_argument("--output-device", default=None,
                   help="fixed ALSA device for speech, e.g. plughw:CARD=wm8960soundcard,DEV=0 "
                        "(default: automatic, TV when connected and on, else the HAT speaker)")
    p.add_argument("--no-cec", dest="cec", action="store_false",
                   help="don't ask the TV for its power state over HDMI-CEC; a connected TV counts as on")
    p.add_argument("--rate", type=int, default=None, help="capture sample rate (default: device default)")
    p.add_argument("--voice", default="en", help="espeak-ng voice (default: en)")
    p.add_argument("--speed", type=int, default=165, help="espeak-ng words per minute (default: 165)")
    p.add_argument("--calibrate", type=float, default=1.5, help="seconds of noise calibration (default: 1.5)")
    p.add_argument("--threshold-factor", type=float, default=3.0,
                   help="speech threshold as a multiple of the noise floor (default: 3.0)")
    p.add_argument("--min-threshold", type=float, default=0.01, help="lowest speech threshold, RMS (default: 0.01)")
    p.add_argument("--silence-ms", type=int, default=800, help="silence that ends an utterance (default: 800)")
    p.add_argument("--max-seconds", type=float, default=15.0, help="longest utterance (default: 15)")
    p.add_argument("--no-barge-in", dest="barge_in", action="store_false", help="disable barge-in")
    p.add_argument("--barge-in-factor", type=float, default=2.0,
                   help="barge-in needs speech this many times louder than the speech threshold (default: 2.0)")
    p.add_argument("--barge-in-delay", type=float, default=0.4,
                   help="seconds after a reply starts before barge-in is allowed (default: 0.4)")


def build_audio(args):
    """Transcriber, speaker and mic from the common options."""
    device = find_input_device(args.input_device)
    if args.backend == "openai":
        transcriber = OpenAIWhisper(args.language)
    else:
        transcriber = LocalWhisper(args.model, args.language)
    speaker = Speaker(AudioRouter(args.output_device, args.cec), args.voice, args.speed)
    return transcriber, speaker, Mic(device, args.rate)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(p)
    args = p.parse_args()
    if args.list_devices:
        print(sd.query_devices())
        return

    transcriber, speaker, mic = build_audio(args)

    try:
        with mic.stream:
            noise = calibrate(mic, args.calibrate)
            threshold = max(noise * args.threshold_factor, args.min_threshold)
            print(f"Noise floor {noise:.4f} RMS, speech threshold {threshold:.4f} RMS")

            preroll = speak_with_barge_in(
                mic, speaker, "Sanity test ready. Say something.", threshold, args) or []
            while True:
                if not preroll:
                    print(f"\nListening... (say '{EXIT_PHRASE}' to quit)")
                audio = record_utterance(mic, threshold, args, preroll)
                t0 = time.monotonic()
                text = transcriber.transcribe(resample(audio, mic.rate, WHISPER_RATE))
                print(f"Heard ({len(audio) / mic.rate:.1f}s audio, "
                      f"{time.monotonic() - t0:.1f}s to transcribe): {text!r}")
                if not text:
                    preroll = []
                    continue
                if EXIT_PHRASE in normalise(text):
                    speaker.start("Stopping the test. Goodbye.")
                    speaker.wait()
                    break
                preroll = speak_with_barge_in(mic, speaker, f"You said: {text}", threshold, args) or []
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        speaker.stop()


if __name__ == "__main__":
    main()
