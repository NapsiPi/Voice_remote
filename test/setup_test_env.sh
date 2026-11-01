#!/usr/bin/env bash
# Installs everything the scripts in test/ need on Raspberry Pi OS:
# system audio/TTS/CEC packages, then a Python virtual environment at <repo>/.venv.
#
# 64-bit OS (arm64): everything from pip, including local Whisper (faster-whisper).
# 32-bit OS (armhf): numpy comes from apt, and local Whisper is skipped because its
#                    dependencies have no 32-bit ARM builds; use --backend openai.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
VENV="$REPO_ROOT/.venv"

# uname -m says aarch64 on a Pi 5 even with the 32-bit OS (64-bit kernel), so ask dpkg.
ARCH="$(dpkg --print-architecture)"
echo "== OS architecture: $ARCH =="
case "$ARCH" in
    arm64) ;;
    armhf)
        echo "WARNING: 32-bit Raspberry Pi OS detected."
        echo "  - numpy is installed from apt (python3-numpy), not pip."
        echo "  - Local Whisper (faster-whisper) is NOT available on 32-bit;"
        echo "    run the tests with --backend openai and set OPENAI_API_KEY."
        echo "  For local speech recognition, reinstall with Raspberry Pi OS (64-bit)."
        ;;
    *)
        echo "Unsupported architecture '$ARCH'; this script targets Raspberry Pi OS." >&2
        exit 1
        ;;
esac

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "Python 3.10 or newer is needed (found $(python3 --version)). Use Raspberry Pi OS Bookworm or later." >&2
    exit 1
fi

echo "== Installing system packages =="
APT_PACKAGES=(python3-venv python3-dev libportaudio2 portaudio19-dev alsa-utils espeak-ng v4l-utils)
# 32-bit: take the compiled dependencies from apt so pip never builds them from source.
[[ "$ARCH" == "armhf" ]] && APT_PACKAGES+=(python3-numpy python3-cffi)
sudo apt-get update
sudo apt-get install -y "${APT_PACKAGES[@]}"

echo "== Creating Python virtual environment at $VENV =="
if [[ "$ARCH" == "armhf" ]]; then
    # Let the venv see apt's python3-numpy instead of building numpy with pip.
    python3 -m venv --system-site-packages "$VENV"
    grep -v '^numpy' "$SCRIPT_DIR/requirements.txt" > "$VENV/requirements-armhf.txt"
    REQUIREMENTS=(-r "$VENV/requirements-armhf.txt")
else
    python3 -m venv "$VENV"
    REQUIREMENTS=(-r "$SCRIPT_DIR/requirements.txt" -r "$SCRIPT_DIR/requirements-local-whisper.txt")
fi
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install "${REQUIREMENTS[@]}"

echo "== Checking the Python packages import =="
"$VENV/bin/python" -c 'import numpy, sounddevice; print("numpy", numpy.__version__, "| sounddevice", sounddevice.__version__)'
if [[ "$ARCH" == "arm64" ]]; then
    "$VENV/bin/python" -c 'import faster_whisper; print("faster-whisper", faster_whisper.__version__)'
fi

echo
echo "Done. Next steps:"
echo "  bash test/mic_check.sh                 # record and play back with arecord/aplay"
echo "  source .venv/bin/activate"
if [[ "$ARCH" == "armhf" ]]; then
    echo "  export OPENAI_API_KEY=...             # 32-bit: speech recognition goes through the OpenAI API"
    echo "  python test/startup_checks.py --backend openai"
else
    echo "  python test/startup_checks.py          # spoken startup checks"
fi
