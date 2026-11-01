"""Turns transcribed speech into remote commands. Standard library only.

With a wake word (default "remote"), only speech containing it counts, and the
command is whatever follows it: "remote, volume up three", "remote channel 5",
"remote open youtube", "remote exit".
"""

from dataclasses import dataclass

from .tv import APPS

DEFAULT_WAKE_WORD = "remote"
MAX_REPEAT = 20

UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
         "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
         "eighteen", "nineteen"]
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
        "eighty": 80, "ninety": 90}
SMALL = {word: n for n, word in enumerate(UNITS)}

# Phrases are matched against the whole command text, longest first.
PHRASES = {
    "volume_up": ["volume up", "turn it up", "turn up", "louder", "increase volume", "increase the volume",
                  "raise volume", "raise the volume"],
    "volume_down": ["volume down", "turn it down", "turn down", "quieter", "softer", "decrease volume",
                    "decrease the volume", "lower volume", "lower the volume"],
    "mute": ["unmute", "mute"],
    "channel_up": ["channel up", "next channel"],
    "channel_down": ["channel down", "previous channel"],
    "power_off": ["power off", "turn off", "switch off", "standby", "tv off", "shut down"],
    "power_on": ["power on", "turn on", "switch on", "wake up", "tv on"],
    "up": ["move up", "go up", "up"],
    "down": ["move down", "go down", "down"],
    "left": ["move left", "go left", "left"],
    "right": ["move right", "go right", "right"],
    "ok": ["select", "okay", "ok", "enter", "choose", "confirm"],
    "back": ["go back", "back"],
    "home": ["home screen", "go home", "home"],
    "play": ["play", "resume"],
    "pause": ["pause"],
    "stop": ["stop"],
    "help": ["what can i say", "help", "commands"],
    "exit": ["exit remote", "quit remote", "stop remote", "exit", "quit", "goodbye"],
}
REPEATABLE = {"volume_up", "volume_down", "up", "down", "left", "right"}


@dataclass
class Command:
    action: str     # an ACTIONS key in tv.py, or channel, launch, power_on, power_off, help, exit, unknown
    arg: object = None  # repeat count, channel number or webOS app id
    label: str = ""     # what is shown and logged, e.g. "Volume up x3"


def normalise(text):
    return " ".join("".join(c if c.isalnum() else " " for c in text.lower()).split())


def parse_number(words):
    """First number in the words ("5", "five", "twenty five"), or None."""
    for i, word in enumerate(words):
        if word.isdigit():
            return int(word)
        if word in TENS:
            n = TENS[word]
            if i + 1 < len(words) and words[i + 1] in UNITS[1:10]:
                n += UNITS.index(words[i + 1])
            return n
        if word in SMALL:
            return SMALL[word]
    return None


def contains(words, phrase):
    p = phrase.split()
    return any(words[i:i + len(p)] == p for i in range(len(words) - len(p) + 1))


def strip_wake_word(words, wake_word):
    """Words after the wake word, or None if it wasn't said."""
    w = wake_word.split()
    for i in range(len(words) - len(w) + 1):
        if words[i:i + len(w)] == w:
            return words[i + len(w):]
    return None


def parse(text, wake_word=DEFAULT_WAKE_WORD, volume_step=2):
    """Command for the transcribed text. None when the wake word wasn't said (or nothing
    was), Command("unknown") when it was but no command matched."""
    words = normalise(text).split()
    if wake_word:
        words = strip_wake_word(words, normalise(wake_word))
        if words is None:
            return None
    if not words:
        return None
    phrase = " ".join(words)

    for verb in ("open", "launch", "start"):
        if words[0] == verb and len(words) > 1:
            name = " ".join(words[1:])
            if name in APPS:
                label, app_id = APPS[name]
                return Command("launch", app_id, f"Open {label}")

    if contains(words, "channel") and not (contains(words, "channel up") or contains(words, "channel down")):
        number = parse_number(words[words.index("channel") + 1:])
        if number is not None:
            return Command("channel", number, f"Channel {number}")

    matches = [(len(p), action, p) for action, ps in PHRASES.items() for p in ps if contains(words, p)]
    if not matches:
        return Command("unknown", phrase, f"Unknown: {phrase}")
    _, action, _ = max(matches)

    if action in REPEATABLE:
        count = parse_number(words)
        if count is None or count == 0:
            count = volume_step if action.startswith("volume") else 1
        count = min(count, MAX_REPEAT)
        label = action.replace("_", " ").capitalize() + (f" x{count}" if count > 1 else "")
        return Command(action, count, label)
    return Command(action, None, action.replace("_", " ").capitalize())


HELP_TEXT = ("Say {wake}, then a command. For example: {wake} volume up, {wake} volume down three, "
             "{wake} mute, {wake} channel up, {wake} channel five, {wake} open YouTube, {wake} home, "
             "{wake} up, down, left, right, {wake} OK, {wake} back, {wake} pause, {wake} power off. "
             "Say {wake} exit to stop the voice remote.")
