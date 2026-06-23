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

# Primary download source (GitHub releases).
_GH_MODEL_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.1/kokoro-v1.1-zh.onnx"
)
_GH_VOICES_URL = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
    "model-files-v1.1/voices-v1.1-zh.bin"
)


def _model_urls():
    """Return (model_url, voices_url).

    Honors explicit per-file overrides via env vars first
    (KOKORO_MODEL_URL / KOKORO_VOICES_URL), so a user behind a slow link can
    point at any mirror without editing code. Defaults to GitHub releases.
    """
    import os
    return (
        os.environ.get("KOKORO_MODEL_URL", _GH_MODEL_URL),
        os.environ.get("KOKORO_VOICES_URL", _GH_VOICES_URL),
    )

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "book2audio" / "kokoro"

# Global engine singleton (one model for all conversions).
_kokoro_engine = None
_engine_lock = asyncio.Lock()


_DOWNLOAD_MAX_RETRIES = 6
# Max seconds a single connection may go without delivering any bytes before we
# abort it and retry. httpx's per-read timeout is unreliable on a stalled TCP
# connection (no FIN), so we enforce this with a watchdog thread instead.
_READ_STALL = 60.0


def _mb(n: float) -> str:
    return f"{n / 1e6:.1f}MB"


def _total_from_range(resp) -> int:
    """True file size from a 206/416 response.

    ``Content-Range: bytes <start>-<end>/<total>`` (206) or
    ``bytes */<total>`` (416) gives the real total; we fall back to
    Content-Length (+resume offset) when the header is absent.
    """
    cr = resp.headers.get("content-range", "")
    # matches ".../<total>"
    if "/" in cr and not cr.endswith("/*"):
        try:
            return int(cr.rsplit("/", 1)[1])
        except ValueError:
            pass
    cl = int(resp.headers.get("content-length", 0))
    if resp.status_code == 206 and cl:
        # Content-Length on 206 is the *remaining* bytes; add resume offset.
        try:
            start = int(cr.split("-", 1)[0].rsplit(" ", 1)[-1])
            return cl + start
        except (ValueError, IndexError):
            pass
    return cl


def _download_file(url: str, dest: Path) -> None:
    """Download *url* to *dest* with resume + retries + size check.

    GitHub release assets are ~330 MB and the connection from many regions is
    slow/unstable, so a single streaming GET almost never finishes. Three
    things make this robust:

      * **Resume**: the final blob (Azure CDN after the 302) advertises
        ``Accept-Ranges: bytes``, so we append to ``dest.part`` on each retry
        via ``Range: bytes=N-`` instead of restarting from zero.
      * **Retries with backoff**: each attempt is bounded by a read timeout,
        retried up to ``_DOWNLOAD_MAX_RETRIES`` times.
      * **Completeness check**: the part is renamed to *dest* only once it
        reaches the true size; a truncated part stays for the next run.
    """
    import httpx

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    name = Path(url).name
    log.info("Downloading %s → %s", name, dest)

    total = 0
    for attempt in range(1, _DOWNLOAD_MAX_RETRIES + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else None

        try:
            # We rely on the OS-level socket timeout (read= below) to bound a
            # stalled connection. httpx translates its read timeout into a
            # socket recv timeout, which fires even when the peer stops sending
            # without a FIN — unlike an in-Python sleep, a blocked recv() is
            # interruptible by the kernel timer. The actual download loop runs
            # inline so there is no abandoned worker to corrupt the part file.
            client = httpx.Client(
                follow_redirects=True,
                timeout=httpx.Timeout(connect=30, read=_READ_STALL,
                                      write=30, pool=30),
            )
            with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code == 416:
                    # Part already covers the whole file (or overshoots).
                    total = _total_from_range(resp) or total
                else:
                    resp.raise_for_status()
                    total = _total_from_range(resp) or total
                    if total and have >= total:
                        break  # already complete
                    log.info("  attempt %d: resuming at %s / %s",
                             attempt, _mb(have), _mb(total) if total else "?")
                    resume = resp.status_code == 206
                    with open(part, "ab" if resume else "wb") as f:
                        last_log = time.time()
                        last_have = have if resume else 0
                        for chunk in resp.iter_bytes(chunk_size=512 * 1024):
                            f.write(chunk)
                            have += len(chunk)
                            now = time.time()
                            if total and now - last_log >= 5:
                                dt = max(1e-9, now - last_log)
                                log.info("  ... %d%% (%.1f MB/s)",
                                         have * 100 // total,
                                         (have - last_have) / 1e6 / dt)
                                last_log, last_have = now, have
            client.close()
        except (httpx.HTTPError, OSError) as exc:
            have = part.stat().st_size if part.exists() else 0
            log.warning("  attempt %d stalled/failed at %s: %s",
                        attempt, _mb(have), type(exc).__name__)
            if attempt < _DOWNLOAD_MAX_RETRIES:
                time.sleep(min(2 ** attempt, 30))
            continue

        have = part.stat().st_size if part.exists() else 0
        if total and have >= total:
            break
        log.info("  incomplete: %s / %s — will resume",
                 _mb(have), _mb(total) if total else "?")
    else:
        have = part.stat().st_size if part.exists() else 0
        raise RuntimeError(
            f"Failed to download {name} after {_DOWNLOAD_MAX_RETRIES} attempts "
            f"({_mb(have)} of {_mb(total) if total else '?'}). The GitHub "
            f"release mirror may be slow/blocked from your network — set "
            f"KOKORO_MODEL_URL / KOKORO_VOICES_URL to a faster mirror."
        )

    part.rename(dest)
    log.info("Downloaded %s (%s)", name, _mb(dest.stat().st_size))


def _ensure_model(model_dir: str | None = None) -> tuple[Path, Path]:
    """Return (model_path, voices_path); download if missing.

    Precedence: settings.kokoro.model_dir > ~/.cache/book2audio/kokoro.
    """
    cache_dir = Path(model_dir).expanduser() if model_dir else _DEFAULT_CACHE_DIR
    model_path = cache_dir / "kokoro-v1.1-zh.onnx"
    voices_path = cache_dir / "voices-v1.1-zh.bin"

    model_url, voices_url = _model_urls()
    if not model_path.exists():
        _download_file(model_url, model_path)
    if not voices_path.exists():
        _download_file(voices_url, voices_path)
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
        try:
            from kokoro_onnx import Kokoro
        except ImportError as e:
            raise RuntimeError(
                "Kokoro TTS needs 'onnxruntime'. Install with: pip install onnxruntime"
            ) from e

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
            import onnxruntime  # noqa: F401
            from kokoro_onnx import Kokoro  # noqa: F401
        except ImportError:
            _install_kokoro_onnx()
            try:
                from kokoro_onnx import Kokoro  # noqa: F401
            except ImportError as e:
                raise ValueError(
                    "Kokoro TTS needs 'onnxruntime'. Install with: pip install onnxruntime"
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
