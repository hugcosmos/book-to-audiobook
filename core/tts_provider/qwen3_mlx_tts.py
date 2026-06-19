from __future__ import annotations

import asyncio
import queue
import subprocess
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

from config.settings import settings
from core.models import TTSConfig
from core.text_processor import TextProcessor
from core.tts_provider.base_tts import BaseTTSProvider
from utils.log import log


class Qwen3MLXTTSProvider(BaseTTSProvider):
    """Qwen3 TTS via MLX — optimized for Apple Silicon (3-5x faster than PyTorch).

    Uses a dedicated worker thread that owns the Metal/GPU context and model.
    Generation requests are sent via queue, results returned via asyncio.Future.
    This keeps the FastAPI event loop responsive for progress polling.
    """

    provider_name = "qwen3_mlx"
    supported_languages = [
        "zh-CN",
        "en-US",
        "ja-JP", "ko-KR",
        "fr-FR", "de-DE", "ru-RU",
        "pt-PT", "es-ES", "it-IT",
    ]

    _model = None
    _request_queue: queue.Queue | None = None
    _worker_ready = threading.Event()
    _worker_started = False
    _model_path: str | None = None

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        self.max_retries = settings.tts.max_retries
        if config.model_path:
            Qwen3MLXTTSProvider._model_path = config.model_path
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
                raise RuntimeError("MLX worker failed to load model within timeout")
            return
        cls.warmup()

    @classmethod
    def warmup(cls) -> None:
        if cls._model is not None:
            return
        if cls._worker_started:
            cls._worker_ready.wait(timeout=600)
            if cls._model is None:
                raise RuntimeError("MLX worker failed to load model within timeout")
            return

        cls._request_queue = queue.Queue()
        cls._worker_started = True
        t = threading.Thread(target=cls._worker_loop, daemon=True)
        t.start()
        log.info("Waiting for MLX worker thread to load model...")
        cls._worker_ready.wait(timeout=600)
        if cls._model is None:
            raise RuntimeError("MLX worker failed to load model within timeout")
        log.info("MLX worker thread ready")

    @classmethod
    def _worker_loop(cls) -> None:
        """Long-lived worker thread — owns Metal context and model."""
        import mlx.core as mx

        mx.set_default_device(mx.gpu)
        # Trigger stream creation
        _ = mx.zeros(1)

        from mlx_audio.tts.utils import load_model

        model_name = cls._model_path or settings.qwen3_mlx.model_path or settings.qwen3_mlx.model_name
        cls._model = load_model(model_name)
        log.info("Qwen3 TTS MLX model loaded in worker thread: %s", model_name)
        cls._worker_ready.set()

        while True:
            item = cls._request_queue.get()
            if item is None:
                break
            text, voice, lang_code, async_future, loop, kwargs = item
            # Skip work whose caller already cancelled (e.g. task.cancel() during
            # synthesis). We cannot interrupt an in-flight generate(), but we can
            # avoid spending GPU time on queued chunks nobody is awaiting, so a
            # cancel stays responsive for any not-yet-started chunks.
            if async_future.cancelled():
                continue
            try:
                # Dynamic max_tokens based on estimated speech duration.
                # At 12.5Hz codec, estimated_sec * 12.5 = core tokens.
                # Factor 1.8 gives comfortable margin for pauses and prosody.
                estimated_sec = TextProcessor.estimate_speech_duration(text)
                max_tokens = max(1024, int(estimated_sec * 12.5 * 1.8))
                gen_kwargs = dict(
                    text=text,
                    voice=voice,
                    lang_code=lang_code,
                    temperature=0.7,
                    top_p=0.95,
                    repetition_penalty=1.2,
                    max_tokens=max_tokens,
                    verbose=False,
                )
                # ICL voice cloning: lower temperature, higher repetition penalty
                if kwargs.get("ref_audio"):
                    gen_kwargs["temperature"] = 0.3
                    gen_kwargs["repetition_penalty"] = 1.8
                gen_kwargs.update(kwargs)
                # Voice cloning (ICL mode): CustomVoice model's generate()
                # returns early at custom_voice routing, skipping ref_audio
                # handling. Temporarily switch to base type so it falls through
                # to the ICL path.
                original_type = None
                if kwargs.get("ref_audio"):
                    original_type = cls._model.config.tts_model_type
                    cls._model.config.tts_model_type = "base"
                try:
                    results = list(cls._model.generate(**gen_kwargs))
                finally:
                    if original_type is not None:
                        cls._model.config.tts_model_type = original_type
                loop.call_soon_threadsafe(async_future.set_result, results)
            except Exception as e:
                loop.call_soon_threadsafe(async_future.set_exception, e)

    @classmethod
    def validate_config(cls, config: TTSConfig) -> None:
        try:
            import mlx_audio  # noqa: F401
        except ImportError:
            raise ValueError(
                "mlx-audio not installed. Run: pip install mlx-audio"
            )

    # ------------------------------------------------------------------
    # TTS synthesis
    # ------------------------------------------------------------------

    def _get_language_code(self) -> str:
        lang_map = {
            "zh-CN": "chinese", "zh-TW": "chinese", "zh-HK": "chinese",
            "en-US": "english", "en-GB": "english",
            "ja-JP": "japanese", "ko-KR": "korean",
            "fr-FR": "french", "de-DE": "german", "ru-RU": "russian",
            "pt-PT": "portuguese", "es-ES": "spanish", "it-IT": "italian",
        }
        return lang_map.get(self.config.language, "auto")

    def _chunk_char_limit(self, is_cloned: bool) -> int:
        """Derive chunk char limit from target audio duration and language speech rate."""
        # chars/sec by language family
        lang_speed = {
            "chinese": 4, "japanese": 5, "korean": 5,
            "english": 15, "french": 14, "german": 13,
            "russian": 12, "portuguese": 13, "spanish": 13, "italian": 13,
        }
        lang = self._get_language_code()
        cps = lang_speed.get(lang, 4)
        target_sec = settings.qwen3_mlx.chunk_max_seconds
        if is_cloned:
            target_sec = min(target_sec, 60)  # Cap clone mode at 60s to prevent drift
        return max(100, int(target_sec * cps))

    async def _submit_to_worker(self, text: str, voice: str | None = None, **kwargs) -> list:
        """Send text to worker thread and await result without blocking event loop."""
        loop = asyncio.get_running_loop()
        async_future = loop.create_future()
        self._request_queue.put((
            text,
            (voice or self.config.voice).lower(),
            self._get_language_code(),
            async_future,
            loop,
            kwargs,
        ))
        return await async_future

    async def synthesize(self, text: str, output_path: Path, progress=None, cancelled=None) -> Path:
        if not text or not text.strip():
            raise ValueError("No text to synthesize")

        # Derive chunk char limit from target audio duration and language speed
        from config.user_settings import get_cloned_voice_ref
        is_cloned = get_cloned_voice_ref(self.config.voice) is not None
        chunk_size = self._chunk_char_limit(is_cloned)
        chunks = TextProcessor.chunk(text, max_chars=chunk_size, language=self.config.language)
        log.info("Qwen3 MLX TTS: %d chunks (max %d chars, cloned=%s)", len(chunks), chunk_size, is_cloned)

        if not chunks:
            raise ValueError("No text to synthesize")

        if len(chunks) == 1:
            if progress:
                progress(0, 1)
            audio, sr = await self._synthesize_single(chunks[0])
            if progress:
                progress(1, 1)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            wav_path = output_path.with_suffix(".wav")
            sf.write(str(wav_path), audio, sr)
            wav_to_mp3(wav_path, output_path, self.config.speed)
            wav_path.unlink(missing_ok=True)
            return output_path

        # Multiple chunks: merge in memory
        audio_parts: list[np.ndarray] = []
        sample_rate: int | None = None
        for i, chunk in enumerate(chunks):
            if cancelled and cancelled():
                raise asyncio.CancelledError("Conversion cancelled")
            if progress:
                progress(i, len(chunks))
            log.info("MLX chunk %d/%d, length: %d", i + 1, len(chunks), len(chunk))
            audio, sr = await self._synthesize_single(chunk)
            if sample_rate is None:
                sample_rate = sr
            audio_parts.append(audio)

        if progress:
            progress(len(chunks), len(chunks))

        merged = np.concatenate(audio_parts)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        wav_path = output_path.with_suffix(".wav")
        sf.write(str(wav_path), merged, sample_rate)
        wav_to_mp3(wav_path, output_path, self.config.speed)
        wav_path.unlink(missing_ok=True)
        return output_path

    async def _synthesize_single(self, text: str) -> tuple[np.ndarray, int]:
        """Synthesize one chunk via worker thread — event loop stays responsive."""
        # Check if voice is a cloned voice
        kwargs = {}
        from config.user_settings import get_cloned_voice_ref
        ref = get_cloned_voice_ref(self.config.voice)
        if ref:
            ref_path = Path(ref["ref_audio"])
            if not ref_path.is_absolute():
                ref_path = Path(__file__).parent.parent.parent / ref_path
            kwargs["ref_audio"] = str(ref_path)
            if ref.get("ref_text"):
                kwargs["ref_text"] = ref["ref_text"]

        # Cloned voices: override voice id with built-in base speaker
        voice = self.config.voice.lower()
        if ref:
            gender = ref.get("gender", "female")
            voice = "serena" if gender == "female" else "uncle_fu"

        for attempt in range(self.max_retries):
            try:
                raw = await self._submit_to_worker(text, voice=voice, **kwargs)
                audio_parts = []
                sample_rate = 24000
                silent_count = 0
                for result in raw:
                    segment = np.array(result.audio)
                    rms = np.sqrt(np.mean(segment.astype(float) ** 2))
                    if rms > 0.005:
                        audio_parts.append(segment)
                    else:
                        silent_count += 1
                        log.warning(
                            "Skipping near-silent segment: rms=%.4f, %d samples",
                            rms, len(segment),
                        )
                    sample_rate = result.sample_rate

                if not audio_parts:
                    raise RuntimeError("MLX TTS returned no audio (all segments silent)")

                audio = np.concatenate(audio_parts)
                audio = _trim_trailing_silence(audio, sample_rate)
                duration = audio.shape[0] / sample_rate
                expected = TextProcessor.estimate_speech_duration(text)
                if silent_count > 0:
                    log.warning(
                        "Filtered %d/%d silent segments for %d chars",
                        silent_count, len(raw), len(text),
                    )
                log.info(
                    "MLX TTS chunk done: %d chars -> %.1f sec audio (expected ~%.1fs, %d segments filtered)",
                    len(text), duration, expected, silent_count,
                )
                # Retry if audio is suspiciously short (<30% of expected)
                if expected > 2.0 and duration < expected * 0.3:
                    raise RuntimeError(
                        f"Audio truncated: {duration:.1f}s vs expected {expected:.1f}s"
                    )
                return audio, sample_rate

            except Exception as e:
                log.warning(
                    "MLX TTS attempt %d/%d failed: %s",
                    attempt + 1, self.max_retries, e,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

    def estimate_duration(self, char_count: int) -> float:
        return char_count / (settings.tts.chars_per_second * self.config.speed)


def _trim_trailing_silence(audio: np.ndarray, sample_rate: int, threshold: float = 0.01) -> np.ndarray:
    """Trim trailing silence from audio, keeping a short natural tail."""
    if len(audio) == 0:
        return audio
    abs_audio = np.abs(audio)
    above = np.where(abs_audio > threshold)[0]
    if len(above) == 0:
        return audio
    # Keep 0.3 seconds of tail for natural ending
    keep_after = int(sample_rate * 0.3)
    end = min(above[-1] + keep_after, len(audio))
    return audio[:end]


def wav_to_mp3(wav_path: Path, mp3_path: Path, speed: float = 1.0) -> None:
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


def float_audio_to_wav(audio: np.ndarray, output_path: Path, sample_rate: int) -> None:
    """Write float audio array directly to WAV file using soundfile."""
    # Ensure float32 and correct shape
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim > 1:
        audio = np.squeeze(audio)
    sf.write(str(output_path), audio, sample_rate)
