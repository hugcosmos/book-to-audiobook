from __future__ import annotations

import asyncio
import queue
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

from config.settings import settings
from core.models import TTSConfig
from core.text_processor import TextProcessor
from core.tts_provider.base_tts import BaseTTSProvider
from utils.log import log

# Reuse wav→mp3 helper from qwen3_mlx provider
from core.tts_provider.qwen3_mlx_tts import wav_to_mp3


class VoxCPMTTSProvider(BaseTTSProvider):
    """VoxCPM TTS — local diffusion-based model (OpenBMB).

    Uses a dedicated worker thread that owns the GPU context and model.
    Generation requests are sent via queue, results returned via asyncio.Future.
    Voice control via natural language instructions prepended to text.
    """

    provider_name = "voxcpm"
    supported_languages = ["zh-CN", "en-US"]

    _model = None
    _request_queue: queue.Queue | None = None
    _worker_ready = threading.Event()
    _worker_started = False
    _model_path: str | None = None
    SAMPLE_RATE = 16000

    # Voice ID → control instruction mapping
    _VOICE_CONTROL = {
        "zh_female_warm": "温暖柔和的女声",
        "zh_female_bright": "清脆明亮的女声",
        "zh_male_deep": "沉稳低沉的男声",
        "zh_male_youth": "充满活力的年轻男声",
        "en_female_warm": "warm female voice",
        "en_male_deep": "deep male voice",
        "default": "",
    }

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        self.max_retries = settings.tts.max_retries
        if config.model_path:
            VoxCPMTTSProvider._model_path = config.model_path
        self._ensure_worker()

    # ------------------------------------------------------------------
    # Worker thread management
    # ------------------------------------------------------------------

    @classmethod
    def _ensure_worker(cls) -> None:
        if cls._model is not None:
            return
        if cls._worker_started:
            cls._worker_ready.wait(timeout=600)
            if cls._model is None:
                raise RuntimeError("VoxCPM worker failed to load model within timeout")
            return
        cls.warmup()

    @classmethod
    def warmup(cls) -> None:
        if cls._model is not None:
            return
        if cls._worker_started:
            cls._worker_ready.wait(timeout=600)
            if cls._model is None:
                raise RuntimeError("VoxCPM worker failed to load model within timeout")
            return

        cls._request_queue = queue.Queue()
        cls._worker_started = True
        t = threading.Thread(target=cls._worker_loop, daemon=True)
        t.start()
        log.info("Waiting for VoxCPM worker thread to load model...")
        cls._worker_ready.wait(timeout=600)
        if cls._model is None:
            raise RuntimeError("VoxCPM worker failed to load model within timeout")
        log.info("VoxCPM worker thread ready")

    @classmethod
    def _worker_loop(cls) -> None:
        """Long-lived worker thread — owns GPU context and model."""
        from voxcpm import VoxCPM

        model_id = cls._model_path or settings.voxcpm.model_id
        cls._model = VoxCPM.from_pretrained(
            hf_model_id=model_id,
            load_denoiser=False,
            device=settings.voxcpm.device,
        )
        log.info("VoxCPM model loaded in worker thread: %s", model_id)
        cls._worker_ready.set()

        while True:
            item = cls._request_queue.get()
            if item is None:
                break
            text, cfg_value, inference_timesteps, async_future, loop, kwargs = item
            try:
                audio = cls._model.generate(
                    text=text,
                    cfg_value=cfg_value,
                    inference_timesteps=inference_timesteps,
                    **kwargs,
                )
                loop.call_soon_threadsafe(async_future.set_result, audio)
            except Exception as e:
                loop.call_soon_threadsafe(async_future.set_exception, e)

    @classmethod
    def validate_config(cls, config: TTSConfig) -> None:
        try:
            import voxcpm  # noqa: F401
        except ImportError:
            raise ValueError(
                "voxcpm not installed. Run: pip install voxcpm"
            )

    # ------------------------------------------------------------------
    # TTS synthesis
    # ------------------------------------------------------------------

    async def _submit_to_worker(self, text: str, **kwargs) -> np.ndarray:
        """Send text to worker thread and await result without blocking event loop."""
        loop = asyncio.get_running_loop()
        async_future = loop.create_future()
        self._request_queue.put((
            text,
            settings.voxcpm.cfg_value,
            settings.voxcpm.inference_timesteps,
            async_future,
            loop,
            kwargs,
        ))
        return await async_future

    async def synthesize(self, text: str, output_path: Path, progress=None, cancelled=None) -> Path:
        if not text or not text.strip():
            raise ValueError("No text to synthesize")

        chunk_size = settings.voxcpm.chunk_max_chars
        chunks = TextProcessor.chunk(text, max_chars=chunk_size, language=self.config.language)
        log.info("VoxCPM TTS: %d chunks (max %d chars)", len(chunks), chunk_size)

        if not chunks:
            raise ValueError("No text to synthesize")

        if len(chunks) == 1:
            if progress:
                progress(0, 1)
            audio = await self._synthesize_single(chunks[0])
            if progress:
                progress(1, 1)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path = output_path.with_suffix(".wav")
            sf.write(str(wav_path), audio, self.SAMPLE_RATE)
            wav_to_mp3(wav_path, output_path, self.config.speed)
            wav_path.unlink(missing_ok=True)
            return output_path

        # Multiple chunks: merge in memory
        audio_parts: list[np.ndarray] = []
        for i, chunk in enumerate(chunks):
            if cancelled and cancelled():
                raise asyncio.CancelledError("Conversion cancelled")
            if progress:
                progress(i, len(chunks))
            log.info("VoxCPM chunk %d/%d, length: %d", i + 1, len(chunks), len(chunk))
            audio = await self._synthesize_single(chunk)
            audio_parts.append(audio)

        if progress:
            progress(len(chunks), len(chunks))

        merged = np.concatenate(audio_parts)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path = output_path.with_suffix(".wav")
        sf.write(str(wav_path), merged, self.SAMPLE_RATE)
        wav_to_mp3(wav_path, output_path, self.config.speed)
        wav_path.unlink(missing_ok=True)
        return output_path

    async def _synthesize_single(self, text: str) -> np.ndarray:
        """Synthesize one chunk via worker thread — event loop stays responsive."""
        kwargs = {}

        # Voice cloning via reference audio takes priority
        from config.user_settings import get_cloned_voice_ref
        ref = get_cloned_voice_ref(self.config.voice)
        if ref:
            ref_path = Path(ref["ref_audio"])
            if not ref_path.is_absolute():
                ref_path = Path(__file__).parent.parent.parent / ref_path
            kwargs["reference_wav_path"] = str(ref_path)
        else:
            # Apply control instruction from voice ID
            control = self._VOICE_CONTROL.get(self.config.voice, "")
            if control:
                text = f"({control}){text}"

        for attempt in range(self.max_retries):
            try:
                audio = await self._submit_to_worker(text, **kwargs)
                duration = len(audio) / self.SAMPLE_RATE
                expected = TextProcessor.estimate_speech_duration(text)
                log.info(
                    "VoxCPM chunk done: %d chars -> %.1f sec audio (expected ~%.1fs)",
                    len(text), duration, expected,
                )
                # Retry if audio is suspiciously short (<30% of expected)
                if expected > 2.0 and duration < expected * 0.3:
                    raise RuntimeError(
                        f"Audio truncated: {duration:.1f}s vs expected {expected:.1f}s"
                    )
                return audio
            except Exception as e:
                log.warning(
                    "VoxCPM attempt %d/%d failed: %s",
                    attempt + 1, self.max_retries, e,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

    def estimate_duration(self, char_count: int) -> float:
        return char_count / (settings.tts.chars_per_second * self.config.speed)
