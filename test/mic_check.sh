#!/usr/bin/env bash
# Low-level WM8960 HAT check with plain ALSA tools (no Python needed):
# confirms the card is detected, records a few seconds and plays it back.
#
# Usage: bash test/mic_check.sh [seconds] [card-number]
set -euo pipefail

DURATION="${1:-5}"
CARD="${2:-}"
OUT="$(mktemp --suffix=.wav)"
trap 'rm -f "$OUT"' EXIT

echo "== Capture devices =="
arecord -l

if [[ -z "$CARD" ]]; then
    CARD="$(arecord -l | grep -i wm8960 | head -n1 | sed -E 's/^card ([0-9]+):.*/\1/' || true)"
fi
if [[ -z "$CARD" ]]; then
    echo "FAIL: WM8960 sound card not detected." >&2
    echo "Check the overlay in /boot/firmware/config.txt (see README, Build 101) and reboot." >&2
    exit 1
fi
echo "Using WM8960 on card $CARD"

echo
echo "== Recording ${DURATION}s, speak now =="
arecord -D "plughw:${CARD},0" -f S16_LE -r 16000 -c 2 -d "$DURATION" "$OUT"

echo
echo "== Playing back through the HAT's output =="
aplay -D "plughw:${CARD},0" "$OUT"

echo
echo "If you heard your voice, the HAT's mic and output both work."
echo "Too quiet? Raise the capture level with: alsamixer -c $CARD  (F4 = capture controls)"
