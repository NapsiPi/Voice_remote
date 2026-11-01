"""Voice remote: control the LG TV by voice until you say "remote exit".

Startup:
  1. Measure the background noise.
  2. Connect to the TV (HDMI-CEC for power, webOS for the rest; pair on first use).
  3. Run the four spoken startup checks (skip with --skip-checks).
Then listen continuously. Speech that starts with the wake word (default "remote") is
a command: "remote volume up", "remote channel five", "remote open YouTube",
"remote help", "remote exit". Each command is shown on the TV as a short message.
"""

import argparse

import sounddevice as sd

from . import __version__
from .commands import DEFAULT_WAKE_WORD, HELP_TEXT, parse
from .speech import Voice, add_common_args, build_audio, speech_threshold
from .startup_checks import StartupChecks, add_check_args
from .tv import ACTIONS, TvControl
from .webos_link import load_config


class VoiceRemote:
    def __init__(self, args):
        self.args = args
        self.transcriber, self.speaker, self.mic = build_audio(args)
        self.voice = None
        self.tv = None

    def run(self):
        with self.mic.stream:
            self.voice = Voice(self.transcriber, self.speaker, self.mic,
                               speech_threshold(self.mic, self.args), self.args)
            print("== Connecting to the TV ==")
            if not self.args.no_webos and not load_config().get("client_keys"):
                self.voice.say("If the TV asks to pair with the voice remote, accept it with the TV remote.")
            self.tv = TvControl.connect(self.args.tv_ip, not self.args.no_webos)

            if not self.args.skip_checks and not StartupChecks(self.voice, self.tv, self.args).run():
                return 1
            self.listen_for_commands()
        return 0

    def listen_for_commands(self):
        wake = self.args.wake_word
        self.voice.say(f"Voice remote ready. Say {wake} followed by a command, "
                       f"for example, {wake} volume up. Say {wake} help to hear more."
                       if wake else "Voice remote ready. Say a command, for example, volume up.")
        while True:
            print(f"\n[listening] say '{wake + ' ' if wake else ''}<command>'...")
            text = self.voice.listen()
            command = parse(text, wake, self.args.volume_step)
            if command is None:
                continue  # no wake word: someone talking, or the TV
            print(f"[command] {command.label}")
            if command.action == "exit":
                self.voice.say("Voice remote stopped. Goodbye.")
                return
            if command.action == "unknown":
                self.voice.say("Sorry, I didn't understand that.")
                continue
            if command.action == "help":
                self.voice.say(HELP_TEXT.format(wake=wake or ""))
                continue
            result = self.execute(command)
            print(f"[command] {command.label}: {result}")
            if self.args.toasts:
                self.tv.toast(command.label)
            if self.args.confirm:
                self.voice.say(command.label)
            if not result.startswith("sent"):
                self.voice.say(f"{command.label} failed.")

    def execute(self, command):
        if command.action in ACTIONS:
            return self.tv.repeat(command.action, command.arg or 1)
        if command.action == "channel":
            return self.tv.channel(command.arg)
        if command.action == "launch":
            return self.tv.launch(command.arg)
        if command.action == "power_on":
            return self.tv.power_on()
        if command.action == "power_off":
            return self.tv.power_off()
        return f"unsupported command {command.action}"

    def close(self):
        self.speaker.stop()
        if self.tv is not None:
            self.tv.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="voice-remote", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"voice-remote {__version__}")
    p.add_argument("--keys", action="store_true", help="keyboard remote instead of voice (no speech stack)")
    p.add_argument("--skip-checks", action="store_true", help="skip the four startup checks")
    p.add_argument("--wake-word", default=DEFAULT_WAKE_WORD,
                   help=f"word that starts every command (default: {DEFAULT_WAKE_WORD}; '' = none, "
                        "not recommended while the TV is playing sound)")
    p.add_argument("--volume-step", type=int, default=2,
                   help="volume steps for 'volume up/down' without a number (default: 2)")
    p.add_argument("--no-toasts", dest="toasts", action="store_false",
                   help="don't show each command as a message on the TV")
    p.add_argument("--confirm", action="store_true", help="speak each command back")
    p.add_argument("--no-webos", action="store_true", help="control the TV over HDMI-CEC only")
    add_check_args(p)
    add_common_args(p)
    args = p.parse_args(argv)
    if args.list_devices:
        print(sd.query_devices())
        return 0

    remote = VoiceRemote(args)
    try:
        return remote.run()
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    finally:
        remote.close()
