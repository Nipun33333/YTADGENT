"""Mix the same quiet, local instrumental under every narration using FFmpeg."""
import math
import os
import shutil
import subprocess


BACKGROUND_TRACK = "channel-bed.mp3"
SUPPORTED_EXTENSIONS = (".mp3", ".wav", ".ogg", ".m4a", ".flac")


def _get_library_tracks(library_dir: str) -> list[str]:
    """Prefer the bundled channel theme; never shuffle or rotate music."""
    if not library_dir or not os.path.isdir(library_dir):
        return []
    theme = os.path.join(library_dir, BACKGROUND_TRACK)
    if os.path.isfile(theme):
        return [theme]
    tracks = sorted(
        os.path.join(library_dir, name) for name in os.listdir(library_dir)
        if os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS
        and os.path.isfile(os.path.join(library_dir, name))
    )
    return tracks[:1]


def mix_music_with_narration(narration_path: str,
                             output_path: str,
                             music_volume: float = 0.15,
                             library_dir: str = "") -> str:
    """Loop one track quietly, fade its ends, and preserve narration duration/level.

    music_volume is a linear gain (0.15 is 15% of the source music amplitude).
    If music is missing or mixing fails, keep the narration usable.
    """
    if os.path.abspath(narration_path) == os.path.abspath(output_path):
        raise ValueError("Music output must not overwrite the source narration")
    volume = float(music_volume)
    if not math.isfinite(volume) or not 0 <= volume <= 1:
        raise ValueError("music_volume must be between 0 and 1")
    tracks = _get_library_tracks(library_dir)
    if not tracks or volume == 0:
        shutil.copy2(narration_path, output_path)
        return output_path

    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", narration_path],
            capture_output=True, text=True, check=True, timeout=30,
        )
        duration = float(probe.stdout.strip())
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError("Narration has no usable duration")
        fade_in = min(1.0, duration / 4)
        fade_out = min(1.5, duration / 4)
        filters = (
            f"[1:a]volume={volume},afade=t=in:st=0:d={fade_in},"
            f"afade=t=out:st={duration-fade_out}:d={fade_out}[music];"
            "[0:a][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            "alimiter=limit=0.98:level=false:latency=true[mixed]"
        )
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", narration_path,
             "-stream_loop", "-1", "-i", tracks[0], "-filter_complex", filters,
             "-map", "[mixed]", "-t", str(duration), "-ar", "44100", "-ac", "2",
             "-codec:a", "libmp3lame", "-b:a", "192k", output_path],
            capture_output=True, check=True, timeout=300,
        )
        if os.path.getsize(output_path) == 0:
            raise RuntimeError("Music mix is empty")
        print(f"   → Background: {os.path.basename(tracks[0])} at {volume:.0%}, {duration:.1f}s")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"   ⚠ Music mix unavailable ({type(exc).__name__}); keeping narration")
        shutil.copy2(narration_path, output_path)
    return output_path
