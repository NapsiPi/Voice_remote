# Bugs

| ID | Title | Found in | Severity | Status |
|----|-------|----------|----------|--------|
| BUG-001 | Speech never plays on the TV; HDMI audio reported as not available | v0.1.0 | High | Verified (owner, v0.1.1) |
| BUG-002 | CEC volume up/down has no effect on the LG TV (light remote) | v0.1.0 | Medium | Verified (owner, v0.1.1): keys via webOS |
| BUG-003 | Startup checks don't wait for the spoken yes/no answer, so the voice app never starts | v0.1.0 | High | Verified (owner, v0.1.1) |
| BUG-004 | Barge-in triggers incorrectly; aplay "Interrupted system call" breaks speaker audio | v0.1.0 | Medium | Verified (owner, v0.1.1) |
| BUG-005 | Spoken replies sound robotic | v0.1.0 | Low | Open |

Statuses: Open, then Fixed (awaiting Pi verification), then Verified. A bug is closed
only after it is verified on the Pi.

---

## BUG-001: Speech never plays on the TV; HDMI audio reported as not available
- **Found in:** v0.1.0, Pi 5, 32-bit Pi OS, LG TV over micro-HDMI
- **Symptom:** the owner reports that audio is not connected to the TV and the speakers
  (channels) are not available. Check 2 (TV connection) fails, and check 4 is skipped
  as a result.
- **Likely cause:** speech is played to `hdmi:CARD=vc4hdmiN,DEV=0` exactly as espeak-ng
  writes it: mono, 22.05 kHz. The Pi's HDMI audio (an IEC958 device) accepts only
  2-channel audio at the TV's rates, so `aplay` fails with "Channels count non
  available". The router then marks the TV's audio as failed and falls back to the
  HAT. A second possible cause is a missing HDMI audio card (e.g. `noaudio` on the
  `vc4-kms-v3d` overlay).
- **Fix plan:** convert audio to 2-channel 48 kHz before playing it on HDMI. Show the
  `aplay` error and the router's reason. Add an HDMI audio diagnostic script.
- **Fix (branch `bugfix/v0.1.0-bugs`):** `Speaker.play` converts every WAV to stereo
  48 kHz (`write_hdmi_wav`) before playing it on an `hdmi:` device. If `aplay` still
  fails, its error text is printed and kept in the router's reason
  (`[audio] Output -> hat: TV HDMI audio failed recently (<error>)`).
  `test/hdmi_audio_check.sh` shows the HDMI connector status, the sound cards and the
  `config.txt` display lines, then plays `speaker-test` (2 ch, 48 kHz) on the TV.
- **Verify on the Pi:** `bash test/hdmi_audio_check.sh` should say "Front Left/Right"
  on the TV. After that, check 2 of `startup_checks.py` should pass.

## BUG-002: CEC volume up/down has no effect on the LG TV (light remote)
- **Found in:** v0.1.0, `test/light_remote.py`
- **Symptom:** the `+`/`-` keys in the light remote do nothing. Power on/standby (`p`)
  over CEC works. Not seen in check 4 of the startup checks, because check 4 was
  skipped after check 2 failed.
- **Likely cause:** the TV either rejects or ignores "User Control" volume presses from a
  playback device. Many TVs forward CEC volume only to an audio system. Not confirmed
  yet: the light remote doesn't show the TV's reply.
- **Fix plan:** report the TV's answer to each key (acknowledged, not acknowledged) and
  add a raw CEC debug mode, so the cause can be confirmed on the Pi. If LG ignores CEC
  volume, control volume another way.
- **Diagnostics (branch `bugfix/v0.1.0-bugs`):** every key now prints `sent`, `not
  acknowledged` or `failed`, with its CEC code. `light_remote.py --cec-debug` prints
  each `cec-ctl` command and its full output. The startup screen shows how to watch
  the TV's replies: `cec-ctl -d /dev/cec0 -M`.
- **Next step:** run `python3 test/light_remote.py --cec-debug` with the monitor open in
  a second terminal, press `+` and `-`, and share both outputs:
  - `not acknowledged`: the message never reaches the TV.
  - `sent` plus `FEATURE_ABORT` in the monitor: the TV refuses CEC volume.
  - `sent` with no reply: the TV silently ignores it. LG TVs often take volume only
    from an audio system. The fallback would then be LG's network control API (webOS)
    over Wi-Fi/Ethernet.
- **Finding (Pi test, `cec-ctl -M`):** for every key (volume, arrows, ...) the only
  message from the TV is `DEVICE_VENDOR_ID (0x87)` broadcast, vendor `0x00E091` (LG).
  There's no `FEATURE_ABORT` and no other reply. Power on/standby works, so the CEC
  link is fine.
- **Cause (confirmed):** the LG TV takes the user-control messages but silently ignores
  them from a playback device. This is a limit of LG's SIMPLINK, not a Pi bug.
- **Planned fix:** keep CEC for power on/standby. Send volume, mute, channel and
  navigation through LG's webOS network control (local network, one-time pairing
  prompt on the TV). Needs: confirmation the TV runs webOS, and the TV on the same
  network as the Pi.
- **Optional experiment:** register with LG's vendor ID
  (`cec-ctl --playback --vendor-id 0x00e091`, if this cec-ctl supports it) and retry
  volume. Low odds.
- **Fix (branch `bugfix/v0.1.0-bugs`):** the owner chose HDMI + Wi-Fi. The TV is an LG
  webOS UJ635V (2017), on the same Wi-Fi as the Pi. New `test/webos_link.py`
  (standard library only) discovers, pairs with and controls the TV over webOS.
  `light_remote.py` sends power over CEC and every other key over webOS (CEC as the
  fallback). Startup check 4 changes volume over webOS.
- **Verify on the Pi:**
  1. Turn on LG Connect Apps on the TV.
  2. Run `python3 test/light_remote.py`, and accept the pairing prompt on the TV.
  3. Press `+`/`-`: the volume changes, and the log says `sent via webOS`.

## BUG-003: Startup checks don't wait for the spoken yes/no answer, so the voice app never starts
- **Found in:** v0.1.0, `test/startup_checks.py`
- **Symptom:** checks 1 to 3 fail with "user did not confirm" without waiting for the
  owner's answer (check 1 recorded fine, peak level 0.0385). Recording and speech
  recognition work. Because the closing "launch anyway?" question has the same
  problem, the voice remote never starts.
- **Likely cause:**
  1. The question plays on the HAT speaker next to its own mics (because of BUG-001),
     and barge-in fires on the Pi's own voice. The "answer" is then the Pi's own echo.
  2. whisper.cpp ignores audio shorter than 1 s, and a short "yes" can be under that.
- **Fix plan:** ask the question first, then listen (no barge-in during yes/no
  questions). Wait for the echo to die down. Pad short recordings for whisper.cpp.
  Log what was heard on every attempt.
- **Fix (branch `bugfix/v0.1.0-bugs`):** `ask_yes_no` speaks the whole question, waits
  0.4 s for the echo to fade, flushes the mic, then listens for up to 8 s. It logs
  `[listening] say yes or no (attempt n/3)`, and every `[heard]` result is printed.
  It retries up to three times. `WhisperCpp` pads recordings shorter than 1.5 s.
- **Verify on the Pi:** in `startup_checks.py`, each question waits for your answer, and
  saying "yes" passes the check.

## BUG-004: Barge-in triggers incorrectly; aplay "Interrupted system call" breaks speaker audio
- **Found in:** v0.1.0
- **Symptom:** barge-in doesn't behave correctly: playback stops without the user
  talking. The owner saw `aplay` "Interrupted system call" errors and broken speaker
  audio in the sanity test. Their first suspicion was that the PCM input and output
  buffers were clashing.
- **Cause:** not a buffer conflict (the WM8960 records and plays at the same time).
  There is no echo cancellation, so the HAT speaker's sound, a few cm from the mics,
  exceeded the barge-in threshold. Barge-in then fired on the Pi's own voice, and
  `Speaker.stop()` killed `aplay` mid-write. `aplay` reports that as "Interrupted
  system call", and the reply is cut off. This repeated on every reply.
- **Fix (branch `bugfix/v0.1.0-bugs`):** `--barge-in auto|on|off` replaces
  `--no-barge-in`. `auto` (default) enables barge-in only when audio plays on the TV.
  `Speaker.stop()` drops the expected `aplay` error after an intentional stop. Real
  `aplay` errors are still printed as `[audio] aplay: ...`.
- **Verify on the Pi:** `python test/sanity_test.py` with audio on the HAT: replies play
  to the end with no "Interrupted system call". With audio on the TV, talking over a
  reply stops it.

## BUG-005: Spoken replies sound robotic
- **Found in:** v0.1.0
- **Symptom:** the owner finds the Pi's voice (prompts, replies, startup checks) robotic.
- **Cause:** text-to-speech is `espeak-ng`, which is a formant synthesizer: fast and
  light, but it sounds artificial by design.
- **Planned fix:** replace or offer an alternative to espeak-ng in `Speaker`, using one of:
  - **Piper:** neural TTS that runs offline and sounds much more natural. Check that
    it runs on 32-bit Pi OS (armhf) and is fast enough on the Pi 5.
  - **Pico (`pico2wave`):** lighter and less robotic than espeak-ng, though less
    natural than Piper.
  Keep espeak-ng as the fallback when neither is installed.
