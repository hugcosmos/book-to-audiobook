from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import BookMetadata, Chapter


class BaseBookParser(ABC):
    def __init__(self, file_path: str):
        self.file_path = file_path

    @abstractmethod
    def get_metadata(self) -> BookMetadata: ...

    @abstractmethod
    def get_chapters(self) -> list[Chapter]: ...

    @abstractmethod
    def validate(self) -> bool: ...
