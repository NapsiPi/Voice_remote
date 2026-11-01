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

    def __init__(self, port):
        self.dev = f"/dev/cec{port}"
        self.available = bool(shutil.which("cec-ctl")) and Path(self.dev).exists()
        self._registered = False

    def _cec_ctl(self, *args, timeout=5):
        try:
            out = subprocess.run(["cec-ctl", "-d", self.dev, *args],
                                 capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout if out.returncode == 0 else None

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

    def press(self, key):
        """Send one remote-control key, named as cec-ctl's ui-cmd (e.g. volume-up)."""
        return self._send("--user-control-pressed", f"ui-cmd={key}", "--user-control-released") is not None
