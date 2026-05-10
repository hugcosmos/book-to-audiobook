from __future__ import annotations

import re
from pathlib import Path

from config.settings import settings
from core.book_parser.base_parser import BaseBookParser
from core.models import BookFormat, BookMetadata, Chapter
from core.text_processor import TextProcessor
from utils.log import log

CHAPTER_PATTERN = re.compile(
    r"^(chapter\s+\d+|part\s+\d+|第[一二三四五六七八九十百千\d]+[章节回]|卷[一二三四五六七八九十百千\d]+)",
    re.IGNORECASE | re.MULTILINE,
)


class TxtParser(BaseBookParser):
    def validate(self) -> bool:
        return Path(self.file_path).exists() and Path(self.file_path).suffix.lower() == ".txt"

    def get_metadata(self) -> BookMetadata:
        return BookMetadata(
            id="",
            title=Path(self.file_path).stem,
            author="Unknown",
            format=BookFormat.TXT,
            file_path=self.file_path,
        )

    def get_chapters(self) -> list[Chapter]:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            with open(self.file_path, "r", encoding="gbk") as f:
                content = f.read()
        if not content.strip():
            return []
        splits = CHAPTER_PATTERN.split(content)
        if len(splits) > 1:
            return self._parse_with_pattern(splits)
        return self._parse_by_double_newlines(content)

    def _parse_with_pattern(self, splits: list[str]) -> list[Chapter]:
        chapters = []
        i = 1
        while i < len(splits):
            title = splits[i].strip()
            text = splits[i + 1].strip() if i + 1 < len(splits) else ""
            text = re.sub(r"\s+", " ", text)
            if text:
                chapters.append(
                    Chapter(
                        index=len(chapters),
                        title=title[:100],
                        text=text,
                        char_count=len(text),
                        estimated_duration_seconds=TextProcessor.estimate_speech_duration(text),
                    )
                )
            i += 2
        return chapters

    def _parse_by_double_newlines(self, content: str) -> list[Chapter]:
        blocks = re.split(r"\n\s*\n", content)
        chapters = []
        buffer = ""
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            buffer += block + "\n"
            if len(buffer) >= 2000:
                text = re.sub(r"\s+", " ", buffer).strip()
                if text:
                    chapters.append(
                        Chapter(
                            index=len(chapters),
                            title=f"Section {len(chapters) + 1}",
                            text=text,
                            char_count=len(text),
                            estimated_duration_seconds=TextProcessor.estimate_speech_duration(text),
                        )
                    )
                buffer = ""
        if buffer.strip():
            text = re.sub(r"\s+", " ", buffer).strip()
            chapters.append(
                Chapter(
                    index=len(chapters),
                    title=f"Section {len(chapters) + 1}",
                    text=text,
                    char_count=len(text),
                    estimated_duration_seconds=len(text) / settings.tts.chars_per_second,
                )
            )
        return chapters
