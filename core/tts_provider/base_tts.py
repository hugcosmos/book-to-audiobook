from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

from core.models import TTSConfig

# Progress callback: (chunk_index, total_chunks)
ProgressCallback = Callable[[int, int], None]


class BaseTTSProvider(ABC):
    provider_name: str = ""
    supported_languages: list[str] = []

    def __init__(self, config: TTSConfig) -> None:
        self.config = config

    @abstractmethod
    async def synthesize(
        self, text: str, output_path: Path, progress: ProgressCallback | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> Path:
        """Convert text to speech, save as audio file. Return output path."""
        ...

    @abstractmethod
    def estimate_duration(self, char_count: int) -> float:
        """Estimate audio duration in seconds."""
        ...

    @staticmethod
    def get_break_string() -> str:
        return " "

    @classmethod
    def validate_config(cls, config: TTSConfig) -> None:
        """Validate provider-specific config (API keys etc). Override if needed."""
        pass

    @classmethod
    def warmup(cls) -> None:
        """Pre-load model / resources. Override for local models."""
        pass
