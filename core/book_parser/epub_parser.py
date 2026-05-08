from __future__ import annotations

import re
from pathlib import Path

import ebooklib
from bs4 import BeautifulSoup
from ebooklib import epub

from config.settings import settings
from core.book_parser.base_parser import BaseBookParser
from core.models import BookFormat, BookMetadata, Chapter
from utils.log import log


class EpubParser(BaseBookParser):
    def __init__(self, file_path: str):
        super().__init__(file_path)
        self.book: epub.EpubBook | None = None

    def validate(self) -> bool:
        try:
            self.book = epub.read_epub(self.file_path)
            return True
        except Exception as e:
            log.error("Failed to read EPUB: %s", e)
            return False

    def get_metadata(self) -> BookMetadata:
        if not self.book:
            self.validate()
        title = self.book.get_metadata("DC", "title")
        author = self.book.get_metadata("DC", "author")
        book_title = title[0][0] if title else Path(self.file_path).stem
        book_author = author[0][0] if author else "Unknown"
        return BookMetadata(
            id="",
            title=book_title,
            author=book_author,
            format=BookFormat.EPUB,
            file_path=self.file_path,
        )

    def get_chapters(self) -> list[Chapter]:
        if not self.book:
            self.validate()
        chapters = []
        idx = 0
        for item in self.book.spine:
            if isinstance(item, tuple):
                item_id = item[0]
                item_obj = self.book.get_item_with_id(item_id)
            else:
                item_obj = item
            if item_obj is None:
                continue
            if item_obj.get_type() != ebooklib.ITEM_DOCUMENT:
                continue
            content = item_obj.get_content()
            if not content:
                continue
            soup = BeautifulSoup(content, "lxml-xml")
            text = self._extract_text(soup)
            text = re.sub(r"\s+", " ", text).strip()
            if not text or len(text) < 10:
                continue
            title = self._extract_title(soup, idx)
            chapters.append(
                Chapter(
                    index=idx,
                    title=title,
                    text=text,
                    char_count=len(text),
                    estimated_duration_seconds=len(text) / settings.chars_per_second,
                )
            )
            idx += 1
        return chapters

    def _extract_text(self, soup: BeautifulSoup) -> str:
        body = soup.find("body")
        if body:
            return body.get_text(separator=" ", strip=True)
        return soup.get_text(separator=" ", strip=True)

    def _extract_title(self, soup: BeautifulSoup, fallback_idx: int) -> str:
        for tag in ["title", "h1", "h2", "h3"]:
            el = soup.find(tag)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)[:100]
        return f"Chapter {fallback_idx + 1}"
