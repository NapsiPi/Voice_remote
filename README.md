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
| TV | LG UJ635V (webOS) | Target device: micro-HDMI for picture, sound and power (CEC); Wi-Fi for remote control (webOS) |
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
| `git`, `cmake`, `build-essential`, `curl` | Building whisper.cpp and downloading its models (32-bit, or `--whisper-cpp`) |
| `python3-numpy`, `python3-cffi` | 32-bit only: prebuilt instead of compiled by pip |

`--light` installs only `alsa-utils` and `v4l-utils`.

### pip packages
Installed into `.venv` by `test/setup_test_env.sh`:

| Package | File | Why |
|---------|------|-----|
| `numpy` | `test/requirements.txt` | Audio buffers (from apt `python3-numpy` on 32-bit) |
| `sounddevice` | `test/requirements.txt` | Microphone capture |
| `faster-whisper` | `test/requirements-local-whisper.txt` | Whisper on the Pi, **64-bit only** |
| `openai` | `test/requirements-openai.txt` | Paid OpenAI Whisper API; installed only with `--with-openai` |

### Speech recognition backends

| Backend | `--backend` | OS | Cost | Notes |
|---------|-------------|----|------|-------|
| faster-whisper | `local` | 64-bit | Free, offline | Default model `base.en` |
| whisper.cpp | `whispercpp` | 32- and 64-bit | Free, offline | Built from source into `third_party/whisper.cpp`; default model `tiny.en`, `base.en` also downloaded |
| OpenAI API | `openai` | any | Paid per minute | Needs `--with-openai` and `OPENAI_API_KEY` |

The default `--backend auto` picks `local` if it's installed, otherwise `whispercpp`.
Compare accuracy and speed on the Pi with `--model tiny.en` and `--model base.en`.
Each transcription prints how long it took.

### 32-bit vs 64-bit Raspberry Pi OS

**Use Raspberry Pi OS (64-bit), Bookworm or later.** Check which one you have:

```bash
dpkg --print-architecture    # arm64 = 64-bit, armhf = 32-bit
```

Don't rely on `uname -m`: a Pi 5 reports `aarch64` even on the 32-bit OS, because
its kernel is 64-bit (kernel names ending in `-rpi-v8`). To confirm the userland:

```bash
getconf LONG_BIT              # 32 = 32-bit userland
file -L /usr/bin/python3      # "ELF 32-bit ... ARM" = 32-bit Python
```

A 64-bit kernel doesn't help Python packages: they follow the userland. Only
re-flashing with Raspberry Pi OS (64-bit) enables faster-whisper. whisper.cpp
doesn't depend on the kernel version. On armhf, `setup_test_env.sh` builds it under
`setarch linux32`, so the build sees `armv7l` and picks 32-bit CPU flags.

| | 64-bit (`arm64`) | 32-bit (`armhf`) |
|---|---|---|
| numpy | pip wheel | apt `python3-numpy`, so pip never compiles it |
| Local Whisper (`faster-whisper`) | Yes (default) | **Not available**: `ctranslate2`/`onnxruntime` have no 32-bit ARM builds |
| Speech recognition | faster-whisper, offline | **whisper.cpp**, offline and free (built from source, a few minutes on a Pi 5) |

`setup_test_env.sh` detects the architecture and installs the right set. It also
needs Python 3.10 or newer, which Bookworm provides. On 32-bit it finishes with a
whisper.cpp smoke test on the bundled `samples/jfk.wav` and prints the time taken.

On 32-bit the script links `libatomic`. Without it, linking fails with
`undefined reference to '__atomic_fetch_add_8'`. It builds only `whisper-cli`, not the
other examples (`whisper-bench`, server, ...).

If whisper.cpp still fails to build on 32-bit, try a release tag instead of `master`:
`WHISPER_CPP_REF=<tag> bash test/setup_test_env.sh` (tags are listed at
https://github.com/ggml-org/whisper.cpp/tags).

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

The script prints the detected architecture, installs the packages, then
import-checks them. If it ends with `Done.`, the install worked.

### 3. Check the HAT with plain ALSA (no Python)

```bash
bash test/mic_check.sh          # records 5 s, then plays it back
bash test/mic_check.sh 10 2     # 10 s, force sound card 2
```

Pass: you hear your own voice from the HAT's speaker or headphone jack.
Too quiet: run `alsamixer -c <card>`, press F4 and raise the capture levels.

### Light test: keyboard remote, no voice

The fastest way to check the hardware. It needs only Python 3's standard library,
`alsa-utils` and `v4l-utils`: no venv, no Whisper.

```bash
bash test/setup_test_env.sh --light     # apt packages only, takes about a minute
python3 test/light_remote.py            # on the Pi's keyboard or over SSH
```

At startup it checks:
- **WM8960 HAT:** the card is detected (`PASS`/`FAIL`).
- **TV:** connected on HDMI and answering HDMI-CEC (`PASS`/`WARN`/`FAIL`).
- **webOS:** the LG TV is found on the network and paired (`PASS`/`FAIL`/`INFO`).

**How the TV is controlled:** the LG TV ignores CEC remote keys (BUG-002), so:
- **Power** goes over HDMI-CEC.
- **All other keys** go over **webOS on the local network**. Without webOS, they fall
  back to CEC.

**One-time LG TV setup for webOS control:**
1. Put the TV on the same Wi-Fi/LAN as the Pi.
2. On the TV, turn on **Settings → Network → LG Connect Apps**.
3. Turn the TV on and run the light remote. The TV shows a pairing prompt; accept it
   with the TV remote within 60 s.

The pairing key and the TV's address are saved in `~/.config/voice_remote/lgtv.json`.
Delete that file to pair again. The TV is found automatically; if it isn't, pass
`--tv-ip <address>` (shown in the TV's network settings).

Each key press then goes to the TV:

| Key | TV command | Key | TV command |
|-----|-----------|-----|-----------|
| Arrows | Up / Down / Left / Right | Enter | OK |
| `b`, Backspace | Back | `h` | Home |
| `+` / `-` | Volume up / down | `m` | Mute |
| `]` / `[` | Channel up / down | `0`–`9` | Numbers |
| `>` | Play | Space | Pause |
| `p` | Power on / standby | `t` | Mic loopback: record 3 s, play on the HAT |
| `?` | Help | `q` | Quit |

Pass: the HAT, TV and webOS checks pass, and the TV reacts to the keys. Each key
prints how it was sent (`sent via webOS`, or the CEC result). `--no-webos` sends
keys over CEC only, and `--webos-debug` prints every webOS message.

To debug CEC itself:

```bash
python3 test/light_remote.py --cec-debug    # prints every cec-ctl command and its output
cec-ctl -d /dev/cec0 -M                     # in a second terminal: shows the TV's replies
```

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
| `--backend whispercpp` | Force whisper.cpp (automatic on 32-bit) |
| `--model tiny.en` / `base.en` | Smaller is faster, larger is more accurate |
| `--backend openai` | Paid OpenAI Whisper API; needs `--with-openai` setup and `OPENAI_API_KEY` |
| `--threshold-factor 4` | Less sensitive to background noise |
| `--barge-in auto\|on\|off` | Talking interrupts replies. `auto` (default) enables it only when audio plays on the TV, because the HAT speaker is too close to the mics |
| `--barge-in-factor 3` | Barge-in needs louder speech |

The first local run downloads the Whisper model, so it needs internet once.

### 5. Startup checks (run before the voice remote)

```bash
source .venv/bin/activate
python test/startup_checks.py                       # checks only
python test/startup_checks.py --then "<command>"    # then start the voice remote
```

The Pi talks you through four checks. **Answer each question by saying "yes" or
"no" after it finishes speaking.** The log shows `[listening] say yes or no` when
it's ready. It waits 8 s and asks up to three times. It speaks on the TV when the TV is
on, otherwise on the HAT speaker.

**What you will hear:**

> "Welcome to the voice remote. Before it starts, we will run four quick checks: the
> microphone, the TV connection, speech recognition, and TV control. Answer each
> question by saying yes or no."

| # | Check | What happens | Passes when |
|---|-------|--------------|-------------|
| 1 | Microphone loopback | "When I say go, talk for a few seconds." It records 4 s and plays it back. | Sound was captured and you say **yes** to "Did you hear yourself clearly?" |
| 2 | TV connection | Looks for the TV on HDMI and asks it over CEC whether it's on. If it's in standby, asks you to turn it on. | Audio switches to the TV and you say **yes** to "Can you hear it from the TV?" |
| 3 | Speech recognition | "Please say a short sentence." Whisper transcribes it. | You say **yes** to "I heard: …. Is that right?" |
| 4 | TV control | Sends volume up ×2 then down ×2 over webOS (network), or over HDMI-CEC without webOS. Skipped if neither reaches the TV. | You say **yes** to "Did the TV volume go up and then back down?" |

At the end it prints a PASS/FAIL/SKIP table. If everything passed it says "We are
launching the voice remote." If something failed, it names the failed checks and
asks whether to launch anyway.

`--loopback-seconds` changes the recording length. All the sanity-test options
(`--model`, `--output-device`, `--no-cec`, ...) work here too.

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No input device matching 'wm8960'` | Card not loaded: redo step 1, or pick a device from `--list-devices` |
| It never starts listening | Mic too quiet: raise capture in `alsamixer`, or lower `--threshold-factor` |
| The reply interrupts itself, `aplay: ... Interrupted system call` | Barge-in stopped playback because the mics heard the HAT speaker. `--barge-in auto` (default) now keeps barge-in off on the HAT speaker; with `--barge-in on`, raise `--barge-in-factor` |
| Whisper prints text you didn't say on silence | Known Whisper behaviour on noise; raise `--threshold-factor` |
| Audio stays on the HAT with the TV on | Run `bash test/hdmi_audio_check.sh` (TV seen? HDMI audio card present? test sound plays?). Check `[audio] Output -> ...` in the log for the reason; enable SIMPLINK on the TV, or try `--no-cec` |
| No `vc4hdmi` card in `/proc/asound/cards` | Remove `,noaudio` from `dtoverlay=vc4-kms-v3d` in `/boot/firmware/config.txt` and reboot |
| Check 4 fails: TV volume doesn't change | Check the log says `webOS TV ... paired and connected`. If not, turn on LG Connect Apps, put the TV on the Pi's network, or pass `--tv-ip`. Over CEC alone, the LG TV ignores volume keys (BUG-002) |
| `webOS TV at ...: ... refused` / pairing fails | Turn the TV on first, then accept the prompt within 60 s. If it was paired before, delete `~/.config/voice_remote/lgtv.json` and pair again |
| `cec-ctl` permission denied | Add your user to the `video` group: `sudo usermod -aG video $USER`, then log in again |
| `aplay: ... Device or resource busy` | Another sound server (e.g. PipeWire on the desktop image) holds the device; run from the Lite image or stop it |

## Usage

_TBD: the voice remote itself is not written yet._

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): system design and data flow
- [DEVELOPER_NOTES.md](DEVELOPER_NOTES.md): running notes and reminders for developers
- [SKILLS.md](SKILLS.md): skills and roles used on this project
- [RELEASE.md](RELEASE.md): release notes per tagged version
- [BUGS.md](BUGS.md): known bugs, with the release they were found in and their status
