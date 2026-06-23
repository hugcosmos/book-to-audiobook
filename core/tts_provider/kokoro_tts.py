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
    """Download a file via httpx streaming with progress feedback.

    Uses httpx (already a project dependency) for HTTP/2, connection reuse, and
    faster downloads than urllib.  Falls back to urllib if httpx is unavailable.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        import httpx
        _download_httpx(url, dest)
    except ImportError:
        _download_urllib(url, dest)
    log.info("Downloaded %s (%.1f MB)", Path(url).name, dest.stat().st_size / 1e6)


def _download_httpx(url: str, dest: Path) -> None:
    """Stream a file with httpx for better throughput."""
    import httpx

    name = Path(url).name
    with httpx.Client(http2=True, follow_redirects=True, timeout=600) as client:
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0))
            log.info("Downloading %s (%.1f MB)", name, total / 1e6)

            tmp = dest.with_suffix(dest.suffix + ".part")
            downloaded = 0
            with open(tmp, "wb") as f:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0 and downloaded % (5 * 1024 * 1024) < len(chunk):
                        pct = downloaded * 100 // total
                        log.info("  ... %d%%", pct)
            tmp.rename(dest)


def _download_urllib(url: str, dest: Path) -> None:
    """Fallback: urllib download (no httpx available)."""
    import urllib.request

    log.info("Downloading %s → %s", Path(url).name, dest)

    def _report(count, block_size, total_size):
        if total_size > 0 and count % 50 == 0:
            pct = min(100, count * block_size * 100 // total_size)
            log.info("  ... %d%%", pct)

    urllib.request.urlretrieve(url, str(dest), _report)


def _ensure_model(model_dir: str | None = None) -> tuple[Path, Path]:
    """Return (model_path, voices_path); download missing files in parallel.

    Precedence: settings.kokoro.model_dir > ~/.cache/book2audio/kokoro.
    """
    from concurrent.futures import ThreadPoolExecutor

    cache_dir = Path(model_dir).expanduser() if model_dir else _DEFAULT_CACHE_DIR
    model_path = cache_dir / "kokoro-v1.1-zh.onnx"
    voices_path = cache_dir / "voices-v1.1-zh.bin"

    # Collect files that need downloading
    jobs: list[tuple[str, Path]] = []
    if not model_path.exists():
        jobs.append((_MODEL_URL, model_path))
    if not voices_path.exists():
        jobs.append((_VOICES_URL, voices_path))

    if jobs:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_download_file, url, path) for url, path in jobs]
            for f in futures:
                f.result()  # raise on first error

    return model_path, voices_path


def _install_kokoro_onnx() -> None:
    """Auto-install kokoro-onnx with --no-deps.

    kokoro-onnx declares ``onnxruntime>=1.20.1`` on PyPI, but onnxruntime's
    macOS x86_64 wheels stop at 1.19.2.  In practice 1.19.2 works fine, so we
    bypass the resolver with --no-deps to avoid a spurious conflict.
    """
    import subprocess, sys
    log.info("Installing kokoro-onnx (auto) ...")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "--no-deps", "kokoro-onnx"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _get_engine(model_dir_override: str | None = None):
    """Lazy-singleton: build kokoro-onnx Kokoro engine once."""
    global _kokoro_engine
    if _kokoro_engine is not None:
        return _kokoro_engine

    try:
        from kokoro_onnx import Kokoro
    except ImportError:
        _install_kokoro_onnx()
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
        except ImportError:
            _install_kokoro_onnx()
            from kokoro_onnx import Kokoro  # noqa: F401

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
