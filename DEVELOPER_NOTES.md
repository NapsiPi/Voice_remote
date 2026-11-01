# Developer Notes

Running reminders and follow-ups for developers. Add an entry whenever a point needs
following up.

| # | Date | Note | Status |
|---|------|------|--------|
| 1 | 2026-11-01 | Project set up: README, architecture doc, developer notes and skills file created. | Done |
| 2 | 2026-11-01 | Released **v0.1.0** (tag `v0.1.0`, notes in [RELEASE.md](RELEASE.md)). First Pi test found BUG-001 to BUG-004, tracked in [BUGS.md](BUGS.md). Fixes are on branch `bugfix/v0.1.0-bugs`; merge to `main` after they are verified on the Pi. | Done: merged as v0.1.1 |
| 3 | 2026-11-01 | Bug-fix summary for branch `bugfix/v0.1.0-bugs`, released as tag **v0.1.1** (below). | Done |
| 4 | 2026-11-01 | v0.2.0 development on branch `dev`: the voice remote app (`./voice-remote`), the keyboard remote moved into the app (`--keys`), and setup moved to the root (`./setup.sh`). `dev` is merged to `main`. Verify on the Pi, then tag **v0.2.0**. Old commands changed: see RELEASE.md v0.2.0, "Changed". | Open: Pi verification |
| 5 | 2026-11-01 | Branching strategy agreed: `dev` for development, verified on the Pi (tag `vX.Y.Z-rcN`) before merging to `main`; `bugfix/...` branches for release bugs; `main` only gets verified releases. The early v0.2.0 merge was a one-off. Rules and the BUGS.md workflow are in CLAUDE.md. | Done |

## Bug-fix summary: `bugfix/v0.1.0-bugs`, v0.1.0 to v0.1.1

All four were verified by the owner on the Pi. Details are in [BUGS.md](BUGS.md).

| Bug | Problem | How it was fixed |
|-----|---------|------------------|
| BUG-001 | Speech never played on the TV | The Pi's HDMI audio accepts only 2-channel audio, and espeak-ng writes mono 22 kHz, so `aplay` failed and the output fell back to the HAT. Every WAV is now converted to stereo 48 kHz (`write_hdmi_wav`) before playing on `hdmi:`. `aplay` errors are shown in the router's reason. New `test/hdmi_audio_check.sh` diagnoses HDMI audio. |
| BUG-002 | TV ignored volume/arrow keys | Monitoring showed the LG TV takes CEC user-control keys but silently ignores them (it only broadcasts its vendor ID). Fix: HDMI + Wi-Fi. CEC still handles power; everything else goes over LG webOS network control (`webos_link.py`, standard library only, with discovery, pairing and a saved key). `--cec-debug` and `cec-ctl -M` were added for diagnosis. |
| BUG-003 | Startup checks didn't wait for yes/no | The question played on the HAT speaker, the mics heard it, and that echo was taken as the answer. whisper.cpp also dropped clips under 1 s. Now it speaks the whole question, waits 0.4 s for the echo, then listens up to 8 s with 3 attempts. Short clips are padded to 1.5 s. |
| BUG-004 | Barge-in misfired; `aplay` "Interrupted system call" | Not a PCM buffer conflict: with no echo cancellation, the Pi's own voice triggered barge-in, which killed `aplay` mid-write. `--barge-in auto` (default) now enables barge-in only when audio plays on the TV. The expected `aplay` error after an intentional stop is suppressed. |

Still open after v0.1.1: BUG-005 (robotic espeak-ng voice, low priority; planned fix:
Piper or Pico).

Lessons for later work:
- The LG TV needs CEC only for power; use webOS for every other command.
- The HAT speaker sits next to the mics, so never listen while speaking on the HAT.
- On armhf, whisper.cpp needs `setarch linux32` and `-latomic` to build.
