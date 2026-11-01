# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Raspberry Pi voice remote: the microphone on a WM8960 Audio HAT picks up voice commands, and a Raspberry Pi 5 forwards them to an LG TV connected over micro-HDMI. See `ARCHITECTURE.md` for the design. No code has been written yet.

## Documentation rules (from the project owner)

- With every change, update the matching sections of `README.md`: requirements, system packages, pip installations, build commands and usage. Replace the `_TBD_` placeholders as things become known.
- Record design decisions in `ARCHITECTURE.md`.
- When the owner flags a point as needing a developer note, add a row to the table in `DEVELOPER_NOTES.md`.
- `SKILLS.md` lists the roles used on the project. The primary role is embedded C developer.
- Commit changes in small steps with clear messages.

## Commands

Run these on the Raspberry Pi, not on the Windows dev PC. This PC has no Python, so the scripts can't run here.

```bash
bash test/setup_test_env.sh                   # apt packages + .venv with test/requirements.txt
bash test/mic_check.sh [seconds] [card]       # ALSA-only record/playback check of the WM8960 HAT
source .venv/bin/activate && python test/sanity_test.py [--help]   # Whisper STT -> espeak-ng echo, with barge-in
```

`test/sanity_test.py` loop: an energy-threshold VAD (calibrated from the noise floor at startup) records an utterance, which is resampled to 16 kHz and transcribed (`--backend local|openai`). The reply plays through `aplay` while the mic keeps reading, and loud input during playback kills `aplay` and becomes the start of the next utterance. Keep "Build 101" in `README.md` in sync with any change to these scripts.

`.gitattributes` forces LF line endings on `*.sh` and `*.py` so the scripts run on the Pi.
