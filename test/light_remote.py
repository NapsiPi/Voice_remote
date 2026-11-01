#!/usr/bin/env python3
"""Light test: a keyboard TV remote, no speech recognition.

Checks the WM8960 HAT is detected and the TV answers over HDMI-CEC, then turns
key presses into TV remote commands. Needs only Python 3 (standard library),
alsa-utils and v4l-utils (setup_test_env.sh --light), so it runs on 32-bit Pi OS.
Run it on the Pi's own keyboard or over SSH.
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

from tv_link import (
    UI_CHANNEL_DOWN, UI_CHANNEL_UP, UI_DOWN, UI_EXIT, UI_LEFT, UI_MUTE, UI_NUMBER_0, UI_PAUSE,
    UI_PLAY, UI_RIGHT, UI_ROOT_MENU, UI_SELECT, UI_UP, UI_VOLUME_DOWN, UI_VOLUME_UP,
    Cec, alsa_card, connected_hdmi_ports,
)

# key -> (label, CEC user-control code)
KEYMAP = {
    "\x1b[A": ("Up", UI_UP),
    "\x1b[B": ("Down", UI_DOWN),
    "\x1b[D": ("Left", UI_LEFT),
    "\x1b[C": ("Right", UI_RIGHT),
    "\n": ("OK", UI_SELECT),
    "\x7f": ("Back", UI_EXIT),
    "b": ("Back", UI_EXIT),
    "h": ("Home", UI_ROOT_MENU),
    "+": ("Volume up", UI_VOLUME_UP),
    "=": ("Volume up", UI_VOLUME_UP),
    "-": ("Volume down", UI_VOLUME_DOWN),
    "m": ("Mute", UI_MUTE),
    "]": ("Channel up", UI_CHANNEL_UP),
    "[": ("Channel down", UI_CHANNEL_DOWN),
    ">": ("Play", UI_PLAY),
    " ": ("Pause", UI_PAUSE),
    **{str(d): (f"Number {d}", UI_NUMBER_0 + d) for d in range(10)},
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


def check_tv(cec_debug):
    ports = connected_hdmi_ports()
    if not ports:
        print("  FAIL  No TV connected on HDMI")
        return None
    cec = Cec(ports[0], debug=cec_debug)
    if not cec.available:
        print(f"  FAIL  TV on HDMI {ports[0]}, but CEC is unavailable ({cec.dev} or cec-ctl missing; "
              "run setup_test_env.sh --light)")
        return None
    power, name = cec.power_status(), cec.tv_name()
    if power is None and name is None:
        print(f"  WARN  TV on HDMI {ports[0]} does not answer CEC: enable SIMPLINK on the LG TV. "
              "Keys are still sent.")
    else:
        print(f"  PASS  TV on HDMI {ports[0]} answers CEC (name: {name or '?'}, power: {power or '?'})")
    print(f"  INFO  To see the TV's replies (e.g. FEATURE_ABORT for ignored keys), run in a second "
          f"terminal: cec-ctl -d {cec.dev} -M")
    return cec


def mic_loopback(card, seconds):
    if not card:
        print("No WM8960 HAT, so no microphone to test.")
        return
    device = f"plughw:CARD={card},DEV=0"
    wav = Path(tempfile.gettempdir()) / "voice_remote_light_loopback.wav"
    print(f"Recording {seconds} s from the HAT, speak now...")
    rec = subprocess.run(["arecord", "-q", "-D", device, "-f", "S16_LE", "-r", "16000", "-c", "2",
                          "-d", str(seconds), str(wav)])
    if rec.returncode != 0:
        print("Recording failed.")
        return
    print("Playing back on the HAT speaker...")
    subprocess.run(["aplay", "-q", "-D", device, str(wav)])
    print("Done. Heard yourself? The HAT works.")


def toggle_power(cec):
    if cec.power_status() in ("on", "to-on"):
        print("Power: standby")
        cec.standby()
    else:
        print("Power: on")
        cec.power_on()


def read_key(fd):
    key = os.read(fd, 1)
    if key == b"\x1b":
        # Arrow keys arrive as ESC [ A..D.
        if select.select([fd], [], [], 0.05)[0]:
            key += os.read(fd, 2)
    return key.decode(errors="ignore").replace("\r", "\n")


def key_loop(card, cec, loopback_seconds):
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
            elif cec is None:
                print("No TV with CEC, so nothing to send. (t = mic test, q = quit)")
            elif key == "p":
                toggle_power(cec)
            elif key in KEYMAP:
                label, code = KEYMAP[key]
                print(f"{label:<13} {cec.press(code)} (code {code:#04x})")
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--loopback-seconds", type=int, default=3, help="length of the t-key mic test (default: 3)")
    p.add_argument("--cec-debug", action="store_true",
                   help="print every cec-ctl command and its full output (for BUG-002 reports)")
    args = p.parse_args()
    if not sys.stdin.isatty():
        sys.exit("Run this in a terminal (on the Pi or over SSH): it reads single key presses.")

    print("== Light test: hardware checks ==")
    card = check_hat()
    cec = check_tv(args.cec_debug)
    try:
        key_loop(card, cec, args.loopback_seconds)
    except KeyboardInterrupt:
        pass
    print("\nBye.")


if __name__ == "__main__":
    main()
