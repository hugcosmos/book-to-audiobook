"""Kokoro TTS via kokoro-onnx (ONNX Runtime, CPU).

Kokoro-82M is an 82M-parameter open-source TTS model. This provider uses the
v1.1-zh multilingual variant (Chinese + English) loaded through the kokoro-onnx
Python package. Chinese text is converted to phonemes via misaki; English goes
through kokoro-onnx's built-in espeak/phonemizer pipeline.

Model files (~380 MB) are auto-downloaded from GitHub releases on first use.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from config.settings import settings
from core.models import TTSConfig
from core.tts_provider.base_tts import BaseTTSProvider
from utils.log import log

_MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.1/kokoro-v1.1-zh.onnx"
)
_VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.1/voices-v1.1-zh.bin"
)

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "book2audio" / "kokoro"

# Global engine singleton (one model for all conversions).
_kokoro_engine = None
_engine_lock = asyncio.Lock()


def _download_file(url: str, dest: Path) -> None:
    """Download a file with a simple progress log."""
    import urllib.request

    log.info("Downloading %s → %s", Path(url).name, dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    def _report(count, block_size, total_size):
        if total_size > 0 and count % 50 == 0:
            pct = min(100, count * block_size * 100 // total_size)
            log.info("  ... %d%%", pct)

    urllib.request.urlretrieve(url, str(dest), _report)
    log.info("Downloaded %s (%.1f MB)", Path(url).name, dest.stat().st_size / 1e6)


def _ensure_model(model_dir: str | None = None) -> tuple[Path, Path]:
    """Return (model_path, voices_path); download if missing.

    Precedence: settings.kokoro.model_dir > ~/.cache/book2audio/kokoro.
    """
    cache_dir = Path(model_dir).expanduser() if model_dir else _DEFAULT_CACHE_DIR
    model_path = cache_dir / "kokoro-v1.1-zh.onnx"
    voices_path = cache_dir / "voices-v1.1-zh.bin"

    if not model_path.exists():
        _download_file(_MODEL_URL, model_path)
    if not voices_path.exists():
        _download_file(_VOICES_URL, voices_path)
    return model_path, voices_path


def _get_engine(model_dir_override: str | None = None):
    """Lazy-singleton: build kokoro-onnx Kokoro engine once."""
    global _kokoro_engine
    if _kokoro_engine is not None:
        return _kokoro_engine

    from kokoro_onnx import Kokoro

    model_path, voices_path = _ensure_model(model_dir_override)
    start = time.time()
    _kokoro_engine = Kokoro(str(model_path), str(voices_path))
    voices = _kokoro_engine.get_voices()
    zh_count = sum(1 for v in voices if v.startswith("z"))
    log.info("Kokoro engine loaded (%d voices, %d Chinese) in %.1fs",
             len(voices), zh_count, time.time() - start)
    return _kokoro_engine


def _phonemize_zh(text: str) -> str:
    """Convert Chinese text to phonemes via misaki."""
    from misaki import zh as misaki_zh
    g2p = misaki_zh.ZHG2P()
    phonemes, _ = g2p(text)
    return phonemes


class KokoroTTSProvider(BaseTTSProvider):
    provider_name = "kokoro"
    supported_languages = [
        "zh-CN", "zh-TW", "zh-HK",
        "en-US", "en-GB",
    ]

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        self._speed = config.speed
        self._model_dir_override = config.model_path

    @classmethod
    def validate_config(cls, config: TTSConfig) -> None:
        try:
            from kokoro_onnx import Kokoro  # noqa: F401
        except ImportError as e:
            raise ValueError(
                "Kokoro TTS requires 'kokoro-onnx'. "
                "Install with: pip install kokoro-onnx"
            ) from e

    @classmethod
    def warmup(cls) -> None:
        _get_engine()

    async def synthesize(self, text: str, output_path: Path,
                         progress=None, cancelled=None) -> Path:
        if not text or not text.strip():
            raise ValueError("No text to synthesize")

        engine = _get_engine(self._model_dir_override)
        is_zh = self.config.language.startswith("zh")

        # Chunk text — Kokoro has a 510-token limit per inference call.
        # For Chinese we phonemize first, then split by phoneme count.
        # For English we pass text directly and use kokoro-onnx's phonemizer.
        from core.text_processor import TextProcessor
        chunk_max = settings.kokoro.chunk_max_chars
        text_chunks = TextProcessor.chunk(text, max_chars=chunk_max,
                                          language=self.config.language)

        if not text_chunks:
            raise ValueError("No text to synthesize")

        log.info("Kokoro TTS: %d chunks (max %d chars)", len(text_chunks), chunk_max)

        async with _engine_lock:
            wav_path = output_path.with_suffix(".wav")
            audio_parts: list[np.ndarray] = []
            sample_rate: int | None = None

            for i, chunk in enumerate(text_chunks):
                if cancelled and cancelled():
                    raise asyncio.CancelledError("Conversion cancelled")

                if is_zh:
                    phonemes = await asyncio.to_thread(_phonemize_zh, chunk)
                    # Kokoro model: split very long phoneme sequences
                    audio, rate = await asyncio.to_thread(
                        engine.create, phonemes, voice=self.config.voice,
                        speed=1.0, is_phonemes=True
                    )
                else:
                    audio, rate = await asyncio.to_thread(
                        engine.create, chunk, voice=self.config.voice,
                        speed=1.0, lang="en-us"
                    )
                sample_rate = rate
                if audio.size == 0:
                    raise RuntimeError(f"Kokoro returned empty audio for chunk {i + 1}")
                audio_parts.append(audio)
                if progress:
                    progress(i + 1, len(text_chunks))

        if progress:
            progress(len(text_chunks), len(text_chunks))

        combined = np.concatenate(audio_parts)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            sf.write(str(wav_path), combined, sample_rate)
            # Speed adjustment via FFmpeg atempo
            from core.tts_provider.audio_utils import wav_to_mp3
            wav_to_mp3(wav_path, output_path, self._speed)
        finally:
            wav_path.unlink(missing_ok=True)
        return output_path

    def estimate_duration(self, char_count: int) -> float:
        return char_count / (settings.tts.chars_per_second * self._speed)
