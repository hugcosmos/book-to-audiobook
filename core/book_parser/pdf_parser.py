from __future__ import annotations

import re
from pathlib import Path

import fitz  # pymupdf

from config.settings import settings
from core.book_parser.base_parser import BaseBookParser
from core.models import BookFormat, BookMetadata, Chapter
from utils.log import log


class PdfParser(BaseBookParser):
    def __init__(self, file_path: str):
        super().__init__(file_path)
        self.doc: fitz.Document | None = None

    def validate(self) -> bool:
        try:
            self.doc = fitz.open(self.file_path)
            return True
        except Exception as e:
            log.error("Failed to read PDF: %s", e)
            return False

    def get_metadata(self) -> BookMetadata:
        if not self.doc:
            self.validate()
        meta = self.doc.metadata or {}
        return BookMetadata(
            id="",
            title=meta.get("title") or Path(self.file_path).stem,
            author=meta.get("author") or "Unknown",
            format=BookFormat.PDF,
            file_path=self.file_path,
        )

    def get_chapters(self) -> list[Chapter]:
        if not self.doc:
            self.validate()
        toc = self.doc.get_toc()
        if toc and len(toc) >= 2:
            return self._chapters_from_toc(toc)
        return self._chapters_from_pages()

    def _chapters_from_toc(self, toc: list) -> list[Chapter]:
        chapters = []
        total_pages = len(self.doc)
        for idx, (level, title, start_page) in enumerate(toc):
            if level > 1:
                continue
            end_page = (
                toc[idx + 1][2] - 1
                if idx + 1 < len(toc)
                else total_pages
            )
            text = ""
            for page_num in range(start_page - 1, min(end_page, total_pages)):
                page = self.doc[page_num]
                text += page.get_text("text") + "\n"
            text = re.sub(r"\s+", " ", text).strip()
            if not text or len(text) < 10:
                continue
            chapters.append(
                Chapter(
                    index=len(chapters),
                    title=title[:100],
                    text=text,
                    char_count=len(text),
                    estimated_duration_seconds=len(text) / settings.chars_per_second,
                )
            )
        return chapters if chapters else self._chapters_from_pages()

    def _chapters_from_pages(self) -> list[Chapter]:
        chapters = []
        pages_per_chapter = 5
        total = len(self.doc)
        for start in range(0, total, pages_per_chapter):
            text = ""
            for page_num in range(start, min(start + pages_per_chapter, total)):
                text += self.doc[page_num].get_text("text") + "\n"
            text = re.sub(r"\s+", " ", text).strip()
            if not text or len(text) < 10:
                continue
            chapter_num = len(chapters) + 1
            chapters.append(
                Chapter(
                    index=len(chapters),
                    title=f"Section {chapter_num} (pages {start+1}-{min(start+pages_per_chapter, total)})",
                    text=text,
                    char_count=len(text),
                    estimated_duration_seconds=len(text) / settings.chars_per_second,
                )
            )
        return chapters
