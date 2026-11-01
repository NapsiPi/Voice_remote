"""Speech building blocks: microphone capture, voice activity detection, Whisper
speech-to-text, and espeak-ng text-to-speech with barge-in.

Used by the voice remote (app.py), the startup checks and test/sanity_test.py. Speech
output plays on the TV when it is connected and on, otherwise on the HAT speaker
(see audio_output.py).
"""

import collections
import importlib.util
import io
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from .audio_output import AudioRouter

WHISPER_RATE = 16000
HDMI_RATE = 48000
BLOCK_MS = 30
START_BLOCKS = 3   # consecutive loud blocks (~90 ms) that count as speech starting
BARGE_BLOCKS = 5   # consecutive loud blocks (~150 ms) that interrupt playback
PREROLL_S = 0.3    # audio kept from before speech starts, so the first syllable isn't clipped
MIN_STT_S = 1.5    # whisper.cpp ignores input under 1 s; pad short answers like "yes" (BUG-003)
WHISPER_CPP_DIR = Path(__file__).resolve().parent.parent / "third_party" / "whisper.cpp"
DEFAULT_MODELS = {"local": "base.en", "whispercpp": "tiny.en"}


def rms(block):
    return float(np.sqrt(np.mean(block * block)))


def resample(audio, src_rate, dst_rate):
    if src_rate == dst_rate:
        return audio
    if src_rate > dst_rate:
        # Box filter to reduce aliasing before decimating.
        k = max(1, int(src_rate // dst_rate))
        audio = np.convolve(audio, np.ones(k) / k, mode="same")
    n = int(round(len(audio) * dst_rate / src_rate))
    x_old = np.arange(len(audio)) / src_rate
    x_new = np.arange(n) / dst_rate
    return np.interp(x_new, x_old, audio).astype(np.float32)


def to_wav_bytes(audio, rate):
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


def read_wav_mono(path):
    """16-bit WAV file -> (mono float32 samples, sample rate)."""
    with wave.open(str(path), "rb") as wf:
        rate, channels = wf.getframerate(), wf.getnchannels()
        data = wf.readframes(wf.getnframes())
    audio = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    return audio, rate


def write_hdmi_wav(src, dst):
    """HDMI audio on the Pi only takes 2-channel audio at the TV's rates (BUG-001):
    convert mono espeak-ng/loopback WAVs to stereo 48 kHz."""
    audio, rate = read_wav_mono(src)
    pcm = (np.clip(resample(audio, rate, HDMI_RATE), -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(dst), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(HDMI_RATE)
        wf.writeframes(np.repeat(pcm, 2).tobytes())  # same sample to left and right


def normalise(text):
    return "".join(c for c in text.lower() if c.isalnum() or c == " ").strip()


class LocalWhisper:
    """Runs Whisper on the Pi with faster-whisper (offline after the model download)."""

    def __init__(self, model_size, language):
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            sys.exit("faster-whisper is not installed. It needs 64-bit Raspberry Pi OS; "
                     "on 32-bit use --backend whispercpp (see README, Build 101).")

        print(f"Loading Whisper model '{model_size}' (the first run downloads it)...")
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.language = language

    def transcribe(self, audio):
        segments, _ = self.model.transcribe(audio, language=self.language, beam_size=1)
        return " ".join(seg.text.strip() for seg in segments).strip()


def whisper_cpp_binary(root):
    """The whisper.cpp CLI built by setup.sh (named 'main' in older releases)."""
    for name in ("whisper-cli", "main"):
        path = Path(root) / "build" / "bin" / name
        if path.exists():
            return path
    return None


class WhisperCpp:
    """Runs the whisper.cpp command-line tool: free, offline, and builds on 32-bit ARM."""

    def __init__(self, root, model, language):
        self.binary = whisper_cpp_binary(root)
        if self.binary is None:
            sys.exit(f"whisper.cpp is not built in {root}. Run ./setup.sh.")
        self.model = Path(model) if model.endswith(".bin") else Path(root) / "models" / f"ggml-{model}.bin"
        if not self.model.exists():
            sys.exit(f"Model {self.model} is missing. Download it with:\n"
                     f"  bash {root}/models/download-ggml-model.sh {model}")
        self.language = language or "auto"
        self.threads = str(os.cpu_count() or 4)
        self.wav = Path(tempfile.gettempdir()) / "voice_remote_stt.wav"
        print(f"whisper.cpp: {self.binary}, model {self.model.name}")

    def transcribe(self, audio):
        short = int(MIN_STT_S * WHISPER_RATE) - len(audio)
        if short > 0:
            audio = np.pad(audio, (0, short))
        self.wav.write_bytes(to_wav_bytes(audio, WHISPER_RATE))
        out = subprocess.run(
            [str(self.binary), "-m", str(self.model), "-f", str(self.wav),
             "-l", self.language, "-t", self.threads, "-nt", "-np"],
            capture_output=True, text=True,
        )
        if out.returncode != 0:
            print(f"[whisper.cpp] failed: {out.stderr.strip()[-300:]}", file=sys.stderr)
            return ""
        # Drop non-speech tags such as [BLANK_AUDIO] or (music).
        text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", " ".join(out.stdout.split()))
        return " ".join(text.split())


class OpenAIWhisper:
    """Sends audio to the OpenAI Whisper API (paid, needs OPENAI_API_KEY)."""

    def __init__(self, language):
        try:
            from openai import OpenAI
        except ImportError:
            sys.exit("The openai package is not installed. Run ./setup.sh --with-openai.")

        self.client = OpenAI()
        self.language = language

    def transcribe(self, audio):
        kwargs = {"language": self.language} if self.language else {}
        result = self.client.audio.transcriptions.create(
            model="whisper-1",
            file=("speech.wav", to_wav_bytes(audio, WHISPER_RATE)),
            **kwargs,
        )
        return result.text.strip()


class Mic:
    """Continuous capture from the input device as mono float32 blocks."""

    def __init__(self, device, rate):
        info = sd.query_devices(device, "input")
        self.rate = rate or int(info["default_samplerate"])
        channels = min(2, info["max_input_channels"])
        print(f"Microphone: {info['name']} @ {self.rate} Hz, {channels} ch")
        self.blocks = queue.Queue()
        self.stream = sd.InputStream(
            device=device,
            samplerate=self.rate,
            channels=channels,
            dtype="float32",
            blocksize=int(self.rate * BLOCK_MS / 1000),
            callback=self._callback,
        )

    def _callback(self, indata, frames, time_info, status):
        if status:
            print(f"[audio] {status}", file=sys.stderr)
        # The HAT has two mics; average them to mono.
        self.blocks.put(indata.mean(axis=1).copy())

    def read(self, timeout=2.0):
        try:
            return self.blocks.get(timeout=timeout)
        except queue.Empty:
            sys.exit("No audio from the microphone. Run test/mic_check.sh to check the HAT.")

    def flush(self):
        while True:
            try:
                self.blocks.get_nowait()
            except queue.Empty:
                return


class Speaker:
    """espeak-ng renders speech to a WAV file and aplay plays it in the background,
    on whichever output the router picks (TV or HAT speaker)."""

    def __init__(self, router, voice, speed):
        for tool in ("espeak-ng", "aplay"):
            if not shutil.which(tool):
                sys.exit(f"'{tool}' not found. Run ./setup.sh first.")
        self.router = router
        self.voice = voice
        self.speed = speed
        self.wav = Path(tempfile.gettempdir()) / "voice_remote_tts.wav"
        self.hdmi_wav = Path(tempfile.gettempdir()) / "voice_remote_hdmi.wav"
        self.proc = None

    def start(self, text):
        subprocess.run(
            ["espeak-ng", "-v", self.voice, "-s", str(self.speed), "-w", str(self.wav), text],
            check=True,
        )
        self.play(self.wav)

    def play(self, wav):
        output = self.router.current()
        if not output.device.startswith("hdmi:"):
            self.proc = self._aplay(output.device, wav)
            return

        write_hdmi_wav(wav, self.hdmi_wav)
        self.proc = self._aplay(output.device, self.hdmi_wav)
        # HDMI audio can still fail with the TV on; fall back to the HAT if aplay dies.
        time.sleep(0.3)
        code = self.proc.poll()
        if code not in (None, 0):
            error = self.proc.stderr.read().strip() or f"aplay exit code {code}"
            print(f"[audio] TV HDMI audio failed on {output.device}: {error}")
            self.router.tv_failed(error)
            self.proc = self._aplay(self.router.current().device, wav)

    @staticmethod
    def _aplay(device, wav, capture_errors=True):
        cmd = ["aplay", "-q"]
        if device:
            cmd += ["-D", device]
        cmd.append(str(wav))
        return subprocess.Popen(cmd, stderr=subprocess.PIPE if capture_errors else None, text=True)

    def _report_error(self):
        if self.proc.returncode and self.proc.stderr:
            error = self.proc.stderr.read().strip()
            if error:
                print(f"[audio] aplay: {error}", file=sys.stderr)

    def playing(self):
        if self.proc is None:
            return False
        if self.proc.poll() is None:
            return True
        self._report_error()
        return False

    def wait(self):
        if self.proc is not None:
            self.proc.wait()
            self._report_error()

    def stop(self):
        """Stop playback on purpose (barge-in, Ctrl+C). aplay killed mid-write reports
        'Interrupted system call'; that's expected here, so its stderr is dropped."""
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait()
        self.proc = None


def find_input_device(hint):
    if hint is None:
        return None
    if hint.isdigit():
        return int(hint)
    for idx, dev in enumerate(sd.query_devices()):
        if hint.lower() in dev["name"].lower() and dev["max_input_channels"] > 0:
            return idx
    sys.exit(f"No input device matching '{hint}'. Use --list-devices to see what is available.")


def calibrate(mic, seconds):
    print(f"Measuring background noise for {seconds:.1f}s, please stay quiet...")
    levels = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        levels.append(rms(mic.read()))
    return float(np.median(levels))


def record_utterance(mic, threshold, args, preroll, wait_s=None):
    """Wait for speech, then record until the speaker goes quiet.

    preroll holds blocks already known to be speech (from a barge-in); when given,
    recording starts straight away. Returns None if nobody speaks within wait_s.
    """
    frames = list(preroll)
    if not frames:
        history = collections.deque(maxlen=int(PREROLL_S * 1000 / BLOCK_MS))
        loud_run = 0
        deadline = None if wait_s is None else time.monotonic() + wait_s
        while loud_run < START_BLOCKS:
            if deadline is not None and time.monotonic() > deadline:
                return None
            block = mic.read()
            history.append(block)
            loud_run = loud_run + 1 if rms(block) > threshold else 0
        frames = list(history)

    max_blocks = int(args.max_seconds * 1000 / BLOCK_MS)
    end_blocks = int(args.silence_ms / BLOCK_MS)
    silent = 0
    while len(frames) < max_blocks and silent < end_blocks:
        block = mic.read()
        frames.append(block)
        silent = silent + 1 if rms(block) <= threshold else 0
    return np.concatenate(frames)


def barge_in_enabled(args, speaker):
    if args.barge_in == "auto":
        # There's no echo cancellation: the HAT speaker sits next to the mics, so our own
        # voice would trigger barge-in and kill playback mid-write (BUG-004). The TV is far
        # enough away.
        return speaker.router.current().name == "tv"
    return args.barge_in == "on"


def speak_with_barge_in(mic, speaker, text, threshold, args):
    """Speak text. Returns the interrupting speech blocks on barge-in, else None."""
    mic.flush()
    speaker.start(text)
    enabled = barge_in_enabled(args, speaker)
    started = time.monotonic()
    history = collections.deque(maxlen=int(PREROLL_S * 1000 / BLOCK_MS))
    loud_run = 0
    while speaker.playing():
        try:
            block = mic.blocks.get(timeout=0.1)
        except queue.Empty:
            continue
        # Ignore the first moments of playback, when our own voice hits the mics hardest.
        if not enabled or time.monotonic() - started < args.barge_in_delay:
            continue
        history.append(block)
        loud_run = loud_run + 1 if rms(block) > threshold * args.barge_in_factor else 0
        if loud_run >= BARGE_BLOCKS:
            speaker.stop()
            print("[barge-in] Stopped talking, listening to you...")
            return list(history)
    mic.flush()  # drop the tail of our own voice
    return None


def add_common_args(p):
    """Audio, Whisper and barge-in options shared by the voice remote, the startup checks and the sanity test."""
    p.add_argument("--list-devices", action="store_true", help="list audio devices and exit")
    p.add_argument("--backend", choices=["auto", "local", "whispercpp", "openai"], default="auto",
                   help="speech recognition: local = faster-whisper (64-bit OS), whispercpp = whisper.cpp "
                        "(works on 32-bit), openai = paid OpenAI API. auto (default) uses local if "
                        "installed, else whispercpp")
    p.add_argument("--model", default=None,
                   help="Whisper model: tiny.en, base.en, small.en, ... or a ggml .bin path for whispercpp "
                        "(default: base.en for local, tiny.en for whispercpp)")
    p.add_argument("--whisper-cpp-dir", default=str(WHISPER_CPP_DIR),
                   help=f"whisper.cpp checkout built by setup.sh (default: {WHISPER_CPP_DIR})")
    p.add_argument("--language", default="en", help="spoken language code (default: en)")
    p.add_argument("--input-device", default="wm8960",
                   help="input device index or part of its name (default: wm8960)")
    p.add_argument("--output-device", default=None,
                   help="fixed ALSA device for speech, e.g. plughw:CARD=wm8960soundcard,DEV=0 "
                        "(default: automatic, TV when connected and on, else the HAT speaker)")
    p.add_argument("--tv-ip", default=None,
                   help="LG TV IP address for webOS control (default: last used, else auto-discover)")
    p.add_argument("--no-cec", dest="cec", action="store_false",
                   help="don't ask the TV for its power state over HDMI-CEC; a connected TV counts as on")
    p.add_argument("--rate", type=int, default=None, help="capture sample rate (default: device default)")
    p.add_argument("--voice", default="en", help="espeak-ng voice (default: en)")
    p.add_argument("--speed", type=int, default=165, help="espeak-ng words per minute (default: 165)")
    p.add_argument("--calibrate", type=float, default=1.5, help="seconds of noise calibration (default: 1.5)")
    p.add_argument("--threshold-factor", type=float, default=3.0,
                   help="speech threshold as a multiple of the noise floor (default: 3.0)")
    p.add_argument("--min-threshold", type=float, default=0.01, help="lowest speech threshold, RMS (default: 0.01)")
    p.add_argument("--silence-ms", type=int, default=800, help="silence that ends an utterance (default: 800)")
    p.add_argument("--max-seconds", type=float, default=15.0, help="longest utterance (default: 15)")
    p.add_argument("--barge-in", choices=["auto", "on", "off"], default="auto",
                   help="interrupt replies by talking: auto (default) = only when audio plays on the TV, "
                        "not on the HAT speaker next to the mics")
    p.add_argument("--barge-in-factor", type=float, default=2.0,
                   help="barge-in needs speech this many times louder than the speech threshold (default: 2.0)")
    p.add_argument("--barge-in-delay", type=float, default=0.4,
                   help="seconds after a reply starts before barge-in is allowed (default: 0.4)")


def build_transcriber(args):
    backend = args.backend
    if backend == "auto":
        if importlib.util.find_spec("faster_whisper"):
            backend = "local"
        elif whisper_cpp_binary(args.whisper_cpp_dir):
            backend = "whispercpp"
        else:
            sys.exit("No speech recognition is installed. Run ./setup.sh.")
    print(f"Speech recognition: {backend}")
    if backend == "openai":
        return OpenAIWhisper(args.language)
    model = args.model or DEFAULT_MODELS[backend]
    if backend == "whispercpp":
        return WhisperCpp(args.whisper_cpp_dir, model, args.language)
    return LocalWhisper(model, args.language)


def build_audio(args):
    """Transcriber, speaker and mic from the common options."""
    device = find_input_device(args.input_device)
    transcriber = build_transcriber(args)
    speaker = Speaker(AudioRouter(args.output_device, args.cec), args.voice, args.speed)
    return transcriber, speaker, Mic(device, args.rate)


def speech_threshold(mic, args):
    """Measure the background noise and return the speech-start threshold (RMS)."""
    noise = calibrate(mic, args.calibrate)
    threshold = max(noise * args.threshold_factor, args.min_threshold)
    print(f"Noise floor {noise:.4f} RMS, speech threshold {threshold:.4f} RMS")
    return threshold


def transcribe(transcriber, mic, audio):
    """Transcribe captured mic audio, printing how long it took."""
    t0 = time.monotonic()
    text = transcriber.transcribe(resample(audio, mic.rate, WHISPER_RATE))
    print(f"[heard] {text!r}  ({len(audio) / mic.rate:.1f}s audio, {time.monotonic() - t0:.1f}s to transcribe)")
    return text
