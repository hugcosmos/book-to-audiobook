from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class BookFormat(str, Enum):
    EPUB = "epub"
    MOBI = "mobi"
    AZW3 = "azw3"
    PDF = "pdf"
    TXT = "txt"


class Chapter(BaseModel):
    index: int
    title: str
    text: str = ""
    char_count: int = 0
    estimated_duration_seconds: float = 0.0
    edited: bool = False


class OutputFile(BaseModel):
    path: str
    filename: str
    type: str  # "m4b" | "mp3" | "chapter"
    title: str = ""  # chapter title for chapter type


class ConversionRecord(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    selected_chapters: list[int] = Field(default_factory=list)
    output_files: list[OutputFile] = Field(default_factory=list)


class BookMetadata(BaseModel):
    id: str
    title: str = "Unknown"
    author: str = "Unknown"
    format: BookFormat
    file_path: str
    cover_path: str = ""
    chapters: list[Chapter] = Field(default_factory=list)
    conversions: list[ConversionRecord] = Field(default_factory=list)
    uploaded_at: str = Field(default_factory=lambda: datetime.now().isoformat())


class TTSConfig(BaseModel):
    voice: str = "vivian"
    language: str = "zh-CN"
    speed: float = 1.0
    model_path: str | None = None


class ConversionRequest(BaseModel):
    book_id: str
    selected_chapters: list[int]
    tts_config: TTSConfig = Field(default_factory=TTSConfig)
    tts_provider: str | None = None
    output_m4b: bool = True
    output_mp3: bool = True


class ConversionStatus(BaseModel):
    book_id: str
    state: str = "pending"  # pending | running | completed | failed | cancelled | resumable
    total_chapters: int = 0
    completed_chapters: int = 0
    current_chapter: str | None = None
    progress_percent: float = 0.0
    error_message: str | None = None
    output_files: list[OutputFile] = Field(default_factory=list)


class ConversionManifest(BaseModel):
    book_id: str
    selected_chapters: list[int]
    completed_chapters: list[int] = Field(default_factory=list)
    tts_provider: str | None = None
    tts_config: TTSConfig = Field(default_factory=TTSConfig)
    output_m4b: bool = True
    output_mp3: bool = True
    state: str = "running"  # running | completed | failed
