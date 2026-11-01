# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Raspberry Pi 5 voice remote for an LG webOS TV (UJ635V). The WM8960 Audio HAT's mics pick up commands ("remote volume up"), Whisper transcribes them offline, and the Pi controls the TV: power over HDMI-CEC, everything else over LG webOS on Wi-Fi. See `ARCHITECTURE.md` for the design and data flow.

## Documentation rules (from the project owner)

- With every change, update the matching sections of `README.md`: usage, requirements, system packages, pip installations, build commands.
- Record design decisions in `ARCHITECTURE.md`.
- When the owner flags a point as needing a developer note, add a row to the table in `DEVELOPER_NOTES.md`. After each bug-fix branch, add a fix summary there (problem and how it was fixed).
- `SKILLS.md` lists the roles used on the project. The primary role is embedded C developer.
- Commit changes in small steps with clear messages.
- Releases are annotated tags (`vX.Y.Z`), published as GitHub releases, with notes in `RELEASE.md`. Bugs found on the Pi go in `BUGS.md` (`BUG-NNN`, the version found in, status Open, then Fixed (awaiting Pi verification), then Verified). Fix them on a `bugfix/...` branch, reference the bug IDs in commit messages, and merge only after Pi verification.
- Feature work for the next release goes on `dev` and is merged to `main` afterwards.

## Commands

Run these on the Raspberry Pi, not on the Windows dev PC. This PC has no Python, so nothing can run here; only `bash -n` syntax checks work.

```bash
./setup.sh [--light] [--whisper-cpp] [--with-openai]   # apt packages, .venv, whisper.cpp on armhf
./voice-remote [--skip-checks] [--help]                # voice remote; runs until "remote exit"
./voice-remote --keys                                  # keyboard remote (stdlib only, no venv)
bash test/mic_check.sh [seconds] [card]                # ALSA-only HAT record/playback
bash test/hdmi_audio_check.sh [port]                   # HDMI audio diagnostics on the TV
.venv/bin/python test/sanity_test.py                   # Whisper -> espeak-ng echo, barge-in
```

There are no automated tests. `commands.parse()` is pure and the easiest piece to unit-test if tests are added.

## Code layout

The `voice_remote/` package uses relative imports. Run it from the repo root as `python -m voice_remote` (the launcher does this). `test/sanity_test.py` adds the repo root to `sys.path`.

- `app.py`: `VoiceRemote`. Startup (noise threshold, `TvControl.connect`, `StartupChecks`), then the `Voice.listen` → `commands.parse` → `execute` loop.
- `keys.py`: the keyboard remote; `__main__.py` imports it alone for `--keys`, so it never loads numpy.
- `commands.py`: wake word plus phrase table (longest match wins), numbers, apps → `Command`.
- `tv.py`: `TvControl`. `ACTIONS` maps each action to (label, CEC code, webOS action), and `APPS` maps names to webOS app ids. webOS first, CEC fallback; power always via CEC.
- `tv_link.py` (DRM/ALSA detection, `cec-ctl`), `webos_link.py` (own WebSocket client, SSDP, pairing key in `~/.config/voice_remote/lgtv.json`).
- `speech.py`: `Mic`, VAD (`record_utterance`), Whisper backends, `Speaker` (espeak-ng → aplay via `AudioRouter`), `speak_with_barge_in`, `Voice` (say, then listen), `add_common_args`, `build_audio`.
- `audio_output.py`: `AudioRouter`, TV HDMI audio when the TV is on, else the HAT speaker.
- `startup_checks.py`: 4 spoken checks sharing the app's `Voice` and `TvControl`; `run()` returns whether to launch.

Rules that came from bugs on the real hardware:
- `tv_link.py`, `webos_link.py`, `tv.py`, `commands.py` and `keys.py` must stay standard-library-only (`--keys` runs without a venv).
- The LG TV ignores CEC user-control keys (BUG-002). Use CEC only for power, and webOS for everything else.
- All speech output goes through `Speaker`. HDMI playback must be stereo 48 kHz (BUG-001).
- Never listen while the Pi is speaking on the HAT speaker: no echo cancellation (BUG-003/004). Use `Voice.say` (full playback, echo tail, flush) before listening. Barge-in only when output is the TV.

32-bit (`armhf`) vs 64-bit (`arm64`) Pi OS matters. Detect it with `dpkg --print-architecture`, never `uname -m` (a Pi 5 reports aarch64 on both).
- On armhf, numpy comes from apt through a `--system-site-packages` venv, and `faster-whisper` can't be installed.
- Speech recognition there uses whisper.cpp, built by `setup.sh` in `third_party/whisper.cpp` (gitignored) with `setarch linux32` and `-latomic`, `whisper-cli` target only.
- `--backend auto` picks faster-whisper, then whisper.cpp.
- The owner doesn't want paid APIs, so `openai` stays opt-in (`--with-openai`).
- Keep dependencies that lack armhf wheels out of `requirements.txt`.

`.gitattributes` forces LF line endings on `*.sh`, `*.py` and `voice-remote` so they run on the Pi.
