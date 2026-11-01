"""Finds the TV on the Raspberry Pi 5's HDMI ports and talks to it over HDMI-CEC.

Connection state comes from the kernel's DRM connector status. Power state and
remote-control keys go through cec-ctl (v4l-utils) on /dev/cec<port>.
"""

import glob
import re
import shutil
import subprocess
from pathlib import Path

CEC_TV = "0"  # CEC logical address of the TV
OSD_NAME = "VoiceRemote"

# CEC "User Control" codes (HDMI-CEC spec), sent as remote-control key presses.
UI_SELECT = 0x00
UI_UP = 0x01
UI_DOWN = 0x02
UI_LEFT = 0x03
UI_RIGHT = 0x04
UI_ROOT_MENU = 0x09  # Home on most TVs
UI_EXIT = 0x0D       # Back
UI_NUMBER_0 = 0x20   # digits are 0x20..0x29
UI_CHANNEL_UP = 0x30
UI_CHANNEL_DOWN = 0x31
UI_VOLUME_UP = 0x41
UI_VOLUME_DOWN = 0x42
UI_MUTE = 0x43
UI_PLAY = 0x44
UI_PAUSE = 0x46


def connected_hdmi_ports():
    """HDMI port numbers (0 or 1) that have a display attached."""
    ports = []
    for status in sorted(glob.glob("/sys/class/drm/card*-HDMI-A-*/status")):
        try:
            if Path(status).read_text().strip() == "connected":
                ports.append(int(re.search(r"HDMI-A-(\d+)", status).group(1)) - 1)
        except OSError:
            pass
    return ports


def alsa_card(pattern):
    """ALSA card id (e.g. 'vc4hdmi0') whose /proc/asound/cards entry matches pattern."""
    try:
        text = Path("/proc/asound/cards").read_text()
    except OSError:
        return None
    for line in text.splitlines():
        m = re.match(r"\s*\d+\s+\[(\S+)\s*\]:\s*(.*)", line)
        if m and re.search(pattern, f"{m.group(1)} {m.group(2)}", re.IGNORECASE):
            return m.group(1)
    return None


class Cec:
    """HDMI-CEC on one HDMI port. Queries return None when CEC is unavailable or the TV is silent."""

    def __init__(self, port, debug=False):
        self.dev = f"/dev/cec{port}"
        self.available = bool(shutil.which("cec-ctl")) and Path(self.dev).exists()
        self.debug = debug  # print every cec-ctl command and its full output
        self.last_output = ""  # output of the last cec-ctl call, even when it failed
        self._registered = False

    def _cec_ctl(self, *args, timeout=5):
        cmd = ["cec-ctl", "-d", self.dev, *args]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            if self.debug:
                print(f"[cec] $ {' '.join(cmd)}\n[cec] {e}")
            return None
        text = out.stdout + out.stderr
        self.last_output = text
        if self.debug:
            print(f"[cec] $ {' '.join(cmd)}  (exit {out.returncode})\n{text.rstrip()}")
        return text if out.returncode == 0 else None

    def _send(self, *args):
        if not self.available:
            return None
        if not self._registered:
            # Claim a CEC logical address as a playback device before talking to the TV.
            if self._cec_ctl("--playback", "--osd-name", OSD_NAME) is None:
                return None
            self._registered = True
        return self._cec_ctl("--to", CEC_TV, *args)

    def power_status(self):
        """'on', 'standby', 'to-on' or 'to-standby'; None if the TV did not answer."""
        m = re.search(r"pwr-state:\s*([\w-]+)", self._send("--give-device-power-status") or "")
        return m.group(1) if m else None

    def tv_name(self):
        m = re.search(r"name:\s*(.+)", self._send("--give-osd-name") or "")
        return m.group(1).strip() if m else None

    def press(self, code):
        """Send one remote-control key press and release (a UI_* code).

        Returns 'sent' (the TV acknowledged the message, though it may still ignore the
        key), 'not acknowledged' (the TV didn't take it) or 'failed' (cec-ctl error)."""
        self.last_output = ""
        out = self._send("--user-control-pressed", f"ui-cmd={code:#04x}", "--user-control-released")
        # cec-ctl may exit non-zero when the TV doesn't acknowledge, so check its output either way.
        if re.search(r"not acknowledged|\bnack\b", out or self.last_output, re.IGNORECASE):
            return "not acknowledged"
        return "failed" if out is None else "sent"

    def power_on(self):
        """Wake the TV and switch it to this input."""
        return self._send("--image-view-on") is not None

    def standby(self):
        return self._send("--standby") is not None
