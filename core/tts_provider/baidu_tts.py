from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf

from config.settings import settings
from core.models import TTSConfig
from core.text_processor import TextProcessor
from core.tts_provider.base_tts import BaseTTSProvider
from utils.log import log


class BaiduTTSProvider(BaseTTSProvider):
    provider_name = "baidu"
    supported_languages = ["zh-CN"]

    # Token cache
    _access_token: str | None = None
    _token_expires: float = 0

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        self.max_retries = settings.tts.max_retries

    @classmethod
    def validate_config(cls, config: TTSConfig) -> None:
        if not settings.baidu_tts.api_key or not settings.baidu_tts.secret_key:
            raise ValueError(
                "Baidu TTS requires B2A_BAIDU_TTS__API_KEY and B2A_BAIDU_TTS__SECRET_KEY"
            )

    async def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires:
            return self._access_token

        url = "https://aip.baidubce.com/oauth/2.0/token"
        params = {
            "grant_type": "client_credentials",
            "client_id": settings.baidu_tts.api_key,
            "client_secret": settings.baidu_tts.secret_key,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        token = data["access_token"]
        expires_in = data.get("expires_in", 2592000)
        BaiduTTSProvider._access_token = token
        BaiduTTSProvider._token_expires = time.time() + expires_in - 60
        log.info("Baidu TTS access token refreshed, expires in %ds", expires_in)
        return token

    def _get_lan(self) -> str:
        """Map language code to Baidu lan parameter."""
        lang = self.config.language
        if lang.startswith("zh"):
            return "zh"
        return "en"

    async def synthesize(self, text: str, output_path: Path, progress=None, cancelled=None) -> Path:
        if not text or not text.strip():
            raise ValueError("No text to synthesize")

        chunk_size = settings.baidu_tts.chunk_max_chars
        chunks = TextProcessor.chunk(text, max_chars=chunk_size, language=self.config.language)
        log.info("Baidu TTS: %d chunks (max %d chars)", len(chunks), chunk_size)

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
            if cancelled and cancelled():
                raise asyncio.CancelledError("Conversion cancelled")
            audio_bytes = await self._synthesize_single(chunk)
            # Baidu returns MP3 when aue=3
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(audio_bytes)
            tmp.close()
            merged += AudioSegment.from_mp3(tmp.name)
            os.unlink(tmp.name)
            if progress:
                progress(i + 1, len(chunks))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        merged.export(str(output_path), format="mp3")
        return output_path

    async def _synthesize_single(self, text: str) -> bytes:
        """Synthesize one chunk, return raw audio bytes."""
        token = await self._get_access_token()

        url = "https://tsn.baidu.com/text2audio"
        # Baidu spd (speech rate) range is [1, 15], where 5 is normal speed.
        # Map the normalized config.speed (1.0 == normal) onto that range.
        spd = max(1, min(15, int(round(5 * self.config.speed))))
        payload = {
            "tex": text,  # httpx form-encodes the body; do not pre-encode
            "tok": token,
            "cuid": "book-to-audiobook",
            "ctp": 1,
            "lan": self._get_lan(),
            "per": int(self.config.voice),
            "spd": spd,
            "pit": 5,
            "vol": 5,
            "aue": 3,  # mp3
        }

        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(url, data=payload, timeout=30)
                    resp.raise_for_status()

                content_type = resp.headers.get("content-type", "")
                if "audio" in content_type:
                    return resp.content

                # Baidu returns JSON on error
                error_msg = resp.text[:200]
                raise RuntimeError(f"Baidu TTS error: {error_msg}")

            except Exception as e:
                log.warning(
                    "Baidu TTS attempt %d/%d failed: %s",
                    attempt + 1, self.max_retries, e,
                )
                if attempt < self.max_retries - 1:
                    import random
                    await asyncio.sleep(2 ** attempt + random.uniform(0, 0.5))
                else:
                    raise

    def estimate_duration(self, char_count: int) -> float:
        return char_count / settings.tts.chars_per_second
