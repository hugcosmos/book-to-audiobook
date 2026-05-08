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
    def __init__(self, config: TTSConfig):
        super().__init__(config)
        self.max_retries = settings.tts_max_retries

    async def synthesize(self, text: str, output_path: Path) -> Path:
        chunks = TextProcessor.chunk(text, language=self.config.language)
        if not chunks:
            raise ValueError("No text to synthesize")
        temp_dir = output_path.parent / f"{output_path.stem}_chunks"
        temp_dir.mkdir(parents=True, exist_ok=True)
        chunk_files: list[Path] = []
        for i, chunk in enumerate(chunks):
            chunk_path = temp_dir / f"chunk_{i:04d}.mp3"
            await self._synthesize_chunk(chunk, chunk_path)
            chunk_files.append(chunk_path)
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
        for attempt in range(self.max_retries):
            try:
                communicate = edge_tts.Communicate(
                    text,
                    self.config.voice,
                    rate=self.config.rate,
                    volume=self.config.volume,
                    pitch=self.config.pitch,
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
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

    def estimate_duration(self, char_count: int) -> float:
        return char_count / settings.chars_per_second
