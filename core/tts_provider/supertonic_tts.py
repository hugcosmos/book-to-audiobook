from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from config.settings import settings
from core.models import TTSConfig
from core.text_processor import TextProcessor
from core.tts_provider.base_tts import BaseTTSProvider
from utils.log import log

# BCP-47 prefix → Supertonic short code (identical for most)
_LANG_MAP: dict[str, str] = {
    "en": "en", "ko": "ko", "ja": "ja", "ar": "ar", "bg": "bg",
    "cs": "cs", "da": "da", "de": "de", "el": "el", "es": "es",
    "et": "et", "fi": "fi", "fr": "fr", "hi": "hi", "hr": "hr",
    "hu": "hu", "id": "id", "it": "it", "lt": "lt", "lv": "lv",
    "nl": "nl", "pl": "pl", "pt": "pt", "ro": "ro", "ru": "ru",
    "sk": "sk", "sl": "sl", "sv": "sv", "tr": "tr", "uk": "uk",
    "vi": "vi",
}

# Lazy-loaded TTS engine (shared across instances)
_tts_engine = None


def _get_engine():
    global _tts_engine
    if _tts_engine is None:
        from supertonic import TTS
        _tts_engine = TTS(auto_download=True)
    return _tts_engine


class SupertonicTTSProvider(BaseTTSProvider):
    provider_name = "supertonic"
    supported_languages = [
        "en-US", "en-GB", "ko-KR", "ja-JP", "ar-SA", "bg-BG",
        "cs-CZ", "da-DK", "de-DE", "el-GR", "es-ES", "et-EE",
        "fi-FI", "fr-FR", "hi-IN", "hr-HR", "hu-HU", "id-ID",
        "it-IT", "lt-LT", "lv-LV", "nl-NL", "pl-PL", "pt-PT",
        "pt-BR", "ro-RO", "ru-RU", "sk-SK", "sl-SI", "sv-SE",
        "tr-TR", "uk-UA", "vi-VN",
    ]

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        self.total_steps = settings.supertonic.total_steps
        self.speed = settings.supertonic.speed * config.speed
        self.chunk_max_chars = settings.supertonic.chunk_max_chars

        # Resolve language code
        prefix = config.language.split("-")[0].lower()
        self.lang_code = _LANG_MAP.get(prefix, "na")

    @classmethod
    def validate_config(cls, config: TTSConfig) -> None:
        try:
            import supertonic  # noqa: F401
        except ImportError as e:
            raise ValueError(
                "Supertonic TTS requires the 'supertonic' package. "
                "Install with: pip install supertonic"
            ) from e

    @classmethod
    def warmup(cls) -> None:
        _get_engine()

    async def synthesize(self, text: str, output_path: Path, progress=None, cancelled=None) -> Path:
        if not text or not text.strip():
            raise ValueError("No text to synthesize")

        chunks = TextProcessor.chunk(text, max_chars=self.chunk_max_chars, language=self.config.language)
        log.info("Supertonic TTS: %d chunks (max %d chars)", len(chunks), self.chunk_max_chars)

        if not chunks:
            raise ValueError("No text to synthesize")

        tts = _get_engine()
        voice_style = tts.get_voice_style(self.config.voice)

        all_audio: list[np.ndarray] = []

        for i, chunk in enumerate(chunks):
            if cancelled and cancelled():
                log.info("Supertonic TTS cancelled at chunk %d/%d", i + 1, len(chunks))
                raise RuntimeError("Synthesis cancelled")

            if progress:
                progress(i, len(chunks))

            wav, dur = await asyncio.to_thread(
                tts.synthesize,
                chunk,
                voice_style=voice_style,
                total_steps=self.total_steps,
                speed=self.speed,
                lang=self.lang_code,
            )
            all_audio.append(wav)
            log.info("Supertonic chunk %d/%d done (%.1fs)", i + 1, len(chunks), dur[0] if hasattr(dur, '__getitem__') else dur)

        if progress:
            progress(len(chunks), len(chunks))

        # Concatenate all chunks
        combined = np.concatenate(all_audio, axis=1)

        # WAV → MP3 via pydub
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        await asyncio.to_thread(sf.write, tmp_path, combined.T, tts.sample_rate)

        from pydub import AudioSegment
        audio = await asyncio.to_thread(AudioSegment.from_wav, tmp_path)
        Path(tmp_path).unlink(missing_ok=True)
        await asyncio.to_thread(audio.export, str(output_path), format="mp3")

        return output_path

    def estimate_duration(self, char_count: int) -> float:
        return char_count / (settings.tts.chars_per_second * self.speed)
