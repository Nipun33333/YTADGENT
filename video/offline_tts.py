"""Kokoro male narration. Models and an isolated runtime are provisioned by --download."""
import argparse
from array import array
import hashlib
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


MODEL_NAME = "kokoro-v1.0.onnx"
VOICE_LABEL = "Kokoro Michael (US English male, conversational)"
MODEL_BASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
)
# Full-precision Kokoro v1.0 weights and voices (Apache-2.0), pinned by SHA-256.
# https://huggingface.co/hexgrad/Kokoro-82M
MODEL_FILES = {
    MODEL_NAME: "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
RUNTIME_VERSION = "0.6.1"


def _model_root() -> Path:
    # Keep the existing cache override so current deployments need no changes.
    return Path(os.getenv("PIPER_MODEL_DIR", str(Path(__file__).resolve().parents[1] / ".tts-models"))).resolve()


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def ensure_model(*, download: bool = False) -> Path:
    root = _model_root()
    for name, expected in MODEL_FILES.items():
        destination = root / name
        if destination.is_file() and _sha256(destination) == expected:
            continue
        if not download:
            raise RuntimeError("Kokoro model missing or invalid; run python -m video.offline_tts --download")
        root.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            temporary = None
            try:
                started = time.monotonic()
                with tempfile.NamedTemporaryFile(dir=root, delete=False) as output:
                    temporary = Path(output.name)
                    with urlopen(f"{MODEL_BASE}/{name}", timeout=60) as response:
                        total = 0
                        while chunk := response.read(1024 * 1024):
                            total += len(chunk)
                            if total > 384 * 1024 * 1024 or time.monotonic() - started > 300:
                                raise RuntimeError("Model download exceeded size/time limit")
                            output.write(chunk)
                if _sha256(temporary) != expected:
                    raise RuntimeError("Model checksum mismatch")
                temporary.replace(destination)
                break
            except Exception:
                if attempt == 2:
                    raise RuntimeError(f"Could not provision verified Kokoro asset: {name}") from None
                time.sleep(2 ** (attempt + 1))
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    return root / MODEL_NAME


def _ensure_runtime(*, download: bool = False) -> Path:
    """Isolate Kokoro's NumPy 2 requirement from MoviePy's NumPy 1 environment."""
    import venv

    runtime = _model_root() / f"kokoro-runtime-{RUNTIME_VERSION}"
    python = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    marker = runtime / "ready.txt"
    expected = f"{RUNTIME_VERSION}:{sys.version_info.major}.{sys.version_info.minor}"
    if python.is_file() and marker.is_file() and marker.read_text() == expected:
        return python
    if not download:
        raise RuntimeError("Kokoro runtime missing; run python -m video.offline_tts --download")
    marker.unlink(missing_ok=True)
    venv.EnvBuilder(with_pip=True).create(runtime)
    subprocess.run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check",
         f"kokoro-onnx=={RUNTIME_VERSION}"],
        check=True, timeout=600,
    )
    # Do not mark partial installs as ready.
    subprocess.run(
        [str(python), "-c", "from kokoro_onnx import Kokoro; import numpy, wave"],
        check=True, timeout=60,
    )
    marker.write_text(expected)
    return python


_SYNTHESIS_SCRIPT = r'''
import sys
import wave
import numpy as np
from kokoro_onnx import Kokoro

engine = Kokoro(sys.argv[1], sys.argv[2])
text = sys.stdin.read().replace("  ...  ", "\n\n")
samples, sample_rate = engine.create(
    text, voice="am_michael", speed=0.98, lang="en-us",
)
if samples.size == 0 or not np.isfinite(samples).all():
    raise RuntimeError("Kokoro returned invalid audio")
pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2")
with wave.open(sys.argv[3], "wb") as output:
    output.setnchannels(1)
    output.setsampwidth(2)
    output.setframerate(sample_rate)
    output.writeframes(pcm.tobytes())
'''


def validate_audio(path: str) -> dict:
    """Decode actual audio; reject empty, corrupt, or effectively silent output."""
    try:
        decoded = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
             "-ar", "16000", "-f", "s16le", "pipe:1"],
            capture_output=True, check=True, timeout=60,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("TTS audio could not be decoded by FFmpeg") from None
    samples = array("h")
    samples.frombytes(decoded)
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) < 3200:
        raise RuntimeError("TTS audio is empty or too short")
    rms = math.sqrt(sum(int(x) ** 2 for x in samples) / len(samples))
    if rms < 16:
        raise RuntimeError("TTS audio is silent or effectively silent")
    return {"duration_seconds": len(samples) / 16000, "rms": rms}


def synthesise(text: str, audio_path: str) -> None:
    """Generate a conversational male voice without pitch-shifting or time-stretching."""
    if not text.strip():
        raise ValueError("Cannot synthesize empty narration")
    model = ensure_model()
    python = _ensure_runtime()
    with tempfile.TemporaryDirectory(prefix="kokoro_", dir=Path(audio_path).parent) as directory:
        wav_path = str(Path(directory) / "speech.wav")
        try:
            subprocess.run(
                [str(python), "-c", _SYNTHESIS_SCRIPT, str(model),
                 str(model.parent / "voices-v1.0.bin"), wav_path],
                input=text, encoding="utf-8",
                env={**os.environ, "PYTHONUTF8": "1"},
                capture_output=True, check=True, timeout=300,
            )
            validate_audio(wav_path)
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", wav_path,
                 "-codec:a", "libmp3lame", "-b:a", "192k", str(audio_path)],
                capture_output=True, check=True, timeout=60,
            )
            validate_audio(audio_path)
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("Kokoro synthesis/encoding failed; no usable narration was produced") from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", required=True)
    parser.parse_args()
    print(f"Verified Kokoro model: {ensure_model(download=True).name}")
    _ensure_runtime(download=True)
    print(f"Ready: {VOICE_LABEL}")
