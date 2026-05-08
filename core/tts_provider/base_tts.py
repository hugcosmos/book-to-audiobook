from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from core.models import TTSConfig


class BaseTTSProvider(ABC):
    def __init__(self, config: TTSConfig):
        self.config = config

    @abstractmethod
    async def synthesize(self, text: str, output_path: Path) -> Path:
        """Convert text to speech, save as audio file. Return output path."""
        ...

    @abstractmethod
    def estimate_duration(self, char_count: int) -> float:
        """Estimate audio duration in seconds."""
        ...

    @staticmethod
    def get_break_string() -> str:
        return " "
