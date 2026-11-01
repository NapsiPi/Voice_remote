# Release Notes

## v0.1.1 (2026-11-01): bug fixes from the first Pi test

Merged from branch `bugfix/v0.1.0-bugs`. Fix summaries are in
[DEVELOPER_NOTES.md](DEVELOPER_NOTES.md#bug-fix-summary-bugfixv010-bugs-v010-to-v011);
full details are in [BUGS.md](BUGS.md).

### Fixed (verified on the Pi)
- **BUG-001** Speech now plays on the TV: audio is converted to stereo 48 kHz for HDMI.
- **BUG-002** TV volume and navigation work: they go over LG webOS on Wi-Fi, and CEC keeps power.
- **BUG-003** Startup checks wait for your spoken yes/no answer.
- **BUG-004** Barge-in no longer cuts replies on the HAT speaker (`--barge-in auto`).

### Added
- `test/hdmi_audio_check.sh`: HDMI audio diagnostics
- `test/webos_link.py`: LG webOS control (standard library only)
- Light remote: `--tv-ip`, `--no-webos`, `--webos-debug`, `--cec-debug`

### Known issues
- BUG-005: the spoken voice sounds robotic (low priority).

## v0.1.0 (2026-11-01): first hardware bring-up

First tagged release: test tooling to bring up the Raspberry Pi 5, the WM8960 Audio
HAT and the LG TV. The voice remote itself is not written yet.

### Contents
- `test/mic_check.sh`: ALSA record/playback check of the WM8960 HAT
- `test/sanity_test.py`: Whisper speech-to-text, then espeak-ng echo, with barge-in
- `test/startup_checks.py`: four spoken pre-launch checks with yes/no answers
- `test/light_remote.py`: keyboard to HDMI-CEC remote, no speech stack
- Audio output routing: TV when it is on, HAT speaker otherwise
- Speech recognition backends: faster-whisper (64-bit), whisper.cpp (32-bit), OpenAI API (opt-in)
- `test/setup_test_env.sh`: setup for 32-bit and 64-bit Pi OS, plus `--light`

### Tested on
Raspberry Pi 5 running 32-bit Raspberry Pi OS (`armhf` userland, 64-bit `rpi-v8`
kernel), WM8960 Audio HAT, LG TV over micro-HDMI.

### Worked
- TV power on / standby over HDMI-CEC (light remote, `p` key)
- whisper.cpp builds and transcribes on 32-bit (after the libatomic fix)
- The microphone captures speech (loopback peak level 0.0385)

### Known issues
See [BUGS.md](BUGS.md): BUG-001 to BUG-004 were found in this release.
