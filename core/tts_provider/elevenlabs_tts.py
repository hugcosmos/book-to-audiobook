from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from config.settings import settings
from core.models import TTSConfig
from core.text_processor import TextProcessor
from core.tts_provider.base_tts import BaseTTSProvider
from utils.log import log


class ElevenLabsTTSProvider(BaseTTSProvider):
    provider_name = "elevenlabs"
    supported_languages = [
        "zh-CN", "zh-TW",
        "en-US", "en-GB",
        "ja-JP", "ko-KR",
        "fr-FR", "de-DE", "ru-RU",
        "pt-PT", "es-ES", "it-IT",
    ]

    _API_BASE = "https://api.elevenlabs.io/v1"

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        self.max_retries = settings.tts.max_retries

    @classmethod
    def validate_config(cls, config: TTSConfig) -> None:
        if not settings.elevenlabs.api_key:
            raise ValueError(
                "ElevenLabs TTS requires B2A_ELEVENLABS__API_KEY"
            )

    async def synthesize(self, text: str, output_path: Path, progress=None, cancelled=None) -> Path:
        if not text or not text.strip():
            raise ValueError("No text to synthesize")

        chunk_size = settings.elevenlabs.chunk_max_chars
        chunks = TextProcessor.chunk(text, max_chars=chunk_size, language=self.config.language)
        log.info("ElevenLabs TTS: %d chunks (max %d chars)", len(chunks), chunk_size)

        if not chunks:
            raise ValueError("No text to synthesize")

        if len(chunks) == 1:
            audio_bytes = await self._synthesize_single(chunks[0])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(audio_bytes)
            return output_path

        # Multiple chunks: merge via pydub
        from pydub import AudioSegment
        import tempfile, os

        merged = AudioSegment.empty()
        for i, chunk in enumerate(chunks):
            log.info("ElevenLabs chunk %d/%d", i + 1, len(chunks))
            audio_bytes = await self._synthesize_single(chunk)
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(audio_bytes)
            tmp.close()
            merged += AudioSegment.from_mp3(tmp.name)
            os.unlink(tmp.name)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        merged.export(str(output_path), format="mp3")
        return output_path

    async def _synthesize_single(self, text: str) -> bytes:
        """Synthesize one chunk, return MP3 bytes."""
        voice_id = self.config.voice
        url = f"{self._API_BASE}/text-to-speech/{voice_id}"

        headers = {
            "xi-api-key": settings.elevenlabs.api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        payload = {
            "text": text,
            "model_id": settings.elevenlabs.model_id,
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
            },
        }

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        url, json=payload, headers=headers, timeout=60,
                    )
                    resp.raise_for_status()

                content_type = resp.headers.get("content-type", "")
                if "audio" in content_type or resp.content[:2] == b"\xff\xfb":
                    return resp.content

                error_msg = resp.text[:200]
                raise RuntimeError(f"ElevenLabs error: {error_msg}")

            except Exception as e:
                log.warning(
                    "ElevenLabs attempt %d/%d failed: %s",
                    attempt + 1, self.max_retries, e,
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

    def estimate_duration(self, char_count: int) -> float:
        return char_count / settings.tts.chars_per_second
