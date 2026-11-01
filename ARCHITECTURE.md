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
| Target TV | LG (exact model TBD), connected over micro-HDMI |

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

If `aplay` fails on the TV device, the router drops to the HAT for 60 s.

## Data flow

_TBD_

## Design decisions

_Each decision is recorded here when it is made._

| # | Date | Decision |
|---|------|----------|
| 1 | 2026-11-01 | Hardware bring-up uses a Python sanity test (`test/sanity_test.py`): Whisper speech-to-text (local `faster-whisper` by default, OpenAI Whisper API optional), `espeak-ng` text-to-speech, and energy-based voice detection with barge-in. This only proves the audio path works; the language for the remote itself is not decided yet. |
| 2 | 2026-11-01 | The HAT is used for microphone input only, and output follows the TV: TV speakers when it is connected and on, the HAT speaker otherwise. TV power is read over HDMI-CEC with `cec-ctl` (Linux CEC framework), because the HDMI hotplug signal often stays "connected" when the TV is in standby. |
