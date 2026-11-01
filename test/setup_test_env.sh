#!/usr/bin/env bash
# Installs everything test/sanity_test.py needs on Raspberry Pi OS:
# system audio/TTS packages, then a Python virtual environment at <repo>/.venv.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
VENV="$REPO_ROOT/.venv"

echo "== Installing system packages =="
sudo apt-get update
sudo apt-get install -y \
    python3-venv python3-dev \
    libportaudio2 portaudio19-dev \
    alsa-utils \
    espeak-ng \
    v4l-utils

echo "== Creating Python virtual environment at $VENV =="
python3 -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

echo
echo "Done. Next steps:"
echo "  bash test/mic_check.sh                 # record and play back with arecord/aplay"
echo "  source .venv/bin/activate"
echo "  python test/sanity_test.py             # speak, and the Pi says it back"
