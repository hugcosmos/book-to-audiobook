from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from utils.log import log


def check_ffmpeg() -> bool:
    if not shutil.which("ffmpeg"):
        log.error("ffmpeg not found on PATH")
        return False
    return True


def check_ffprobe() -> bool:
    if not shutil.which("ffprobe"):
        log.error("ffprobe not found on PATH")
        return False
    return True


def check_ebook_convert() -> bool:
    return shutil.which("ebook-convert") is not None


def get_audio_duration(file_path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def validate_audio(
    file_path: str | Path,
    min_bytes: int = 1024,
    min_duration: float = 0.5,
) -> bool:
    """Validate that an audio file is non-empty and decodable.

    Checks, in order:
      1. File exists and is at least ``min_bytes`` bytes (catches 0-byte / tiny
         error-response files).
      2. ffprobe can decode the container and reports a positive duration.
      3. ffprobe reports at least one audio stream (catches HTML/JSON error pages
         saved with an audio extension).

    Returns True only when all checks pass. Any subprocess/parse failure returns
    False rather than raising — callers decide whether to retry or fail loudly.
    """
    path = Path(file_path)
    try:
        if not path.exists() or path.stat().st_size < min_bytes:
            return False
    except OSError:
        return False

    # Probe streams + format in one call.
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=codec_type:format=duration",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if result.returncode != 0:
        return False

    import json as _json
    try:
        data = _json.loads(result.stdout or "{}")
    except ValueError:
        return False

    streams = data.get("streams") or []
    if not any(s.get("codec_type") == "audio" for s in streams):
        return False

    fmt = data.get("format") or {}
    duration = fmt.get("duration")
    try:
        return float(duration) >= min_duration
    except (TypeError, ValueError):
        return False
