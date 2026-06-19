from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

import edge_tts
from pydub import AudioSegment

from config.settings import settings
from core.models import TTSConfig
from core.text_processor import TextProcessor
from core.tts_provider.base_tts import BaseTTSProvider
from utils.log import log


class EdgeTTSProvider(BaseTTSProvider):
    provider_name = "edge"
    supported_languages = [
        "zh-CN",
        "en-US",
        "ja-JP", "ko-KR",
        "fr-FR", "de-DE", "ru-RU", "es-ES",
    ]

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        self.max_retries = settings.tts.max_retries

    @staticmethod
    def _speed_to_rate(speed: float) -> str:
        """Convert speed float (0.5-2.0) to edge-tts rate string like '+50%'."""
        if speed == 1.0:
            return "+0%"
        pct = round((speed - 1.0) * 100)
        return f"+{pct}%" if pct >= 0 else f"{pct}%"

    async def synthesize(self, text: str, output_path: Path, progress=None, cancelled=None) -> Path:
        chunk_size = settings.edge_tts.chunk_max_chars
        chunks = TextProcessor.chunk(text, max_chars=chunk_size, language=self.config.language)
        if not chunks:
            raise ValueError("No text to synthesize")

        temp_dir = output_path.parent / f"{output_path.stem}_chunks"
        temp_dir.mkdir(parents=True, exist_ok=True)
        chunk_files: list[Path] = []

        for i, chunk in enumerate(chunks):
            if cancelled and cancelled():
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise asyncio.CancelledError("TTS cancelled")
            chunk_path = temp_dir / f"chunk_{i:04d}.mp3"
            await self._synthesize_chunk(chunk, chunk_path)
            chunk_files.append(chunk_path)
            if progress:
                progress(i + 1, len(chunks))

        if len(chunk_files) == 1:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            chunk_files[0].rename(output_path)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return output_path

        merged = AudioSegment.empty()
        for f in chunk_files:
            merged += AudioSegment.from_mp3(str(f))
            f.unlink(missing_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        merged.export(str(output_path), format="mp3")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return output_path

    async def _synthesize_chunk(self, text: str, output_path: Path) -> None:
        edge_cfg = settings.edge_tts
        for attempt in range(self.max_retries):
            try:
                communicate = edge_tts.Communicate(
                    text,
                    self.config.voice,
                    rate=self._speed_to_rate(self.config.speed),
                    volume=edge_cfg.volume,
                    pitch=edge_cfg.pitch,
                )
                await communicate.save(str(output_path))
                if output_path.exists() and output_path.stat().st_size > 0:
                    return
                raise RuntimeError("Output file empty or missing")
            except Exception as e:
                log.warning(
                    "TTS attempt %d/%d failed: %s",
                    attempt + 1,
                    self.max_retries,
                    e,
                )
                if attempt < self.max_retries - 1:
                    import random
                    await asyncio.sleep(2 ** attempt + random.uniform(0, 0.5))
                else:
                    raise

    def estimate_duration(self, char_count: int) -> float:
        return char_count / (settings.tts.chars_per_second * self.config.speed)
