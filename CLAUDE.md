# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Raspberry Pi 5 voice remote for an LG webOS TV (UJ635V). The WM8960 Audio HAT's mics pick up commands ("remote volume up"), Whisper transcribes them offline, and the Pi controls the TV: power over HDMI-CEC, everything else over LG webOS on Wi-Fi. See `ARCHITECTURE.md` for the design and data flow.

## Documentation rules (from the project owner)

- With every change, update the matching sections of `README.md`: usage, requirements, system packages, pip installations, build commands.
- Record design decisions in `ARCHITECTURE.md`.
- When the owner flags a point as needing a developer note, add a row to the table in `DEVELOPER_NOTES.md`. After each bug-fix branch, add a fix summary there (problem and how it was fixed).
- `SKILLS.md` lists the roles used on the project: embedded C developer (primary), Python application developer, speech/audio processing, TV integration/networking, and hardware test/release engineering. Add a role when the work needs one that isn't listed.
- Commit changes in small steps with clear messages. Reference bug IDs (`BUG-NNN`) in fix commits.

## Git branching and releases

| Branch | Purpose | Merged into |
|--------|---------|-------------|
| `main` | Stable, verified releases only. Everybody uses it. Release tags `vX.Y.Z` live here. | n/a |
| `dev` | Normal development for the next release. | `main`, only after the owner verifies it on the Pi |
| `bugfix/<version>-bugs` (e.g. `bugfix/v0.1.0-bugs`) | Fixes for bugs found in a release; branched from that release on `main`. | `main` after Pi verification, then also into `dev` |

Rules:
1. Never merge `dev` into `main` before Pi verification. (v0.2.0 was merged early; that was a one-off, not the process.)
2. To verify `dev`, tag it as a release candidate `vX.Y.Z-rcN` (e.g. `v0.3.0-rc1`). The owner tests that tag on the Pi.
3. After the owner confirms, merge with `git merge --no-ff dev` into `main`. Then tag `vX.Y.Z` on `main`, publish it as a GitHub release with `gh release create`, and add its notes to `RELEASE.md`.
4. Bug fixes work the same way. Fix on the bugfix branch, the owner verifies on the Pi, then merge to `main` and tag a patch release (`vX.Y.Z+1`). Merge `main` back into `dev` so the fixes aren't lost.
5. Don't rewrite pushed history. Use a new commit instead of amending.

## When to update BUGS.md

- **The owner reports a problem on the Pi:** add `BUG-NNN` with the version it was found in, a severity (High/Medium/Low), status **Open**, and the symptom in the owner's words. Add it to the "Open bugs" list.
- **The cause is found:** record it under the bug (and say whether it's confirmed or only likely).
- **A fix is committed:** set **Fixed (awaiting Pi verification)**, and describe the fix and how to verify it on the Pi.
- **The owner confirms on the Pi:** set **Verified** and remove the bug from the "Open bugs" list.
- **At release time:** list the fixed bugs in `RELEASE.md` and the still-open ones under "Known issues". After a bug-fix branch, add a fix summary to `DEVELOPER_NOTES.md`.
- Only the owner can verify a bug. Never mark a bug Verified on your own: nothing can run on this Windows PC.

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
