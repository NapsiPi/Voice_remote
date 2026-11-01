#!/usr/bin/env bash
# HDMI audio diagnostics (BUG-001): is the TV seen on HDMI, is there an HDMI audio
# card for it, and does a 2-channel 48 kHz test sound play on the TV?
#
# Usage: bash test/hdmi_audio_check.sh [hdmi-port 0|1]
set -uo pipefail

PORT="${1:-}"

echo "== HDMI connectors (kernel DRM status) =="
for status in /sys/class/drm/card*-HDMI-A-*/status; do
    [[ -e "$status" ]] && echo "  $(basename "$(dirname "$status")"): $(cat "$status")"
done

echo
echo "== ALSA sound cards =="
cat /proc/asound/cards

echo
echo "== Display/audio lines in /boot/firmware/config.txt =="
grep -nE 'vc4|audio|hdmi' /boot/firmware/config.txt || echo "  (none)"

if [[ -z "$PORT" ]]; then
    for status in /sys/class/drm/card*-HDMI-A-*/status; do
        if [[ "$(cat "$status" 2>/dev/null)" == "connected" ]]; then
            n="${status##*HDMI-A-}"
            PORT=$(( ${n%%/*} - 1 ))
            break
        fi
    done
fi
if [[ -z "$PORT" ]]; then
    echo
    echo "FAIL: no TV connected on either HDMI port." >&2
    exit 1
fi

CARD="$(awk -v want="vc4hdmi$PORT" '{ id = $2; gsub(/[\[\]:]/, "", id); if (id == want) { print id; exit } }' /proc/asound/cards)"
if [[ -z "$CARD" ]]; then
    echo
    echo "FAIL: TV on HDMI $PORT but no HDMI audio card 'vc4hdmi$PORT'." >&2
    echo "Check /boot/firmware/config.txt: 'dtoverlay=vc4-kms-v3d' must not end in ',noaudio'." >&2
    exit 1
fi

DEVICE="hdmi:CARD=$CARD,DEV=0"
echo
echo "== Playing a 2-channel 48 kHz voice test on $DEVICE =="
echo "(You should hear \"Front Left\" and \"Front Right\" from the TV.)"
if speaker-test -D "$DEVICE" -c 2 -r 48000 -t wav -l 1; then
    echo
    echo "PASS if you heard it on the TV. If not, set the TV's sound output to its own speakers."
else
    echo
    echo "FAIL: speaker-test could not play on $DEVICE (see the error above)." >&2
    exit 1
fi
