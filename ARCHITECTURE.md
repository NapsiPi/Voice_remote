# Architecture

## Overview

The Raspberry Pi works as a voice-controlled TV remote:

```
 WM8960 mics ──▶ speech.py ──▶ Whisper ──▶ commands.py ──▶ tv.py ─┬─ HDMI-CEC (power) ──────▶ TV
 (I2S)           VAD, record   STT        wake word +            └─ webOS over Wi-Fi ───────▶ TV
                                           command parse             (volume, channels, nav)
 Spoken prompts: espeak-ng ──▶ audio_output.py ──▶ TV speakers (HDMI audio) or HAT speaker
```

## Hardware

| Part | Model |
|------|-------|
| Host | Raspberry Pi 5 |
| Microphone | WM8960 Audio HAT, mounted on the Pi's 40-pin header (I2S audio, I2C control; overlay `wm8960-soundcard`) |
| Target TV | LG UJ635V (webOS), micro-HDMI to the Pi, same Wi-Fi as the Pi |

## Code layout

| Module (`voice_remote/`) | Role | Dependencies |
|--------------------------|------|--------------|
| `__main__.py` | Entry point (`python -m voice_remote`); `--keys` imports only the keyboard remote | stdlib |
| `app.py` | Voice remote: startup, then the listen → parse → execute loop | speech stack |
| `keys.py` | Keyboard remote | stdlib |
| `commands.py` | Transcribed text → `Command` (wake word, phrases, numbers) | stdlib |
| `tv.py` | `TvControl`: one TV interface over CEC + webOS | stdlib |
| `tv_link.py` | TV detection (DRM, ALSA cards) and HDMI-CEC via `cec-ctl` | stdlib |
| `webos_link.py` | LG webOS client: WebSocket, SSDP discovery, pairing | stdlib |
| `speech.py` | Mic capture, VAD, Whisper backends, espeak-ng `Speaker`, barge-in, `Voice` | numpy, sounddevice |
| `audio_output.py` | `AudioRouter`: TV or HAT speaker | stdlib |
| `startup_checks.py` | The four spoken pre-launch checks | speech stack |

The launcher `./voice-remote` runs `.venv/bin/python -m voice_remote`, or system
`python3` for `--keys`. `test/` holds hardware test tools that import the package.

## Components

### 1. Audio capture and voice activity detection (`speech.py`)
`Mic` streams mono float32 blocks (30 ms) from the WM8960 through `sounddevice`. At
startup, the noise floor is measured and the speech threshold is set at
`threshold-factor ×` that floor. `record_utterance` starts on 3 loud blocks, keeps a
0.3 s pre-roll, and stops after 0.8 s of silence.

### 2. Speech recognition (`speech.py`)
Audio is resampled to 16 kHz and sent to one of these backends (`--backend auto`):
- faster-whisper (64-bit)
- whisper.cpp CLI (32-bit; clips padded to 1.5 s)
- OpenAI API (opt-in)

### 3. Command parsing (`commands.py`)
The text is normalised. Only words after the wake word ("remote") count. The phrase
table is matched, and the longest phrase wins. Numbers are read as digits or words,
and set repeat counts or channel numbers. "open <app>" maps to webOS app ids.
Without the wake word the result is `None` (ignored); with it but no match, the
result is `unknown` (the Pi says it didn't understand).

### 4. TV control (`tv.py`, `tv_link.py`, `webos_link.py`)
The LG TV ignores CEC user-control keys from the Pi (BUG-002), so control is split by
transport:

| Command | Transport | Why |
|---------|-----------|-----|
| Power on / standby | HDMI-CEC (`--image-view-on` / `--standby`) | Works on the LG TV; webOS can't wake a TV that is off |
| Volume, mute, channels, channel numbers, media, arrows, OK, Back, Home, apps, toasts | webOS SSAP over the LAN | The TV acts on these; it ignores them over CEC |

`TvControl.send` tries webOS first, then CEC. `webos_link.py`:
- minimal WebSocket client: `wss://<tv>:3001`, falling back to `ws://<tv>:3000`
- SSDP discovery (`urn:lge-com:service:webos-second-screen:1`)
- PROMPT pairing; the key is saved in `~/.config/voice_remote/lgtv.json`
- `ssap://` requests, and buttons through the pointer input socket
- one automatic reconnect

### 5. Audio output routing (`audio_output.py`)
All speech output goes through one router, which picks the device before each playback
(cached for 10 s):
1. Is a display connected? Check `/sys/class/drm/card*-HDMI-A-*/status`.
2. Is the TV on? Ask over CEC (`--give-device-power-status`). No answer means "assume on".
3. Is there HDMI audio? Look for `vc4hdmi<port>` in `/proc/asound/cards`, then use `hdmi:CARD=vc4hdmi<port>,DEV=0`.
4. Otherwise use the WM8960 speaker (`plughw:CARD=<wm8960 card>,DEV=0`).

HDMI audio only takes 2-channel audio, so `hdmi:` playback is converted to stereo
48 kHz (`write_hdmi_wav`). If `aplay` fails on HDMI, the router drops to the HAT for
60 s and keeps the error text.

### 6. Speaking and listening (`speech.py`: `Speaker`, `Voice`, barge-in)
`Voice.say` speaks the whole text, waits a 0.4 s echo tail, then flushes the mic.
This keeps the Pi from hearing itself (BUG-003). Barge-in (`speak_with_barge_in`,
used by the sanity test) defaults to `auto`: it's on only when output is the TV.
There's no echo cancellation, and the HAT speaker sits next to the mics (BUG-004).

### 7. Startup checks (`startup_checks.py`)
Four checks, each confirmed by a spoken yes/no: mic loopback, TV connection, speech
recognition, TV control (volume via `TvControl`). They share the app's `Voice` and
`TvControl`. `run()` returns whether to launch.

## Data flow (voice remote)

1. `app.py` starts the mic stream and measures noise, giving the threshold.
2. `TvControl.connect` finds the TV over CEC and over webOS (with pairing).
3. `StartupChecks.run()` runs unless `--skip-checks` is set.
4. Then it loops until "remote exit":
   1. `Voice.listen()` records an utterance and transcribes it.
   2. `commands.parse()` turns the text into a `Command`, or ignores it.
   3. `VoiceRemote.execute()` calls `TvControl` (webOS or CEC).
   4. A toast appears on the TV, the result is logged, and a failure is spoken.

## Design decisions

_Each decision is recorded here when it is made._

| # | Date | Decision |
|---|------|----------|
| 1 | 2026-11-01 | Hardware bring-up uses a Python sanity test (`test/sanity_test.py`): Whisper speech-to-text (local `faster-whisper` by default, OpenAI Whisper API optional), `espeak-ng` text-to-speech, and energy-based voice detection with barge-in. This only proves the audio path works; the language for the remote itself is not decided yet. |
| 2 | 2026-11-01 | The HAT is used for microphone input only, and output follows the TV: TV speakers when it is connected and on, the HAT speaker otherwise. TV power is read over HDMI-CEC with `cec-ctl` (Linux CEC framework), because the HDMI hotplug signal often stays "connected" when the TV is in standby. |
| 3 | 2026-11-01 | The voice remote launches only after four spoken startup checks (mic loopback, TV connection, speech recognition, TV control), each confirmed by the user saying yes or no. If any fail, the user is asked whether to launch anyway. |
| 4 | 2026-11-01 | On 32-bit Pi OS (armhf), speech recognition uses whisper.cpp (C/C++, built from source by `setup.sh`, run as a CLI per utterance). faster-whisper has no armhf builds, and the owner wants no paid API, so the OpenAI backend is opt-in only. |
| 5 | 2026-11-01 | A keyboard remote (first `test/light_remote.py`, now `voice_remote/keys.py`) checks the hardware with no speech stack. CEC keys are sent as numeric user-control codes from the spec, not cec-ctl's key names. |
| 6 | 2026-11-01 | TV control uses HDMI + Wi-Fi (owner's choice over HDMI-only or an IR blaster): CEC for power, LG webOS network control for everything else, because the LG TV silently ignores CEC user-control keys (BUG-002). |
| 7 | 2026-11-01 | v0.2.0 app layout: a `voice_remote/` package at the repo root with a `./voice-remote` launcher. Voice is the main mode and `--keys` is the keyboard mode. `test/` keeps only hardware test tools. Setup moved to the root (`setup.sh`, `requirements*.txt`). The TV-control and keyboard code stays stdlib-only, so `--keys` runs on a bare 32-bit Pi. |
| 8 | 2026-11-01 | Voice commands need a wake word ("remote") because the mics also hear the TV. There's no echo cancellation. Each executed command is shown as a webOS toast on the TV, meeting the owner's wish that app output goes to the TV. |
