# Voice Remote

A Raspberry Pi 5 voice remote for an LG webOS TV. The microphone on a WM8960 Audio HAT
picks up spoken commands such as "remote, volume up". The Pi recognises them offline
with Whisper and controls the TV: power over HDMI-CEC, and everything else over LG
webOS on the local network.

> Status: **v0.2.0 in development** on branch `dev`. The voice remote app is new and
> not yet verified on the Pi. The last release is **v0.1.1**, with hardware bring-up
> verified. Release history is in [RELEASE.md](RELEASE.md), and open bugs are in
> [BUGS.md](BUGS.md).

## Quick start

```bash
git clone https://github.com/NapsiPi/Voice_remote.git
cd Voice_remote
./setup.sh                 # once: system packages, .venv, Whisper (see Installation)
./voice-remote             # voice remote: startup checks, then voice commands
./voice-remote --keys      # keyboard remote: no speech stack needed
```

The voice remote runs until you say **"remote exit"** or press Ctrl+C.

## Usage

### Voice remote: `./voice-remote`

On start it:
1. Measures the background noise for 1.5 s (stay quiet).
2. Connects to the TV. On first use, the TV shows a pairing prompt: accept it with the
   TV remote.
3. Runs the four spoken [startup checks](#startup-checks). `--skip-checks` skips them.
4. Says "Voice remote ready", then listens.

Every command starts with the wake word **"remote"**. Speech without it (people
talking, the TV itself) is ignored.

| Say | The TV does |
|-----|-------------|
| "remote volume up" / "remote louder" | Volume up 2 steps (`--volume-step`) |
| "remote volume down five" | Volume down 5 steps |
| "remote mute" / "remote unmute" | Toggle mute |
| "remote channel up" / "remote next channel" | Channel up (and down) |
| "remote channel twelve" / "remote channel 12" | Go to channel 12 |
| "remote up" / "down" / "left" / "right" (optionally "… three") | Move in menus |
| "remote OK" / "remote select" | OK |
| "remote back" / "remote home" | Back / Home |
| "remote play" / "pause" / "stop" | Media controls |
| "remote open YouTube" (Netflix, Prime Video, Live TV, Settings) | Opens the app |
| "remote power off" / "remote power on" | Standby / wake (HDMI-CEC) |
| "remote help" | Speaks the list of commands |
| "remote exit" | Stops the voice remote |

Each command is printed (`[command] Volume up x2: sent via webOS`) and shown on the
TV as a short message. If a command fails, the Pi says so.

| Option | Use |
|--------|-----|
| `--skip-checks` | Start listening right away |
| `--wake-word WORD` | Change the wake word. `''` turns it off, which isn't recommended while the TV plays sound |
| `--volume-step N` | Steps for "volume up/down" without a number (default 2) |
| `--no-toasts` | Don't show commands on the TV |
| `--confirm` | Speak each command back |
| `--tv-ip ADDRESS` | The TV's address if discovery fails |
| `--no-webos` | HDMI-CEC only (the LG TV then only does power) |
| `--model tiny.en` / `base.en` | Faster vs. more accurate speech recognition |
| `--list-devices`, `--input-device`, `--output-device`, `--no-cec`, `--threshold-factor`, … | Audio options; `./voice-remote --help` lists all |

### Keyboard remote: `./voice-remote --keys`

No speech stack needed: it runs with system Python, plus `alsa-utils` and `v4l-utils`
(`./setup.sh --light`). Run it on the Pi's keyboard or over SSH. It checks the HAT and
the TV, then:

| Key | TV command | Key | TV command |
|-----|-----------|-----|-----------|
| Arrows | Up / Down / Left / Right | Enter | OK |
| `b`, Backspace | Back | `h` | Home |
| `+` / `-` | Volume up / down | `m` | Mute |
| `]` / `[` | Channel up / down | `0`–`9` | Numbers |
| `>` | Play | Space | Pause |
| `p` | Power on / standby | `t` | Mic loopback: record 3 s, play on the HAT |
| `?` | Help | `q` | Quit |

Options: `--tv-ip`, `--no-webos`, `--cec-debug` (print every `cec-ctl` call) and
`--webos-debug` (print every webOS message).

### Startup checks

The voice remote talks you through four checks first. **Answer each question by
saying "yes" or "no" after it finishes speaking.** The log shows `[listening] say yes
or no`; it waits 8 s and asks up to three times.

| # | Check | What happens | Passes when |
|---|-------|--------------|-------------|
| 1 | Microphone loopback | Records 4 s (`--loopback-seconds`) and plays it back | Sound was captured and you say **yes** to "Did you hear yourself clearly?" |
| 2 | TV connection | Finds the TV on HDMI and checks it's on over CEC; asks you to turn it on if it's in standby | Audio switches to the TV and you say **yes** to "Can you hear it from the TV?" |
| 3 | Speech recognition | "Please say a short sentence"; Whisper transcribes it | You say **yes** to "I heard: …. Is that right?" |
| 4 | TV control | Volume up ×2, then down ×2 (webOS, else CEC); skipped if the TV can't be reached | You say **yes** to "Did the TV volume go up and then back down?" |

It prints a PASS/FAIL/SKIP table. If everything passes it says "We are launching the
voice remote". If something failed, it asks whether to launch anyway.

### Where the sound comes out

The HAT's microphones are always the input. Speech output is re-checked every 10 s:

| TV state | Audio plays on |
|----------|----------------|
| Connected on HDMI and on | TV speakers (HDMI audio, converted to stereo 48 kHz) |
| Connected but in standby | HAT speaker |
| Not connected, or its HDMI audio fails | HAT speaker |

### How the TV is controlled

The LG TV ignores CEC remote keys (BUG-002), so control is split:
- **Power:** HDMI-CEC.
- **Everything else:** LG webOS over Wi-Fi/LAN, falling back to CEC.

**One-time LG TV setup:**
1. Put the TV on the same network as the Pi.
2. Turn on **Settings → Network → LG Connect Apps**, and **SIMPLINK (HDMI-CEC)**.
3. Accept the pairing prompt on first use.

The pairing key and TV address are saved in `~/.config/voice_remote/lgtv.json`.
Delete that file to pair again.

## Requirements

### Hardware
| Part | Model | Role |
|------|-------|------|
| Single-board computer | Raspberry Pi 5 | Runs voice capture, recognition and TV control |
| Audio HAT | WM8960 Audio HAT (WM8960 codec, on-board microphones) | Microphone input to the Pi |
| TV | LG UJ635V (webOS) | Target device: micro-HDMI for picture, sound and power (CEC); Wi-Fi for remote control (webOS) |
| Cable | Micro-HDMI to HDMI | Pi 5 to TV link |

### Software
- Raspberry Pi OS Bookworm or later, 32-bit or 64-bit (64-bit recommended), with Python 3.10+
- WM8960 overlay enabled (see [Enable the WM8960 Audio HAT](#1-enable-the-wm8960-audio-hat))

## Installation

### 1. Enable the WM8960 Audio HAT
With the HAT fitted on the 40-pin header, add these lines to `/boot/firmware/config.txt`:

```
dtparam=i2s=on
dtoverlay=wm8960-soundcard
```

Reboot, then check `arecord -l` lists a `wm8960` card. If it doesn't, install the
vendor driver: https://github.com/waveshare/WM8960-Audio-HAT

### 2. Run the setup script

```bash
./setup.sh                  # voice remote: system packages, .venv, speech recognition
./setup.sh --light          # keyboard remote only: alsa-utils + v4l-utils
./setup.sh --whisper-cpp    # 64-bit: also build whisper.cpp
./setup.sh --with-openai    # also install the paid OpenAI Whisper client
```

It detects 32/64-bit, installs everything, then import-checks it. If it ends with
`Done.`, the install worked.

### System packages

| Package | Why |
|---------|-----|
| `python3-venv`, `python3-dev` | Python virtual environment |
| `libportaudio2`, `portaudio19-dev` | Audio capture backend for `sounddevice` |
| `alsa-utils` | `arecord`, `aplay`, `alsamixer`, `speaker-test` |
| `espeak-ng` | Text-to-speech for the spoken replies |
| `v4l-utils` | `cec-ctl`, for HDMI-CEC: TV power |
| `git`, `cmake`, `build-essential`, `curl` | Building whisper.cpp and downloading its models (32-bit, or `--whisper-cpp`) |
| `python3-numpy`, `python3-cffi` | 32-bit only: prebuilt instead of compiled by pip |

### pip packages

| Package | File | Why |
|---------|------|-----|
| `numpy` | `requirements.txt` | Audio buffers (apt `python3-numpy` on 32-bit) |
| `sounddevice` | `requirements.txt` | Microphone capture |
| `faster-whisper` | `requirements-local-whisper.txt` | Whisper on the Pi, **64-bit only** |
| `openai` | `requirements-openai.txt` | Paid OpenAI Whisper API; only with `--with-openai` |

The keyboard remote and the TV control code (`tv_link.py`, `webos_link.py`, `tv.py`,
`commands.py`, `keys.py`) use only the Python standard library.

### Speech recognition backends

| Backend | `--backend` | OS | Cost | Notes |
|---------|-------------|----|------|-------|
| faster-whisper | `local` | 64-bit | Free, offline | Default model `base.en` |
| whisper.cpp | `whispercpp` | 32- and 64-bit | Free, offline | Built into `third_party/whisper.cpp`; default model `tiny.en`, `base.en` also downloaded |
| OpenAI API | `openai` | any | Paid per minute | Needs `--with-openai` and `OPENAI_API_KEY` |

The default `--backend auto` picks `local` if it's installed, otherwise `whispercpp`.

### 32-bit vs 64-bit Raspberry Pi OS

Check with `dpkg --print-architecture`: `arm64` = 64-bit, `armhf` = 32-bit. Don't rely
on `uname -m`: a Pi 5 reports `aarch64` even on the 32-bit OS, because its kernel is
64-bit (`-rpi-v8`). `getconf LONG_BIT` shows the userland.

| | 64-bit (`arm64`) | 32-bit (`armhf`) |
|---|---|---|
| numpy | pip wheel | apt `python3-numpy` |
| faster-whisper | Yes (default) | **Not available** (no armhf builds of `ctranslate2`/`onnxruntime`) |
| Speech recognition | faster-whisper | **whisper.cpp**, built from source |

On armhf, `setup.sh` builds whisper.cpp under `setarch linux32` and links `libatomic`,
building only `whisper-cli`. It ends with a smoke test on `samples/jfk.wav`. If the
build fails, try a release tag: `WHISPER_CPP_REF=<tag> ./setup.sh`
(https://github.com/ggml-org/whisper.cpp/tags).

## Hardware test tools (`test/`)

For bringing up or debugging the hardware. The voice remote doesn't need them.

| Tool | Checks |
|------|--------|
| `bash test/mic_check.sh [seconds] [card]` | HAT microphone and speaker with plain ALSA (records, then plays back) |
| `bash test/hdmi_audio_check.sh [port]` | TV on HDMI? `vc4hdmi` audio card? Plays `speaker-test` (2 ch, 48 kHz) on the TV |
| `.venv/bin/python test/sanity_test.py` | Speech in, speech out: Whisper transcribes, espeak-ng repeats it; barge-in on the TV. Say "stop test" to quit |

To watch the TV's CEC traffic: `cec-ctl -d /dev/cec0 -M` in a second terminal.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No .venv found` | Run `./setup.sh` first, or use `./voice-remote --keys` |
| `No input device matching 'wm8960'` | HAT not loaded: redo [step 1](#1-enable-the-wm8960-audio-hat), or pick a device from `--list-devices` |
| It never reacts to "remote …" | Watch the `[heard]` lines. Mic too quiet: raise capture in `alsamixer -c <card>` (F4), or lower `--threshold-factor`. Wrong words: try `--model base.en` |
| Commands trigger on TV sound | The wake word filters most of it; raise `--threshold-factor` |
| Whisper prints text you didn't say on silence | Known Whisper behaviour on noise; raise `--threshold-factor` |
| Audio stays on the HAT with the TV on | `bash test/hdmi_audio_check.sh`; check the `[audio] Output -> ...` reason; enable SIMPLINK, or try `--no-cec` |
| No `vc4hdmi` card in `/proc/asound/cards` | Remove `,noaudio` from `dtoverlay=vc4-kms-v3d` in `/boot/firmware/config.txt` and reboot |
| TV volume/navigation doesn't react | Check the log says `webOS TV ... paired and connected`. If not, turn on LG Connect Apps, put the TV on the Pi's network, or pass `--tv-ip`. Over CEC alone the LG TV ignores these (BUG-002) |
| Pairing fails / `refused` | Turn the TV on first and accept the prompt within 60 s. Delete `~/.config/voice_remote/lgtv.json` to pair again |
| "remote power on" doesn't work | Needs HDMI-CEC (SIMPLINK on); webOS can't wake a TV that is off |
| `cec-ctl` permission denied | `sudo usermod -aG video $USER`, then log in again |
| `aplay: ... Device or resource busy` | Another sound server (e.g. PipeWire on the desktop image) holds the device; use the Lite image or stop it |

## Project layout

| Path | What |
|------|------|
| `voice-remote` | Launcher (uses `.venv` for voice, system Python for `--keys`) |
| `voice_remote/` | The app: `app.py` (voice remote), `keys.py` (keyboard remote), `commands.py` (speech to command), `tv.py` (TV control), `speech.py` (mic, Whisper, TTS), `startup_checks.py`, `audio_output.py`, `tv_link.py` (HDMI/CEC), `webos_link.py` (LG webOS) |
| `test/` | Hardware test tools |
| `setup.sh`, `requirements*.txt` | Installation |

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): system design and data flow
- [DEVELOPER_NOTES.md](DEVELOPER_NOTES.md): running notes, reminders and bug-fix summaries
- [SKILLS.md](SKILLS.md): skills and roles used on this project
- [RELEASE.md](RELEASE.md): release notes per tagged version
- [BUGS.md](BUGS.md): known bugs, with the release they were found in and their status
