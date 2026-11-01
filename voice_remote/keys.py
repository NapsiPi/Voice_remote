"""Light test: a keyboard TV remote, no speech recognition.

Checks the WM8960 HAT is detected and the TV answers over HDMI-CEC and webOS, then
turns key presses into TV remote commands. Power goes over HDMI-CEC; everything else
goes over webOS on the network (the LG TV ignores CEC keys, BUG-002), falling back
to CEC when webOS isn't available. Needs only Python 3 (standard library),
alsa-utils and v4l-utils (./setup.sh --light), so it runs on 32-bit Pi OS.
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

from .tv_link import (
    UI_CHANNEL_DOWN, UI_CHANNEL_UP, UI_DOWN, UI_EXIT, UI_LEFT, UI_MUTE, UI_NUMBER_0, UI_PAUSE,
    UI_PLAY, UI_RIGHT, UI_ROOT_MENU, UI_SELECT, UI_UP, UI_VOLUME_DOWN, UI_VOLUME_UP,
    Cec, alsa_card, connected_hdmi_ports,
)
from .webos_link import connect_webos

# key -> (label, CEC user-control code, webOS action)
KEYMAP = {
    "\x1b[A": ("Up", UI_UP, ("button", "UP")),
    "\x1b[B": ("Down", UI_DOWN, ("button", "DOWN")),
    "\x1b[D": ("Left", UI_LEFT, ("button", "LEFT")),
    "\x1b[C": ("Right", UI_RIGHT, ("button", "RIGHT")),
    "\n": ("OK", UI_SELECT, ("button", "ENTER")),
    "\x7f": ("Back", UI_EXIT, ("button", "BACK")),
    "b": ("Back", UI_EXIT, ("button", "BACK")),
    "h": ("Home", UI_ROOT_MENU, ("button", "HOME")),
    "+": ("Volume up", UI_VOLUME_UP, ("request", "ssap://audio/volumeUp")),
    "=": ("Volume up", UI_VOLUME_UP, ("request", "ssap://audio/volumeUp")),
    "-": ("Volume down", UI_VOLUME_DOWN, ("request", "ssap://audio/volumeDown")),
    "m": ("Mute", UI_MUTE, ("button", "MUTE")),
    "]": ("Channel up", UI_CHANNEL_UP, ("request", "ssap://tv/channelUp")),
    "[": ("Channel down", UI_CHANNEL_DOWN, ("request", "ssap://tv/channelDown")),
    ">": ("Play", UI_PLAY, ("request", "ssap://media.controls/play")),
    " ": ("Pause", UI_PAUSE, ("request", "ssap://media.controls/pause")),
    **{str(d): (f"Number {d}", UI_NUMBER_0 + d, ("button", str(d))) for d in range(10)},
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
              "run ./setup.sh --light)")
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


def toggle_power(cec, tv):
    """Power over CEC (works on the LG TV). Without CEC, webOS can only turn the TV off."""
    if cec is not None:
        if cec.power_status() in ("on", "to-on"):
            print("Power: standby (CEC)")
            cec.standby()
        else:
            print("Power: on (CEC)")
            cec.power_on()
    elif tv is not None:
        print("Power: off (webOS; turning on needs CEC)")
        tv.do(("request", "ssap://system/turnOff"))


def send_key(key, cec, tv):
    label, code, action = KEYMAP[key]
    if tv is not None:
        try:
            tv.do(action)
            return f"{label:<13} sent via webOS"
        except (OSError, ConnectionError, RuntimeError) as e:
            if cec is None:
                return f"{label:<13} webOS failed: {e}"
            return f"{label:<13} webOS failed ({e}); CEC: {cec.press(code)}"
    return f"{label:<13} {cec.press(code)} via CEC (code {code:#04x})"


def read_key(fd):
    key = os.read(fd, 1)
    if key == b"\x1b":
        # Arrow keys arrive as ESC [ A..D.
        if select.select([fd], [], [], 0.05)[0]:
            key += os.read(fd, 2)
    return key.decode(errors="ignore").replace("\r", "\n")


def key_loop(card, cec, tv, loopback_seconds):
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
            elif cec is None and tv is None:
                print("No TV control (neither CEC nor webOS), so nothing to send. (t = mic test, q = quit)")
            elif key == "p":
                toggle_power(cec, tv)
            elif key in KEYMAP:
                print(send_key(key, cec, tv))
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--loopback-seconds", type=int, default=3, help="length of the t-key mic test (default: 3)")
    p.add_argument("--cec-debug", action="store_true",
                   help="print every cec-ctl command and its full output (for BUG-002 reports)")
    p.add_argument("--tv-ip", default=None,
                   help="LG TV IP address for webOS control (default: last used, else auto-discover)")
    p.add_argument("--no-webos", action="store_true", help="send keys over CEC only")
    p.add_argument("--webos-debug", action="store_true", help="print every webOS message")
    args = p.parse_args()
    if not sys.stdin.isatty():
        sys.exit("Run this in a terminal (on the Pi or over SSH): it reads single key presses.")

    print("== Light test: hardware checks ==")
    card = check_hat()
    cec = check_tv(args.cec_debug)
    tv = None if args.no_webos else connect_webos(args.tv_ip, args.webos_debug)
    try:
        key_loop(card, cec, tv, args.loopback_seconds)
    except KeyboardInterrupt:
        pass
    finally:
        if tv is not None:
            tv.close()
    print("\nBye.")


if __name__ == "__main__":
    main()
