"""Controls an LG webOS TV over the local network (BUG-002).

The LG TV ignores CEC remote keys from the Pi, so volume, channels and navigation go
through webOS's "second screen" API (SSAP over WebSocket). CEC stays in use for
power, because webOS can't turn on a TV that is off.

Standard library only, so the light remote needs no pip packages. The first connection
shows a pairing prompt on the TV (accept it with the TV remote). The client key and
the TV's address are saved in ~/.config/voice_remote/lgtv.json.

On the TV, enable: Settings > Network > LG Connect Apps (webOS 3.x).
"""

import base64
import json
import os
import socket
import ssl
import struct
import urllib.parse
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "voice_remote" / "lgtv.json"
SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_TARGET = "urn:lge-com:service:webos-second-screen:1"
PAIRING_TIMEOUT_S = 60

PERMISSIONS = [
    "LAUNCH", "LAUNCH_WEBAPP", "APP_TO_APP", "CONTROL_AUDIO", "CONTROL_DISPLAY",
    "CONTROL_INPUT_JOYSTICK", "CONTROL_INPUT_MEDIA_PLAYBACK", "CONTROL_INPUT_TV",
    "CONTROL_MOUSE_AND_KEYBOARD", "CONTROL_POWER", "READ_INSTALLED_APPS",
    "READ_CURRENT_CHANNEL", "READ_INPUT_DEVICE_LIST", "READ_TV_CHANNEL_LIST",
    "READ_POWER_STATE", "WRITE_NOTIFICATION_TOAST",
]


class WebSocket:
    """Minimal WebSocket client (RFC 6455): text messages only, which is all SSAP uses."""

    def __init__(self, url, timeout=5.0):
        u = urllib.parse.urlsplit(url)
        port = u.port or (443 if u.scheme == "wss" else 80)
        sock = socket.create_connection((u.hostname, port), timeout)
        if u.scheme == "wss":
            # The TV uses a self-signed certificate.
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock = ctx.wrap_socket(sock, server_hostname=u.hostname)
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {u.hostname}:{port}\r\n"
                      "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        self.sock = sock
        self._buf = b""
        while b"\r\n\r\n" not in self._buf:
            self._buf += self._recv_some()
        header, self._buf = self._buf.split(b"\r\n\r\n", 1)
        status = header.split(b"\r\n", 1)[0].decode(errors="replace")
        if " 101 " not in status:
            sock.close()
            raise ConnectionError(f"WebSocket handshake refused: {status}")

    def settimeout(self, seconds):
        self.sock.settimeout(seconds)

    def _recv_some(self):
        chunk = self.sock.recv(4096)
        if not chunk:
            raise ConnectionError("connection closed by the TV")
        return chunk

    def _read(self, n):
        while len(self._buf) < n:
            self._buf += self._recv_some()
        data, self._buf = self._buf[:n], self._buf[n:]
        return data

    def _send_frame(self, opcode, data):
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            header = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
        elif n < 65536:
            header = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            header = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
        self.sock.sendall(header + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def send(self, text):
        self._send_frame(0x1, text.encode())

    def recv(self):
        message = b""
        while True:
            b1, b2 = self._read(2)
            opcode, n = b1 & 0x0F, b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            payload = self._read(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise ConnectionError("connection closed by the TV")
            if opcode == 0x9:
                self._send_frame(0xA, payload)  # answer pings
            elif opcode in (0x0, 0x1, 0x2):
                message += payload
                if b1 & 0x80:
                    return message.decode(errors="replace")

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_config(config):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def discover(timeout=3.0):
    """IP address of the first LG webOS TV answering an SSDP search, or None."""
    request = (f"M-SEARCH * HTTP/1.1\r\nHOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
               f"MAN: \"ssdp:discover\"\r\nMX: 2\r\nST: {SSDP_TARGET}\r\n\r\n")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.settimeout(timeout)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    try:
        s.sendto(request.encode(), SSDP_ADDR)
        while True:
            data, (ip, _) = s.recvfrom(2048)
            if SSDP_TARGET.encode() in data:
                return ip
    except OSError:  # includes the timeout
        return None
    finally:
        s.close()


class WebOsTv:
    def __init__(self, host, debug=False):
        self.host = host
        self.debug = debug
        self.ws = None
        self._pointer = None
        self._next_id = 0

    def connect(self):
        """Open the control connection and pair (prompt on the TV the first time)."""
        self.close()
        errors = []
        for url in (f"wss://{self.host}:3001", f"ws://{self.host}:3000"):
            try:
                self.ws = WebSocket(url)
                break
            except (OSError, ConnectionError) as e:
                errors.append(f"{url}: {e}")
        else:
            raise ConnectionError("; ".join(errors))
        self._register()

    def _send(self, message):
        if self.debug:
            print(f"[webos] > {json.dumps(message)}")
        self.ws.send(json.dumps(message))

    def _recv(self):
        text = self.ws.recv()
        if self.debug:
            print(f"[webos] < {text}")
        return json.loads(text)

    def _register(self):
        config = load_config()
        key = config.get("client_keys", {}).get(self.host)
        payload = {"forcePairing": False, "pairingType": "PROMPT",
                   "manifest": {"manifestVersion": 1, "permissions": PERMISSIONS}}
        if key:
            payload["client-key"] = key
        self._send({"type": "register", "id": "register_0", "payload": payload})
        self.ws.settimeout(PAIRING_TIMEOUT_S)
        while True:
            msg = self._recv()
            if msg.get("type") == "registered":
                break
            if msg.get("type") == "error":
                raise ConnectionError(f"TV refused pairing: {msg.get('error')}")
            if msg.get("payload", {}).get("pairingType") == "PROMPT":
                print(f"Accept the pairing prompt on the TV with the TV remote "
                      f"(waiting up to {PAIRING_TIMEOUT_S} s)...")
        self.ws.settimeout(5)
        config.setdefault("client_keys", {})[self.host] = msg["payload"]["client-key"]
        config["host"] = self.host
        save_config(config)

    def request(self, uri, payload=None):
        self._next_id += 1
        msg_id = f"req_{self._next_id}"
        self._send({"type": "request", "id": msg_id, "uri": uri, "payload": payload or {}})
        while True:
            msg = self._recv()
            if msg.get("id") == msg_id:
                if msg.get("type") == "error":
                    raise RuntimeError(f"{uri}: {msg.get('error')}")
                return msg.get("payload", {})

    def button(self, name):
        """Remote-control button (UP, DOWN, LEFT, RIGHT, ENTER, BACK, HOME, MUTE, 0-9, ...)."""
        if self._pointer is None:
            path = self.request("ssap://com.webos.service.networkinput/getPointerInputSocket")["socketPath"]
            self._pointer = WebSocket(path)
        self._pointer.send(f"type:button\nname:{name}\n\n")

    def do(self, action):
        """Run ("button", NAME) or ("request", URI[, payload]), reconnecting once if the TV
        dropped us."""
        kind, arg, *payload = action
        for attempt in (1, 2):
            try:
                if self.ws is None:
                    self.connect()
                return self.button(arg) if kind == "button" else self.request(arg, *payload)
            except (OSError, ConnectionError):
                self.close()
                if attempt == 2:
                    raise

    def volume_up(self):
        return self.do(("request", "ssap://audio/volumeUp"))

    def volume_down(self):
        return self.do(("request", "ssap://audio/volumeDown"))

    def toast(self, message):
        """Show a short message on the TV screen."""
        return self.request("ssap://system.notifications/createToast", {"message": message})

    def close(self):
        for ws in (self._pointer, self.ws):
            if ws is not None:
                ws.close()
        self._pointer = self.ws = None


def connect_webos(host=None, debug=False):
    """Connected WebOsTv, or None (with the reason printed). host: IP, else saved, else discovered."""
    host = host or load_config().get("host") or discover()
    if not host:
        print("  INFO  No LG webOS TV found on the network (pass --tv-ip, and check that "
              "LG Connect Apps is on)")
        return None
    tv = WebOsTv(host, debug)
    try:
        tv.connect()
    except (OSError, ConnectionError) as e:
        print(f"  FAIL  webOS TV at {host}: {e}")
        return None
    print(f"  PASS  webOS TV at {host} paired and connected")
    return tv
