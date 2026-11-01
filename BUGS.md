# Bugs

| ID | Title | Found in | Severity | Status |
|----|-------|----------|----------|--------|
| BUG-001 | Speech never plays on the TV; HDMI audio reported as not available | v0.1.0 | High | Fixed (awaiting Pi verification) |
| BUG-002 | CEC volume up/down has no effect on the LG TV (light remote) | v0.1.0 | Medium | Open |
| BUG-003 | Startup checks don't wait for the spoken yes/no answer, so the voice app never starts | v0.1.0 | High | Open |
| BUG-004 | Barge-in triggers incorrectly | v0.1.0 | Medium | Open |

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

## BUG-004: Barge-in triggers incorrectly
- **Found in:** v0.1.0
- **Symptom:** barge-in doesn't behave correctly: playback stops without the user
  talking, or doesn't stop when they do.
- **Likely cause:** there is no echo cancellation, so with the HAT speaker a few cm
  from the mics, the Pi's own voice exceeds the barge-in threshold.
- **Fix plan:** barge-in defaults to `auto`: on when output is the TV, off on the HAT
  speaker. `--barge-in on|off` overrides it.
