"""Entry point: python3 -m voice_remote [--keys] [options]

--keys starts the keyboard remote, which is imported on its own so it runs without
the speech packages (numpy, sounddevice, Whisper).
"""

import sys


def main():
    argv = sys.argv[1:]
    if "--keys" in argv:
        from .keys import main as keys_main
        return keys_main([a for a in argv if a != "--keys"])
    from .app import main as app_main
    return app_main(argv)


if __name__ == "__main__":
    sys.exit(main())
