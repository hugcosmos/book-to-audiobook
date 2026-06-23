"""Shared audio utilities used by TTS providers."""
from __future__ import annotations

import subprocess
from pathlib import Path

from config.settings import settings
from utils.log import log


def wav_to_mp3(wav_path: Path, mp3_path: Path, speed: float = 1.0) -> None:
    """Convert WAV to MP3 via FFmpeg with loudnorm + atempo speed."""
    filters = []
    # Loudness normalization: targets -16 LUFS, smooths volume fluctuations
    filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if speed != 1.0:
        # atempo range is [0.5, 2.0]; chain for values outside range
        remaining = speed
        while remaining > 2.0:
            filters.append("atempo=2.0")
            remaining /= 2.0
        while remaining < 0.5:
            filters.append("atempo=0.5")
            remaining /= 0.5
        filters.append(f"atempo={remaining:.4f}")

    cmd = [
        settings.ffmpeg_path,
        "-y",
        "-i", str(wav_path),
        "-filter:a", ",".join(filters),
        "-codec:a", "libmp3lame",
        "-q:a", "2",
        str(mp3_path),
    ]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        log.error("ffmpeg wav→mp3 failed: %s\nstderr: %s", " ".join(cmd), result.stderr.decode(errors="replace"))
        result.check_returncode()
