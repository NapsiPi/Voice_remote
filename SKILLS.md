# Skills

Roles and skill sets used on this project.

## 1. Embedded C developer

- C programming for embedded Linux on the Raspberry Pi
- Hardware interfaces: audio HAT, I2S/I2C, ALSA
- Talking to the TV over HDMI (e.g. HDMI-CEC)
- Resource-aware, reliable code for a device that runs continuously
- Building native code on the Pi (e.g. whisper.cpp on 32-bit ARM: `setarch`, `libatomic`)

## 2. Python application developer

- The `voice_remote` package: app structure, CLI options, entry points and launcher
- Standard-library-first code where it must run without a venv (keyboard remote, TV control)
- Audio in Python: `sounddevice`, `numpy`, WAV handling, resampling
- Virtual environments and packaging on Raspberry Pi OS (apt vs pip, 32-bit vs 64-bit wheels)

## 3. Speech and audio processing

- Voice activity detection and noise-floor calibration
- Speech-to-text with Whisper (faster-whisper, whisper.cpp) and choosing models for the Pi
- Text-to-speech (espeak-ng now; Piper or Pico planned, BUG-005)
- Echo and barge-in behaviour without acoustic echo cancellation

## 4. TV integration and networking

- HDMI-CEC with the Linux CEC framework (`cec-ctl`): power, monitoring, debugging
- LG webOS control over the LAN: WebSocket, SSAP, SSDP discovery, pairing
- HDMI audio on the Pi (`vc4hdmi`, IEC958, stereo 48 kHz)

## 5. Hardware test and release engineering

- Testing on the real device: diagnostic scripts, reading logs, reproducing bugs
- Bug tracking (`BUGS.md`), release notes (`RELEASE.md`), Git branching and tagging
  (see CLAUDE.md)
