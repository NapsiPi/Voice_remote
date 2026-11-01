"""Chooses where the app's audio plays.

TV connected on HDMI and on  -> the TV's speakers (HDMI audio)
otherwise                    -> the WM8960 HAT speaker
The HAT's microphones stay the input either way. The choice is re-checked every
few seconds, so turning the TV on or off moves the audio without a restart.
"""

import time
from dataclasses import dataclass

from tv_link import Cec, alsa_card, connected_hdmi_ports

TV_POWER_ON = (None, "on", "to-on")  # None: TV gave no CEC answer, trust the HDMI connection
TV_FAILED_HOLD_S = 60                # after HDMI audio fails, stay on the HAT this long


@dataclass(frozen=True)
class Output:
    name: str    # "tv", "hat", "fixed" or "default"
    device: str  # ALSA device for aplay; "" means the system default
    reason: str


class AudioRouter:
    def __init__(self, override=None, use_cec=True, recheck_s=10.0):
        self.override = override
        self.use_cec = use_cec
        self.recheck_s = recheck_s
        self._cecs = {}
        self._cached = None
        self._checked_at = 0.0
        self._tv_failed_until = 0.0
        self._tv_error = ""
        self._last_name = None

    def current(self):
        now = time.monotonic()
        if self._cached is None or now - self._checked_at > self.recheck_s:
            self._cached = self._decide(now)
            self._checked_at = now
            if self._cached.name != self._last_name:
                print(f"[audio] Output -> {self._cached.name}: {self._cached.reason}")
                self._last_name = self._cached.name
        return self._cached

    def refresh(self):
        self._cached = None

    def tv_failed(self, error=""):
        """aplay could not use the TV's HDMI audio: fall back to the HAT for a while."""
        self._tv_failed_until = time.monotonic() + TV_FAILED_HOLD_S
        self._tv_error = error
        self._cached = None

    def cec(self, port):
        if port not in self._cecs:
            self._cecs[port] = Cec(port)
        return self._cecs[port]

    def tv_status(self):
        """(port, power) of the first connected HDMI port, or (None, None) without a TV."""
        ports = connected_hdmi_ports()
        if not ports:
            return None, None
        port = ports[0]
        return port, (self.cec(port).power_status() if self.use_cec else None)

    def _decide(self, now):
        if self.override:
            return Output("fixed", self.override, "set with --output-device")

        port, power = self.tv_status()
        if port is None:
            reason = "no TV connected"
        elif now < self._tv_failed_until:
            reason = f"TV HDMI audio failed recently ({self._tv_error or 'no error text'})"
        elif power not in TV_POWER_ON:
            reason = f"TV on HDMI {port} is {power}"
        else:
            card = alsa_card(rf"vc4-?hdmi-?{port}")
            if card:
                state = "is on" if power else "power state unknown (no CEC answer)"
                return Output("tv", f"hdmi:CARD={card},DEV=0", f"TV on HDMI {port}, {state}")
            reason = f"no HDMI audio device for HDMI {port}"

        hat = alsa_card("wm8960")
        if hat:
            return Output("hat", f"plughw:CARD={hat},DEV=0", reason)
        return Output("default", "", f"{reason}, and no WM8960 card found")
