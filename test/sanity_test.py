#!/usr/bin/env python3
"""WM8960 Audio HAT sanity test: speak, and the Pi says it back.

Captures speech from the WM8960 microphones, transcribes it with Whisper (STT) and
reads the text back with espeak-ng (TTS). Talking over the reply interrupts it
(barge-in, when audio plays on the TV) and the new speech is transcribed instead.

Say "stop test" or press Ctrl+C to quit.
"""

import argparse
import sys
from pathlib import Path

import sounddevice as sd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root, for voice_remote

from voice_remote.speech import (  # noqa: E402
    add_common_args, build_audio, normalise, record_utterance, speak_with_barge_in,
    speech_threshold, transcribe,
)

EXIT_PHRASE = "stop test"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_common_args(p)
    args = p.parse_args()
    if args.list_devices:
        print(sd.query_devices())
        return

    transcriber, speaker, mic = build_audio(args)
    try:
        with mic.stream:
            threshold = speech_threshold(mic, args)
            preroll = speak_with_barge_in(
                mic, speaker, "Sanity test ready. Say something.", threshold, args) or []
            while True:
                if not preroll:
                    print(f"\nListening... (say '{EXIT_PHRASE}' to quit)")
                audio = record_utterance(mic, threshold, args, preroll)
                text = transcribe(transcriber, mic, audio)
                if not text:
                    preroll = []
                    continue
                if EXIT_PHRASE in normalise(text):
                    speaker.start("Stopping the test. Goodbye.")
                    speaker.wait()
                    break
                preroll = speak_with_barge_in(mic, speaker, f"You said: {text}", threshold, args) or []
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        speaker.stop()


if __name__ == "__main__":
    main()
