"""Pinned Piper CLI fallback. Downloads happen only during explicit setup."""
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


MODEL_REVISION = "c10ece1aade47bb51c153c893d14e5bf8e5b7117"
MODEL_NAME = "en_US-ljspeech-medium.onnx"
MODEL_BASE = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/"
    f"{MODEL_REVISION}/en/en_US/ljspeech/medium"
)
# Model weights, voice configuration, and public-domain dataset notice.
MODEL_FILES = {
    MODEL_NAME: "6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22",
    MODEL_NAME + ".json": "141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860",
    "MODEL_CARD": "fbee1529c89d36b3fe76d7e9f3f832dce17f44900a52d76a9bda735654766b4d",
}


def _sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def ensure_model(*, download: bool = False) -> Path:
    root = Path(os.getenv("PIPER_MODEL_DIR", str(Path(__file__).resolve().parents[1] / ".tts-models")))
    for name, expected in MODEL_FILES.items():
        destination = root / name
        if destination.is_file() and _sha256(destination) == expected:
            continue
        if not download:
            raise RuntimeError("Piper model missing or invalid; run python -m video.offline_tts --download")
        root.mkdir(parents=True, exist_ok=True)
        for attempt in range(3):
            temporary = None
            try:
                started = time.monotonic()
                with tempfile.NamedTemporaryFile(dir=root, delete=False) as output:
                    temporary = Path(output.name)
                    with urlopen(f"{MODEL_BASE}/{name}", timeout=30) as response:
                        total = 0
                        while chunk := response.read(1024 * 1024):
                            total += len(chunk)
                            if total > 128 * 1024 * 1024 or time.monotonic() - started > 180:
                                raise RuntimeError("Model download exceeded size/time limit")
                            output.write(chunk)
                if _sha256(temporary) != expected:
                    raise RuntimeError("Model checksum mismatch")
                temporary.replace(destination)
                break
            except Exception:
                if attempt == 2:
                    raise RuntimeError(f"Could not provision verified Piper asset: {name}") from None
                time.sleep(2 ** (attempt + 1))
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    return root / MODEL_NAME


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
    """Use the separate Piper executable, then encode its real WAV as MP3."""
    if not text.strip():
        raise ValueError("Cannot synthesize empty narration")
    model = ensure_model()
    with tempfile.TemporaryDirectory(prefix="piper_", dir=Path(audio_path).parent) as directory:
        wav_path = str(Path(directory) / "speech.wav")
        try:
            subprocess.run(
                [sys.executable, "-m", "piper", "--model", str(model), "--output-file", wav_path],
                input=" ".join(text.splitlines()), encoding="utf-8",
                capture_output=True, check=True, timeout=300,
            )
            validate_audio(wav_path)
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-i", wav_path,
                 "-codec:a", "libmp3lame", "-b:a", "128k", str(audio_path)],
                capture_output=True, check=True, timeout=60,
            )
            validate_audio(audio_path)
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("Piper synthesis/encoding failed; no usable narration was produced") from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", required=True)
    parser.parse_args()
    print(f"Verified Piper model: {ensure_model(download=True).name}")
