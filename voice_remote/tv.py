"""One TV interface for the remote.

Power goes over HDMI-CEC. Everything else goes over LG webOS on the network, because
the LG TV ignores CEC remote keys (BUG-002). CEC is the fallback when webOS isn't
available. Standard library only.
"""

import time

from .tv_link import (
    UI_CHANNEL_DOWN, UI_CHANNEL_UP, UI_DOWN, UI_EXIT, UI_LEFT, UI_MUTE, UI_NUMBER_0, UI_PAUSE,
    UI_PLAY, UI_RIGHT, UI_ROOT_MENU, UI_SELECT, UI_STOP, UI_UP, UI_VOLUME_DOWN, UI_VOLUME_UP,
    Cec, connected_hdmi_ports,
)
from .webos_link import connect_webos

# action -> (label, CEC user-control code, webOS action)
ACTIONS = {
    "up": ("Up", UI_UP, ("button", "UP")),
    "down": ("Down", UI_DOWN, ("button", "DOWN")),
    "left": ("Left", UI_LEFT, ("button", "LEFT")),
    "right": ("Right", UI_RIGHT, ("button", "RIGHT")),
    "ok": ("OK", UI_SELECT, ("button", "ENTER")),
    "back": ("Back", UI_EXIT, ("button", "BACK")),
    "home": ("Home", UI_ROOT_MENU, ("button", "HOME")),
    "volume_up": ("Volume up", UI_VOLUME_UP, ("request", "ssap://audio/volumeUp")),
    "volume_down": ("Volume down", UI_VOLUME_DOWN, ("request", "ssap://audio/volumeDown")),
    "mute": ("Mute", UI_MUTE, ("button", "MUTE")),
    "channel_up": ("Channel up", UI_CHANNEL_UP, ("request", "ssap://tv/channelUp")),
    "channel_down": ("Channel down", UI_CHANNEL_DOWN, ("request", "ssap://tv/channelDown")),
    "play": ("Play", UI_PLAY, ("request", "ssap://media.controls/play")),
    "pause": ("Pause", UI_PAUSE, ("request", "ssap://media.controls/pause")),
    "stop": ("Stop", UI_STOP, ("request", "ssap://media.controls/stop")),
    **{f"digit_{d}": (f"Number {d}", UI_NUMBER_0 + d, ("button", str(d))) for d in range(10)},
}

# Spoken app name -> webOS app id
APPS = {
    "youtube": ("YouTube", "youtube.leanback.v4"),
    "netflix": ("Netflix", "netflix"),
    "prime video": ("Prime Video", "amazon"),
    "amazon": ("Prime Video", "amazon"),
    "live tv": ("Live TV", "com.webos.app.livetv"),
    "settings": ("Settings", "com.palm.app.settings"),
}

WEBOS_ERRORS = (OSError, ConnectionError, RuntimeError)


class TvControl:
    def __init__(self, cec=None, webos=None):
        self.cec = cec
        self.webos = webos

    @classmethod
    def connect(cls, tv_ip=None, use_webos=True, cec_debug=False, webos_debug=False):
        """Find the TV over HDMI-CEC and webOS, printing a PASS/FAIL line for each."""
        cec = None
        ports = connected_hdmi_ports()
        if not ports:
            print("  FAIL  No TV connected on HDMI (no CEC power control)")
        else:
            cec = Cec(ports[0], debug=cec_debug)
            if not cec.available:
                print(f"  FAIL  TV on HDMI {ports[0]}, but CEC is unavailable ({cec.dev} or cec-ctl "
                      "missing; run ./setup.sh --light)")
                cec = None
            else:
                power, name = cec.power_status(), cec.tv_name()
                if power is None and name is None:
                    print(f"  WARN  TV on HDMI {ports[0]} does not answer CEC: enable SIMPLINK on the TV")
                else:
                    print(f"  PASS  TV on HDMI {ports[0]} answers CEC (name: {name or '?'}, "
                          f"power: {power or '?'})")
        webos = connect_webos(tv_ip, webos_debug) if use_webos else None
        return cls(cec, webos)

    @property
    def available(self):
        return self.cec is not None or self.webos is not None

    def send(self, action):
        """Send one ACTIONS entry. Returns a short result for the log."""
        _, code, webos_action = ACTIONS[action]
        if self.webos is not None:
            try:
                self.webos.do(webos_action)
                return "sent via webOS"
            except WEBOS_ERRORS as e:
                if self.cec is None:
                    return f"webOS failed: {e}"
                return f"webOS failed ({e}); CEC: {self.cec.press(code)}"
        if self.cec is not None:
            return f"{self.cec.press(code)} via CEC (code {code:#04x})"
        return "no TV control available"

    def repeat(self, action, times, gap_s=0.25):
        result = ""
        for i in range(times):
            if i:
                time.sleep(gap_s)
            result = self.send(action)
        return result

    def channel(self, number):
        if self.webos is not None:
            try:
                self.webos.do(("request", "ssap://tv/openChannel", {"channelNumber": str(number)}))
                return "sent via webOS"
            except WEBOS_ERRORS as e:
                if self.cec is None:
                    return f"webOS failed: {e}"
        for digit in str(number):  # CEC fallback: type the digits
            result = self.send(f"digit_{digit}")
            time.sleep(0.15)
        return result

    def launch(self, app_id):
        if self.webos is None:
            return "opening apps needs webOS"
        try:
            self.webos.do(("request", "ssap://system.launcher/launch", {"id": app_id}))
            return "sent via webOS"
        except WEBOS_ERRORS as e:
            return f"webOS failed: {e}"

    def power_on(self):
        if self.cec is None:
            return "turning the TV on needs HDMI-CEC"
        return "sent via CEC" if self.cec.power_on() else "CEC failed"

    def power_off(self):
        if self.cec is not None:
            return "sent via CEC" if self.cec.standby() else "CEC failed"
        if self.webos is not None:
            try:
                self.webos.do(("request", "ssap://system/turnOff"))
                return "sent via webOS"
            except WEBOS_ERRORS as e:
                return f"webOS failed: {e}"
        return "no TV control available"

    def toggle_power(self):
        if self.cec is not None and self.cec.power_status() not in ("on", "to-on"):
            return "Power on", self.power_on()
        return "Power off", self.power_off()

    def toast(self, message):
        """Show a message on the TV screen (webOS only); errors are ignored."""
        if self.webos is not None:
            try:
                self.webos.do(("request", "ssap://system.notifications/createToast", {"message": message}))
            except WEBOS_ERRORS:
                pass

    def close(self):
        if self.webos is not None:
            self.webos.close()
