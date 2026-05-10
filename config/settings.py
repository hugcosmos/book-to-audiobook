from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings


class TTSSettings(BaseModel):
    """TTS provider selection and common params."""

    provider: str = "qwen3_mlx"  # qwen3_mlx | edge | baidu | iflytek | elevenlabs
    default_voice: str = "vivian"
    default_language: str = "zh-CN"
    max_retries: int = 5
    chars_per_second: float = 4.0
    chunk_max_chars: int = 3000  # fallback default, providers override


class EdgeTTSSettings(BaseModel):
    """Edge TTS specific."""

    chunk_max_chars: int = 3000
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"


class BaiduTTSSettings(BaseModel):
    """Baidu TTS specific."""

    app_id: str = ""
    api_key: str = ""
    secret_key: str = ""
    chunk_max_chars: int = 500


class IflytekTTSSettings(BaseModel):
    """iFlytek TTS specific."""

    app_id: str = ""
    api_key: str = ""
    api_secret: str = ""
    chunk_max_chars: int = 500


class ElevenLabsSettings(BaseModel):
    """ElevenLabs TTS specific."""

    api_key: str = ""
    model_id: str = "eleven_multilingual_v2"
    chunk_max_chars: int = 2500


class Qwen3MLXSettings(BaseModel):
    """Qwen3 TTS via MLX — Apple Silicon optimized."""

    model_name: str = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
    chunk_max_seconds: int = 90  # Target max audio duration per chunk; chars derived from language
    speed: float = 1.0  # speech speed via FFmpeg atempo (1.0=normal, 1.5=50% faster, 2.0=2x)


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8000
    upload_dir: Path = Path("uploads")
    output_dir: Path = Path("output")
    max_upload_size_mb: int = 500
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    ebook_convert_path: str = "ebook-convert"

    tts: TTSSettings = TTSSettings()
    edge_tts: EdgeTTSSettings = EdgeTTSSettings()
    baidu_tts: BaiduTTSSettings = BaiduTTSSettings()
    iflytek_tts: IflytekTTSSettings = IflytekTTSSettings()
    elevenlabs: ElevenLabsSettings = ElevenLabsSettings()
    qwen3_mlx: Qwen3MLXSettings = Qwen3MLXSettings()

    model_config = {"env_prefix": "B2A_"}


settings = Settings()
