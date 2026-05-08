from __future__ import annotations

import shutil
import subprocess

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
