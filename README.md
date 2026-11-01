# Voice Remote

A Raspberry Pi voice remote for a TV. A microphone on an audio HAT picks up spoken
commands, the Pi recognises them, and the matching control command goes to the TV
over the micro-HDMI connection.

> Status: hardware bring-up. A sanity test for the microphone HAT is available
> (see [Build 101](#build-101-getting-started)); the remote itself is not written yet.

## Requirements

### Hardware
| Part | Model | Role |
|------|-------|------|
| Single-board computer | Raspberry Pi 5 | Runs voice capture, recognition and TV control |
| Audio HAT | WM8960 Audio HAT (WM8960 codec, on-board microphones) | Microphone input to the Pi |
| TV | LG (exact model TBD) | Target device, connected to the Pi by micro-HDMI |
| Cable | Micro-HDMI to HDMI | Pi 5 to TV link |

### Software
- Raspberry Pi OS for the Raspberry Pi 5 (version: TBD)
- WM8960 HAT driver / device-tree overlay (setup steps: TBD)
- Other software: TBD

## Installation

### System packages
Installed by `test/setup_test_env.sh`:

| Package | Why |
|---------|-----|
| `python3-venv`, `python3-dev` | Python virtual environment |
| `libportaudio2`, `portaudio19-dev` | Audio capture backend for `sounddevice` |
| `alsa-utils` | `arecord`, `aplay`, `alsamixer` |
| `espeak-ng` | Text-to-speech for the spoken replies |
| `v4l-utils` | `cec-ctl`, for HDMI-CEC: TV power state and remote-control keys |

### pip packages
From `test/requirements.txt`, installed into `.venv`:

| Package | Why |
|---------|-----|
| `numpy` | Audio buffers |
| `sounddevice` | Microphone capture |
| `faster-whisper` | Whisper speech-to-text on the Pi (default) |
| `openai` | OpenAI Whisper API (only with `--backend openai`) |

## Build 101 (getting started)

These steps take a fresh Raspberry Pi 5 to a working microphone test.

### 1. Enable the WM8960 Audio HAT
With the HAT fitted on the 40-pin header, add these lines to `/boot/firmware/config.txt`:

```
dtparam=i2s=on
dtoverlay=wm8960-soundcard
```

Reboot, then check the card is listed:

```bash
arecord -l    # expect a "wm8960" card
```

If no `wm8960` card appears, install the vendor driver instead:
https://github.com/waveshare/WM8960-Audio-HAT

### Where the sound comes out

The HAT's microphones are always the input. Speech output is chosen automatically
and re-checked every 10 seconds:

| TV state | Audio plays on |
|----------|----------------|
| Connected on HDMI and on | TV speakers (HDMI audio) |
| Connected but in standby | HAT speaker |
| Not connected, or its HDMI audio fails | HAT speaker |

"On" comes from asking the TV over HDMI-CEC. On the LG TV, enable **SIMPLINK
(HDMI-CEC)** in the TV settings. If the TV doesn't answer CEC, a connected TV counts
as on. Pass `--no-cec` to skip the CEC query, or `--output-device <alsa-device>` to
fix the output.

### 2. Get the code and install prerequisites

```bash
git clone https://github.com/NapsiPi/Voice_remote.git
cd Voice_remote
bash test/setup_test_env.sh
```

### 3. Check the HAT with plain ALSA (no Python)

```bash
bash test/mic_check.sh          # records 5 s, then plays it back
bash test/mic_check.sh 10 2     # 10 s, force sound card 2
```

Pass: you hear your own voice from the HAT's speaker or headphone jack.
Too quiet: run `alsamixer -c <card>`, press F4 and raise the capture levels.

### 4. Run the sanity test (speech in, speech out)

```bash
source .venv/bin/activate
python test/sanity_test.py
```

It measures the background noise for 1.5 s (stay quiet), says "Sanity test ready",
then loops:

1. You speak. Recording stops after 0.8 s of silence.
2. Whisper transcribes it and prints `Heard (...): '<your words>'`.
3. The Pi replies "You said: <your words>".
4. **Barge-in:** if you talk over the reply, playback stops and your new speech is
   transcribed instead.

Say **"stop test"** or press Ctrl+C to quit.

Pass: the printed text matches what you said, and the reply is audible.

Useful options (`python test/sanity_test.py --help` lists all):

| Option | Use |
|--------|-----|
| `--list-devices` | Show audio devices and their numbers |
| `--output-device plughw:<card>,0` | Always play replies on this device (default: automatic, TV or HAT) |
| `--no-cec` | Don't query the TV's power over HDMI-CEC |
| `--model tiny.en` | Faster, less accurate Whisper model (default `base.en`) |
| `--backend openai` | Use the OpenAI Whisper API; needs `export OPENAI_API_KEY=...` |
| `--threshold-factor 4` | Less sensitive to background noise |
| `--no-barge-in` / `--barge-in-factor 3` | Stop the reply interrupting itself |

The first local run downloads the Whisper model, so it needs internet once.

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No input device matching 'wm8960'` | Card not loaded: redo step 1, or pick a device from `--list-devices` |
| It never starts listening | Mic too quiet: raise capture in `alsamixer`, or lower `--threshold-factor` |
| The reply interrupts itself | The HAT speaker is picked up by its own mics: use headphones, or raise `--barge-in-factor` |
| Whisper prints text you didn't say on silence | Known Whisper behaviour on noise; raise `--threshold-factor` |
| Audio stays on the HAT with the TV on | Check `[audio] Output -> ...` in the log for the reason; enable SIMPLINK on the TV, or try `--no-cec` |
| `aplay: ... Device or resource busy` | Another sound server (e.g. PipeWire on the desktop image) holds the device; run from the Lite image or stop it |

## Usage

_TBD: the voice remote itself is not written yet._

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): system design and data flow
- [DEVELOPER_NOTES.md](DEVELOPER_NOTES.md): running notes and reminders for developers
- [SKILLS.md](SKILLS.md): skills and roles used on this project
