"""Keyboard remote: TV control from single key presses, no speech recognition.

Checks the WM8960 HAT and the TV (HDMI-CEC and webOS), then turns key presses into
TV commands. Power goes over HDMI-CEC; everything else goes over webOS on the network
(the LG TV ignores CEC keys, BUG-002), falling back to CEC. Needs only Python 3
(standard library), alsa-utils and v4l-utils (./setup.sh --light), so it runs on
32-bit Pi OS without a venv. Run it on the Pi's own keyboard or over SSH:

  ./voice-remote --keys
"""

import argparse
import os
import select
import subprocess
import sys
import tempfile
import termios
import tty
from pathlib import Path

from .tv import ACTIONS, TvControl
from .tv_link import alsa_card

# key -> TvControl action
KEYMAP = {
    "\x1b[A": "up", "\x1b[B": "down", "\x1b[D": "left", "\x1b[C": "right",
    "\n": "ok", "\x7f": "back", "b": "back", "h": "home",
    "+": "volume_up", "=": "volume_up", "-": "volume_down", "m": "mute",
    "]": "channel_up", "[": "channel_down", ">": "play", " ": "pause",
    **{str(d): f"digit_{d}" for d in range(10)},
}

HELP = """
Keys:
  arrows        Up / Down / Left / Right      Enter  OK
  b, Backspace  Back                          h      Home
  + / -         Volume up / down              m      Mute
  ] / [         Channel up / down             0-9    Numbers
  >             Play                          Space  Pause
  p             Power on / standby            t      Microphone loopback test
  ?             This help                     q      Quit
"""


def check_hat():
    card = alsa_card("wm8960")
    if card:
        print(f"  PASS  WM8960 HAT detected (ALSA card '{card}')")
    else:
        print("  FAIL  WM8960 HAT not detected: check /boot/firmware/config.txt (README, Build 101)")
    return card


def mic_loopback(card, seconds):
    if not card:
        print("No WM8960 HAT, so no microphone to test.")
        return
    device = f"plughw:CARD={card},DEV=0"
    wav = Path(tempfile.gettempdir()) / "voice_remote_keys_loopback.wav"
    print(f"Recording {seconds} s from the HAT, speak now...")
    rec = subprocess.run(["arecord", "-q", "-D", device, "-f", "S16_LE", "-r", "16000", "-c", "2",
                          "-d", str(seconds), str(wav)])
    if rec.returncode != 0:
        print("Recording failed.")
        return
    print("Playing back on the HAT speaker...")
    subprocess.run(["aplay", "-q", "-D", device, str(wav)])
    print("Done. Heard yourself? The HAT works.")


def read_key(fd):
    key = os.read(fd, 1)
    if key == b"\x1b":
        # Arrow keys arrive as ESC [ A..D.
        if select.select([fd], [], [], 0.05)[0]:
            key += os.read(fd, 2)
    return key.decode(errors="ignore").replace("\r", "\n")


def key_loop(card, tv, loopback_seconds):
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    print(HELP)
    try:
        tty.setcbreak(fd)  # single key presses; Ctrl+C still works
        while True:
            key = read_key(fd)
            if key == "q":
                return
            if key == "?":
                print(HELP)
            elif key == "t":
                termios.tcsetattr(fd, termios.TCSADRAIN, saved)
                mic_loopback(card, loopback_seconds)
                tty.setcbreak(fd)
            elif not tv.available:
                print("No TV control (neither CEC nor webOS), so nothing to send. (t = mic test, q = quit)")
            elif key == "p":
                label, result = tv.toggle_power()
                print(f"{label:<13} {result}")
            elif key in KEYMAP:
                action = KEYMAP[key]
                print(f"{ACTIONS[action][0]:<13} {tv.send(action)}")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def main(argv=None):
    p = argparse.ArgumentParser(prog="voice-remote --keys", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--loopback-seconds", type=int, default=3, help="length of the t-key mic test (default: 3)")
    p.add_argument("--tv-ip", default=None,
                   help="LG TV IP address for webOS control (default: last used, else auto-discover)")
    p.add_argument("--no-webos", action="store_true", help="send keys over CEC only")
    p.add_argument("--cec-debug", action="store_true", help="print every cec-ctl command and its full output")
    p.add_argument("--webos-debug", action="store_true", help="print every webOS message")
    args = p.parse_args(argv)
    if not sys.stdin.isatty():
        sys.exit("Run this in a terminal (on the Pi or over SSH): it reads single key presses.")

    print("== Keyboard remote: hardware checks ==")
    card = check_hat()
    tv = TvControl.connect(args.tv_ip, not args.no_webos, args.cec_debug, args.webos_debug)
    if tv.cec is not None:
        print(f"  INFO  To watch the TV's CEC replies, run in a second terminal: cec-ctl -d {tv.cec.dev} -M")
    try:
        key_loop(card, tv, args.loopback_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        tv.close()
    print("\nBye.")
    return 0
