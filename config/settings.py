from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    upload_dir: Path = Path("uploads")
    output_dir: Path = Path("output")
    max_upload_size_mb: int = 500
    default_voice: str = "zh-CN-XiaoxiaoNeural"
    default_language: str = "zh-CN"
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    ebook_convert_path: str = "ebook-convert"
    tts_chunk_max_chars: int = 3000
    tts_max_retries: int = 5
    chars_per_second: float = 13.0  # rough estimate for TTS duration

    model_config = {"env_prefix": "B2A_"}


settings = Settings()
