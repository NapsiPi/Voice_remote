#!/usr/bin/env bash
# Installs everything the scripts in test/ need on Raspberry Pi OS.
#
# Usage: bash test/setup_test_env.sh [--light] [--whisper-cpp] [--with-openai]
#   (no options)   full voice test setup for this OS:
#                    64-bit (arm64): pip packages + local Whisper (faster-whisper)
#                    32-bit (armhf): numpy/cffi from apt + whisper.cpp built from source
#   --light        only what test/light_remote.py needs (no Python packages, no Whisper)
#   --whisper-cpp  also build whisper.cpp on 64-bit
#   --with-openai  also install the paid OpenAI Whisper API client
#
# Environment: WHISPER_CPP_REF   whisper.cpp branch/tag to build (default: master)
#              WHISPER_CPP_MODELS models to download (default: "tiny.en base.en")
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
VENV="$REPO_ROOT/.venv"
WHISPER_CPP_DIR="$REPO_ROOT/third_party/whisper.cpp"
WHISPER_CPP_REF="${WHISPER_CPP_REF:-master}"
WHISPER_CPP_MODELS="${WHISPER_CPP_MODELS:-tiny.en base.en}"

LIGHT=0; WITH_WHISPER_CPP=0; WITH_OPENAI=0
for arg in "$@"; do
    case "$arg" in
        --light) LIGHT=1 ;;
        --whisper-cpp) WITH_WHISPER_CPP=1 ;;
        --with-openai) WITH_OPENAI=1 ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
done

# uname -m says aarch64 on a Pi 5 even with the 32-bit OS (64-bit kernel), so ask dpkg.
ARCH="$(dpkg --print-architecture)"
echo "== OS architecture: $ARCH =="
case "$ARCH" in
    arm64) ;;
    armhf)
        echo "32-bit Raspberry Pi OS: numpy comes from apt, and speech recognition uses"
        echo "whisper.cpp (faster-whisper has no 32-bit ARM builds)."
        WITH_WHISPER_CPP=1
        ;;
    *) echo "Unsupported architecture '$ARCH'; this script targets Raspberry Pi OS." >&2; exit 1 ;;
esac

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    echo "Python 3.10 or newer is needed (found $(python3 --version)). Use Raspberry Pi OS Bookworm or later." >&2
    exit 1
fi

echo "== Installing system packages =="
APT_PACKAGES=(alsa-utils v4l-utils)
if [[ $LIGHT -eq 0 ]]; then
    APT_PACKAGES+=(python3-venv python3-dev libportaudio2 portaudio19-dev espeak-ng)
    # 32-bit: take the compiled dependencies from apt so pip never builds them from source.
    [[ "$ARCH" == "armhf" ]] && APT_PACKAGES+=(python3-numpy python3-cffi)
    [[ $WITH_WHISPER_CPP -eq 1 ]] && APT_PACKAGES+=(git cmake build-essential curl)
fi
sudo apt-get update
sudo apt-get install -y "${APT_PACKAGES[@]}"

if [[ $LIGHT -eq 1 ]]; then
    echo
    echo "Done (light). Next step:"
    echo "  python3 test/light_remote.py"
    exit 0
fi

echo "== Creating Python virtual environment at $VENV =="
REQUIREMENTS=()
if [[ "$ARCH" == "armhf" ]]; then
    # Let the venv see apt's python3-numpy instead of building numpy with pip.
    python3 -m venv --system-site-packages "$VENV"
    grep -v '^numpy' "$SCRIPT_DIR/requirements.txt" > "$VENV/requirements-armhf.txt"
    REQUIREMENTS+=(-r "$VENV/requirements-armhf.txt")
else
    python3 -m venv "$VENV"
    REQUIREMENTS+=(-r "$SCRIPT_DIR/requirements.txt" -r "$SCRIPT_DIR/requirements-local-whisper.txt")
fi
[[ $WITH_OPENAI -eq 1 ]] && REQUIREMENTS+=(-r "$SCRIPT_DIR/requirements-openai.txt")
"$VENV/bin/pip" install --upgrade pip
"$VENV/bin/pip" install "${REQUIREMENTS[@]}"

echo "== Checking the Python packages import =="
"$VENV/bin/python" -c 'import numpy, sounddevice; print("numpy", numpy.__version__, "| sounddevice", sounddevice.__version__)'
if [[ "$ARCH" == "arm64" ]]; then
    "$VENV/bin/python" -c 'import faster_whisper; print("faster-whisper", faster_whisper.__version__)'
fi

if [[ $WITH_WHISPER_CPP -eq 1 ]]; then
    echo "== Building whisper.cpp ($WHISPER_CPP_REF) in $WHISPER_CPP_DIR =="
    if [[ -d "$WHISPER_CPP_DIR/.git" ]]; then
        git -C "$WHISPER_CPP_DIR" fetch --depth 1 origin "$WHISPER_CPP_REF"
        git -C "$WHISPER_CPP_DIR" checkout -q FETCH_HEAD
    else
        git clone --depth 1 --branch "$WHISPER_CPP_REF" https://github.com/ggml-org/whisper.cpp.git "$WHISPER_CPP_DIR"
    fi
    echo "whisper.cpp commit: $(git -C "$WHISPER_CPP_DIR" rev-parse --short HEAD)"
    # On 32-bit userland with a 64-bit kernel, uname -m says aarch64 and the build would
    # pick 64-bit CPU flags for a 32-bit compiler. setarch makes it report armv7l instead.
    BUILD_PREFIX=()
    CMAKE_ARGS=(-DCMAKE_BUILD_TYPE=Release)
    if [[ "$ARCH" == "armhf" ]]; then
        BUILD_PREFIX=(setarch linux32)
        # 64-bit atomics (__atomic_fetch_add_8) live in libatomic on 32-bit ARM. Passed as a
        # standard library so it lands at the end of the link line.
        CMAKE_ARGS+=(-DCMAKE_C_STANDARD_LIBRARIES=-latomic -DCMAKE_CXX_STANDARD_LIBRARIES=-latomic)
    fi
    "${BUILD_PREFIX[@]}" cmake -S "$WHISPER_CPP_DIR" -B "$WHISPER_CPP_DIR/build" "${CMAKE_ARGS[@]}"
    # Only the CLI the tests use ('main' in older releases), not every example (bench, server, ...).
    "${BUILD_PREFIX[@]}" cmake --build "$WHISPER_CPP_DIR/build" --config Release -j"$(nproc)" --target whisper-cli \
        || "${BUILD_PREFIX[@]}" cmake --build "$WHISPER_CPP_DIR/build" --config Release -j"$(nproc)" --target main

    for model in $WHISPER_CPP_MODELS; do
        if [[ ! -f "$WHISPER_CPP_DIR/models/ggml-$model.bin" ]]; then
            bash "$WHISPER_CPP_DIR/models/download-ggml-model.sh" "$model"
        fi
    done

    WHISPER_BIN="$WHISPER_CPP_DIR/build/bin/whisper-cli"
    [[ -x "$WHISPER_BIN" ]] || WHISPER_BIN="$WHISPER_CPP_DIR/build/bin/main"
    FIRST_MODEL="${WHISPER_CPP_MODELS%% *}"
    echo "== whisper.cpp smoke test (samples/jfk.wav, model $FIRST_MODEL) =="
    time "$WHISPER_BIN" -m "$WHISPER_CPP_DIR/models/ggml-$FIRST_MODEL.bin" \
        -f "$WHISPER_CPP_DIR/samples/jfk.wav" -nt -np
    echo "(Expected: \"And so my fellow Americans, ask not what your country can do for you...\")"
fi

echo
echo "Done. Next steps:"
echo "  bash test/mic_check.sh                 # record and play back with arecord/aplay"
echo "  source .venv/bin/activate"
echo "  python test/startup_checks.py          # spoken startup checks"
