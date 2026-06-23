"""CosyVoice TTS via sherpa-onnx (ONNX runtime, pure CPU).

Targeted at low-spec machines without a GPU (e.g. Intel MacBook Air): CosyVoice
is exported to a quantized ONNX model and run on CPU through sherpa-onnx, which
is far more practical than the native PyTorch path (the latter needs a CUDA/Metal
GPU to be usable). Only preset speakers are exposed here — no zero-shot cloning.

Model files are downloaded on first use. CosyVoice is Alibaba's, so ModelScope
(its home registry) is tried first — much faster than HuggingFace in mainland
China — with a HuggingFace fallback. Set model_dir to use a pre-downloaded copy.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from config.settings import settings
from core.models import TTSConfig
from core.text_processor import TextProcessor
from core.tts_provider.base_tts import BaseTTSProvider
from utils.log import log

# Default cache location when settings.cosyvoice.model_dir is unset.
_DEFAULT_MODEL_DIR = Path.home() / ".cache" / "book2audio" / "cosyvoice2"

# Lazy-loaded shared engine (one model instance for all conversions).
_tts_engine = None
_engine_lock = asyncio.Lock()


def _resolve_model_dir(override: str | None = None) -> Path:
    # Precedence: CLI/config model_path > settings.cosyvoice.model_dir > default cache.
    configured = override or settings.cosyvoice.model_dir
    return Path(configured).expanduser() if configured else _DEFAULT_MODEL_DIR


def _download_from_modelscope(repo: str, target: Path) -> None:
    """Download a model snapshot via the modelscope SDK."""
    from modelscope import snapshot_download
    snapshot_download(model_id=repo, local_dir=str(target))


def _download_from_huggingface(repo: str, target: Path) -> None:
    """Download a model snapshot via huggingface_hub (respects HF_ENDPOINT)."""
    from huggingface_hub import snapshot_download
    snapshot_download(repo_id=repo, local_dir=str(target))


def _ensure_model(override: str | None = None) -> Path:
    """Make sure the CosyVoice2 ONNX model files exist locally; download if not.

    Returns the directory containing model.onnx / cosyvoice2.int8.onnx,
    tokens.txt and espeak-ng-data/. ``override`` (from config.model_path / the
    CLI --model-path flag) takes precedence over settings.cosyvoice.model_dir.
    Download source is configurable (settings.cosyvoice.download_source); "auto"
    tries ModelScope first then HuggingFace.
    """
    model_dir = _resolve_model_dir(override)
    # Heuristic: the dir must contain a tokens.txt and an .onnx file.
    if (model_dir / "tokens.txt").exists() and list(model_dir.glob("*.onnx")):
        return model_dir

    model_dir.mkdir(parents=True, exist_ok=True)
    source = settings.cosyvoice.download_source.lower()
    # Ordered list of (label, repo, downloader) to try.
    attempts: list[tuple[str, str, callable]] = []
    if source in ("auto", "modelscope"):
        attempts.append(("ModelScope", settings.cosyvoice.modelscope_repo, _download_from_modelscope))
    if source in ("auto", "huggingface"):
        attempts.append(("HuggingFace", settings.cosyvoice.huggingface_repo, _download_from_huggingface))
    if not attempts:  # unknown source value
        attempts.append(("ModelScope", settings.cosyvoice.modelscope_repo, _download_from_modelscope))

    last_err: Exception | None = None
    for label, repo, downloader in attempts:
        log.info("Downloading CosyVoice model from %s (%s) → %s", label, repo, model_dir)
        try:
            downloader(repo, model_dir)
            if (model_dir / "tokens.txt").exists() and list(model_dir.glob("*.onnx")):
                log.info("CosyVoice model downloaded from %s", label)
                return model_dir
            last_err = RuntimeError(f"{label} download completed but model files missing")
        except Exception as e:  # noqa: BLE001 — fall through to next source
            log.warning("%s download failed: %s", label, e)
            last_err = e

    raise RuntimeError(
        f"Failed to download CosyVoice model from all configured sources ({source}): {last_err}. "
        f"Set B2A_COSYVOICE__MODEL_DIR to a directory with a pre-downloaded model, or "
        f"install modelscope / huggingface_hub and check network access."
    ) from last_err


def _find_onnx(model_dir: Path) -> Path:
    """Pick the CosyVoice2 ONNX file, preferring the int8/quantized variant."""
    # Prefer int8 (smaller, faster on CPU).
    candidates = sorted(model_dir.glob("*int8*.onnx")) + sorted(model_dir.glob("*.onnx"))
    if not candidates:
        raise RuntimeError(f"No .onnx file found in CosyVoice model dir: {model_dir}")
    return candidates[0]


def _get_engine(model_dir_override: str | None = None):
    """Lazily build (once) and return the sherpa_onnx OfflineTts engine.

    ``model_dir_override`` only takes effect on the first (engine-creating) call;
    subsequent calls reuse the cached engine regardless of the override.
    """
    global _tts_engine
    if _tts_engine is not None:
        return _tts_engine

    import sherpa_onnx

    model_dir = _ensure_model(model_dir_override)
    onnx_path = _find_onnx(model_dir)
    tokens_path = model_dir / "tokens.txt"
    espeak_dir = model_dir / "espeak-ng-data"

    cosyvoice_cfg = sherpa_onnx.OfflineTtsCosyVoice2ModelConfig(model=str(onnx_path))
    model_cfg = sherpa_onnx.OfflineTtsModelConfig(cosyvoice2=cosyvoice_cfg)
    tts_cfg = sherpa_onnx.OfflineTtsConfig(
        model=model_cfg,
        tokens=str(tokens_path),
        data_dir=str(espeak_dir) if espeak_dir.exists() else "",
        num_threads=settings.cosyvoice.num_threads,
        debug=False,
        provider="cpu",
    )
    start = time.time()
    _tts_engine = sherpa_onnx.OfflineTts(tts_cfg)
    log.info("CosyVoice engine loaded from %s in %.1fs", onnx_path.name, time.time() - start)
    return _tts_engine


def _sid_for(voice_id: str) -> int:
    """Map a voice id (e.g. '0', 'female1') to a speaker index."""
    # Preset voices register their id as the string form of the sid.
    try:
        return int(voice_id)
    except (TypeError, ValueError):
        return 0


class CosyVoiceTTSProvider(BaseTTSProvider):
    provider_name = "cosyvoice"
    # CosyVoice2 ships a multilingual model (zh / en / ja / ko + cross-lingual).
    supported_languages = [
        "zh-CN", "zh-TW", "zh-HK",
        "en-US", "en-GB",
        "ja-JP", "ko-KR",
    ]

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        self.speed = settings.cosyvoice.speed * config.speed
        self.chunk_max_chars = settings.cosyvoice.chunk_max_chars
        self.sid = _sid_for(config.voice)
        # CLI --model-path / config.model_path overrides settings.cosyvoice.model_dir.
        self._model_dir_override = config.model_path

    @classmethod
    def validate_config(cls, config: TTSConfig) -> None:
        try:
            import sherpa_onnx  # noqa: F401
        except ImportError as e:
            raise ValueError(
                "CosyVoice requires the 'sherpa-onnx' package (ONNX/CPU runtime). "
                "Install with: pip install sherpa-onnx"
            ) from e

    @classmethod
    def warmup(cls) -> None:
        _get_engine()

    async def synthesize(self, text: str, output_path: Path, progress=None, cancelled=None) -> Path:
        if not text or not text.strip():
            raise ValueError("No text to synthesize")

        chunks = TextProcessor.chunk(text, max_chars=self.chunk_max_chars, language=self.config.language)
        log.info("CosyVoice TTS: %d chunks (max %d chars)", len(chunks), self.chunk_max_chars)
        if not chunks:
            raise ValueError("No text to synthesize")

        engine = _get_engine(self._model_dir_override)

        async with _engine_lock:
            # sherpa_onnx is not async-safe across concurrent generate() calls
            # on the same engine; serialize them. Each generate() is CPU-bound
            # and runs in a worker thread so the event loop stays responsive.
            audio_parts: list[np.ndarray] = []
            sample_rate: int | None = None
            for i, chunk in enumerate(chunks):
                if cancelled and cancelled():
                    raise asyncio.CancelledError("Conversion cancelled")
                log.info("CosyVoice chunk %d/%d, length: %d", i + 1, len(chunks), len(chunk))
                audio = await asyncio.to_thread(
                    engine.generate, chunk, self.sid, self.speed
                )
                if sample_rate is None:
                    sample_rate = audio.sample_rate
                samples = np.asarray(audio.samples, dtype=np.float32)
                if samples.size == 0:
                    raise RuntimeError(f"CosyVoice returned empty audio for chunk {i + 1}")
                audio_parts.append(samples)
                if progress:
                    progress(i + 1, len(chunks))

        if progress:
            progress(len(chunks), len(chunks))

        # Normalize each part to 2-D before concatenating (mono may come back 1-D).
        normalized: list[np.ndarray] = []
        for part in audio_parts:
            arr = part
            if arr.ndim == 1:
                arr = arr.reshape(1, -1)
            normalized.append(arr)
        combined = np.concatenate(normalized, axis=1)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path = output_path.with_suffix(".wav")
        try:
            sf.write(str(wav_path), combined.T, sample_rate)
            # Reuse the shared wav→mp3 helper (loudnorm + atempo speed).
            from core.tts_provider.audio_utils import wav_to_mp3
            wav_to_mp3(wav_path, output_path, self.speed)
        finally:
            wav_path.unlink(missing_ok=True)
        return output_path

    def estimate_duration(self, char_count: int) -> float:
        return char_count / (settings.tts.chars_per_second * self.speed)
