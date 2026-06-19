from __future__ import annotations

import platform
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings


def _default_provider_for_platform() -> str:
    """Pick the default local TTS provider based on the host platform.

    Apple Silicon (arm64 macOS) can run Qwen3 MLX (GPU-accelerated, highest
    quality), so that stays the default there. On every other platform — Intel
    Macs, Windows, Linux without a GPU — Qwen3 MLX is unavailable (its wheel is
    arm64-only), so fall back to CosyVoice (ONNX/CPU), which runs anywhere.
    Users can still override via B2A_TTS__PROVIDER or the settings UI.
    """
    is_apple_silicon = (
        platform.system() == "Darwin" and platform.machine() == "arm64"
    )
    return "qwen3_mlx" if is_apple_silicon else "cosyvoice"


class TTSSettings(BaseModel):
    """TTS provider selection and common params."""

    # Apple Silicon → qwen3_mlx; everywhere else (Intel Mac/Win/Linux) → cosyvoice.
    # Override via B2A_TTS__PROVIDER or the settings UI.
    provider: str = _default_provider_for_platform()
    default_voice: str = "vivian"
    default_language: str = "zh-CN"
    max_retries: int = 5
    chars_per_second: float = 4.0
    chunk_max_chars: int = 3000  # fallback default, providers override
    # Max number of chapters to synthesize concurrently. Local GPU providers
    # (qwen3_mlx, supertonic) ignore this and run serially; cloud providers
    # (edge, elevenlabs, baidu, iflytek) are I/O-bound and benefit from >1.
    concurrency: int = 1


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

    model_name: str = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-8bit"
    model_path: str | None = None  # Local model path (if set, overrides model_name)
    chunk_max_seconds: int = 90  # Target max audio duration per chunk; chars derived from language
    speed: float = 1.0  # speech speed via FFmpeg atempo (1.0=normal, 1.5=50% faster, 2.0=2x)


class SupertonicSettings(BaseModel):
    """Supertonic TTS — local ONNX-based, 31 languages."""

    total_steps: int = 5       # quality: 2-15
    speed: float = 1.0         # speech speed multiplier
    chunk_max_chars: int = 300 # matches supertonic's default


class CosyVoiceSettings(BaseModel):
    """CosyVoice TTS via sherpa-onnx — local ONNX/CPU runtime.

    Aimed at low-spec / GPU-less machines (e.g. Intel MacBook Air). CosyVoice2
    is exported to a quantized ONNX model and run on CPU through sherpa-onnx.
    """

    model_dir: str | None = None       # None → auto-download to ~/.cache/book2audio/cosyvoice2
    num_threads: int = 2               # CPU threads for inference (leave cores for the system)
    chunk_max_chars: int = 120         # per-chunk char cap; short on CPU to bound latency
    speed: float = 1.0                 # speech speed multiplier
    # Where to fetch the ONNX model on first use. "auto" tries ModelScope first
    # (CosyVoice is Alibaba's; ModelScope is its home registry and fastest in
    # mainland China), falling back to HuggingFace if ModelScope is unavailable.
    download_source: str = "auto"      # auto | modelscope | huggingface
    modelscope_repo: str = "pengzhendong/cosyvoice2-0.5B-int8"
    huggingface_repo: str = "k2-fsa/sherpa-onnx-cosyvoice2-0.5B-int8"


class AudioSettings(BaseModel):
    """Audio assembly options."""

    # Apply EBU R128 loudness normalization when re-encoding (M4B build). Keeps
    # volume consistent across chapters/providers. Only affects paths that
    # already re-encode (concat fallback, AAC for M4B); -c copy is untouched.
    normalize_loudness: bool = True


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
    supertonic: SupertonicSettings = SupertonicSettings()
    cosyvoice: CosyVoiceSettings = CosyVoiceSettings()
    audio: AudioSettings = AudioSettings()

    model_config = {"env_prefix": "B2A_"}


settings = Settings()
