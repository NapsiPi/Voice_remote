# Architecture

## Overview

The Raspberry Pi works as a voice-controlled TV remote:

```
 Microphone        Raspberry Pi                                 TV
 (audio HAT) ──▶ [ audio capture ] ──▶ [ command recognition ] ──▶ [ TV control ] ──micro-HDMI──▶
```

## Hardware

| Part | Model |
|------|-------|
| Host | Raspberry Pi 5 |
| Microphone | WM8960 Audio HAT, mounted on the Pi's 40-pin header |
| Target TV | LG UJ635V (webOS), micro-HDMI to the Pi, same Wi-Fi as the Pi |

## Components

### 1. Audio capture
Reads audio from the WM8960 HAT's microphones.
- The WM8960 codec talks to the Pi over I2S for audio and I2C for control. Driver / overlay details: TBD

### 2. Command recognition
Turns captured audio into a command such as "volume up" or "power off".
- Approach (wake word, speech-to-text engine, on-device or cloud): TBD
- Supported command set: TBD

### 3. TV control
Sends the recognised command to the TV over the HDMI link.
- Mechanism: TBD (HDMI-CEC is the usual way to control a TV over HDMI; LG brands its CEC support "SIMPLINK")

### 4. Audio output routing (`test/audio_output.py`, `test/tv_link.py`)
All speech output goes through one router, which picks the device before each playback
(cached for 10 s):

1. Is a display connected? Check `/sys/class/drm/card*-HDMI-A-*/status`.
2. Is the TV on? Ask it over HDMI-CEC with `cec-ctl --give-device-power-status` on `/dev/cec<port>`.
   No answer means "assume on".
3. Is there HDMI audio? Look for `vc4hdmi<port>` in `/proc/asound/cards`, then play on `hdmi:CARD=vc4hdmi<port>,DEV=0`.
4. Otherwise use the WM8960 speaker (`plughw:CARD=<wm8960 card>,DEV=0`).

HDMI audio on the Pi (an IEC958 device) only takes 2-channel audio, so everything sent
to an `hdmi:` device is first converted to stereo 48 kHz (`write_hdmi_wav`). If `aplay`
still fails on the TV device, the router drops to the HAT for 60 s and keeps the error
text in its reason.

### 5. Startup checks (`test/startup_checks.py`)
Runs before the voice remote: mic loopback, TV connection, speech recognition and TV
control (CEC volume up/down). Each check is confirmed by a spoken yes/no, transcribed
by Whisper. `--then` starts the remote afterwards. It reuses the sanity test's
building blocks (`build_audio`, `record_utterance`). Yes/no questions are spoken in
full, then a 0.4 s echo tail passes before it listens. There's no barge-in during
questions.

Barge-in (`sanity_test.speak_with_barge_in`) defaults to `auto`: it's enabled only
when output is the TV. There's no acoustic echo cancellation, and the HAT speaker
next to the mics would trigger it on the Pi's own voice. Stopping playback kills
`aplay`, whose expected "Interrupted system call" message is suppressed.

### 5a. TV control over webOS (`test/webos_link.py`)
The LG TV (webOS) ignores CEC user-control keys from the Pi (BUG-002), so control is
split by transport:

| Command | Transport | Why |
|---------|-----------|-----|
| Power on / standby | HDMI-CEC (`--image-view-on` / `--standby`) | Works on the LG TV; webOS can't wake a TV that is off |
| Volume, mute, channels, play/pause, arrows, OK, Back, Home, digits | webOS SSAP over the LAN | The TV acts on these; it ignores them over CEC |

`webos_link.py` uses only the standard library:
- a minimal WebSocket client: `wss://<tv>:3001`, falling back to `ws://<tv>:3000`
- SSDP discovery (`urn:lge-com:service:webos-second-screen:1`)
- PROMPT pairing; the client key is saved in `~/.config/voice_remote/lgtv.json`
- requests like `ssap://audio/volumeUp`
- buttons through the pointer input socket (`getPointerInputSocket`)

It reconnects once if the TV drops the connection.

### 6. Light keyboard remote (`test/light_remote.py`)
Uses only the standard library plus `cec-ctl`/`arecord`/`aplay`, with no speech
recognition. It checks for the WM8960 card and the TV's CEC link, then maps key
presses (read in cbreak mode) to CEC user-control codes (`tv_link.UI_*`). Power uses
`--image-view-on` / `--standby` rather than a key code.

## Data flow

_TBD_

## Design decisions

_Each decision is recorded here when it is made._

| # | Date | Decision |
|---|------|----------|
| 1 | 2026-11-01 | Hardware bring-up uses a Python sanity test (`test/sanity_test.py`): Whisper speech-to-text (local `faster-whisper` by default, OpenAI Whisper API optional), `espeak-ng` text-to-speech, and energy-based voice detection with barge-in. This only proves the audio path works; the language for the remote itself is not decided yet. |
| 2 | 2026-11-01 | The HAT is used for microphone input only, and output follows the TV: TV speakers when it is connected and on, the HAT speaker otherwise. TV power is read over HDMI-CEC with `cec-ctl` (Linux CEC framework), because the HDMI hotplug signal often stays "connected" when the TV is in standby. |
| 3 | 2026-11-01 | The voice remote launches only after four spoken startup checks (mic loopback, TV connection, speech recognition, TV control), each confirmed by the user saying yes or no. If any fail, the user is asked whether to launch anyway. |
| 4 | 2026-11-01 | On 32-bit Pi OS (armhf), speech recognition uses whisper.cpp (C/C++, built from source by `setup_test_env.sh`, run as a CLI per utterance). faster-whisper has no armhf builds, and the owner wants no paid API, so the OpenAI backend is opt-in only. |
| 5 | 2026-11-01 | A light test (`test/light_remote.py`) checks the hardware with no speech stack: HAT detected, TV reachable over CEC, keyboard keys sent as CEC remote commands. CEC keys are sent as numeric user-control codes from the spec, not cec-ctl's key names. |
| 6 | 2026-11-01 | TV control uses HDMI + Wi-Fi (owner's choice over HDMI-only or an IR blaster): CEC for power, LG webOS network control for everything else, because the LG TV silently ignores CEC user-control keys (BUG-002). |
