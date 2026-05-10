from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from config.settings import settings
from core.book_parser._epub_reader import EpubBook, read_epub
from core.book_parser.base_parser import BaseBookParser
from core.models import BookFormat, BookMetadata, Chapter
from core.text_processor import TextProcessor
from utils.log import log


class EpubParser(BaseBookParser):
    def __init__(self, file_path: str):
        super().__init__(file_path)
        self.book: EpubBook | None = None

    def validate(self) -> bool:
        try:
            self.book = read_epub(self.file_path)
            return True
        except Exception as e:
            log.error("Failed to read EPUB: %s", e)
            return False

    def get_metadata(self) -> BookMetadata:
        if not self.book:
            self.validate()
        title = self.book.get_metadata("DC", "title")
        author = self.book.get_metadata("DC", "author") or self.book.get_metadata("DC", "creator")
        book_title = title[0][0] if title else Path(self.file_path).stem
        book_author = author[0][0] if author else self._guess_author_from_filename()
        return BookMetadata(
            id="",
            title=book_title,
            author=book_author,
            format=BookFormat.EPUB,
            file_path=self.file_path,
        )

    def extract_cover(self, output_dir: Path) -> str | None:
        """Extract cover image from EPUB, save to output_dir/cover.*. Return relative path or None."""
        if not self.book:
            self.validate()
        cover_item = None
        for item in self.book.get_items():
            iid = (item.get_id() or "").lower()
            iname = (item.get_name() or "").lower()
            if item.is_image and ("cover" in iid or "cover" in iname):
                cover_item = item
                break
        # Fallback: any image item if only one exists
        if not cover_item:
            images = [i for i in self.book.get_items() if i.is_image]
            if len(images) == 1:
                cover_item = images[0]
        if not cover_item:
            return None
        content = cover_item.get_content()
        if not content:
            return None
        ext = Path(cover_item.get_name() or "cover.jpg").suffix or ".jpg"
        output_dir.mkdir(parents=True, exist_ok=True)
        cover_path = output_dir / f"cover{ext}"
        cover_path.write_bytes(content)
        return str(cover_path)

    def _guess_author_from_filename(self) -> str:
        """Try to extract author from filename like 'Title (Author).epub'."""
        stem = Path(self.file_path).stem
        m = re.search(r"[(\uff08](.+?)[)\uff09]", stem)
        if m:
            return m.group(1).strip()
        return "Unknown"

    def get_chapters(self) -> list[Chapter]:
        if not self.book:
            self.validate()
        toc = self._flatten_toc()
        if len(toc) >= 2:
            chapters = self._chapters_from_toc(toc)
            if chapters:
                return chapters
        return self._chapters_from_spine()

    def _flatten_toc(self) -> list[tuple[str, str]]:
        """Flatten book.toc to [(title, href)] for top-level entries only."""
        result = []
        for entry in self.book.toc:
            href = entry.href.split("#")[0]  # strip fragment
            title = entry.title or ""
            if title and href:
                result.append((title, href))
        return result

    def _build_spine_index_map(self) -> dict[str, int]:
        """Map item.get_name() → spine position index."""
        spine_map = {}
        for idx, item in enumerate(self.book.spine):
            if item.is_document:
                spine_map[item.get_name()] = idx
        return spine_map

    def _chapters_from_toc(self, toc: list[tuple[str, str]]) -> list[Chapter]:
        """Merge spine items between consecutive TOC entries into chapters."""
        spine_items = list(self.book.spine)
        spine_map = self._build_spine_index_map()

        # Map TOC entries to spine indices
        toc_spine_indices = []
        for title, href in toc:
            if href in spine_map:
                toc_spine_indices.append((title, href, spine_map[href]))
        if len(toc_spine_indices) < 2:
            return []

        # Sort by spine index
        toc_spine_indices.sort(key=lambda x: x[2])

        chapters = []
        idx = 0

        # Front matter: spine items before first TOC entry
        first_toc_idx = toc_spine_indices[0][2]
        for i in range(first_toc_idx):
            item_obj = spine_items[i]
            if item_obj is None or not item_obj.is_document:
                continue
            text = self._text_from_item(item_obj)
            if len(text) < 50:
                continue
            title = self._title_from_item(item_obj, idx)
            chapters.append(self._make_chapter(idx, title, text))
            idx += 1

        # TOC-guided chapters: merge spine items between consecutive entries
        for i in range(len(toc_spine_indices)):
            start = toc_spine_indices[i][2]
            end = toc_spine_indices[i + 1][2] if i + 1 < len(toc_spine_indices) else len(spine_items)
            title = toc_spine_indices[i][0]
            text_parts = []
            for j in range(start, end):
                item_obj = spine_items[j]
                if item_obj is None or not item_obj.is_document:
                    continue
                part = self._text_from_item(item_obj)
                if part:
                    text_parts.append(part)
            merged = " ".join(text_parts).strip()
            if len(merged) < 10:
                continue
            chapters.append(self._make_chapter(idx, title, merged))
            idx += 1

        return chapters

    def _chapters_from_spine(self) -> list[Chapter]:
        """Fallback: one chapter per spine item (original behavior)."""
        chapters = []
        idx = 0
        for item_obj in self.book.spine:
            if item_obj is None or not item_obj.is_document:
                continue
            text = self._text_from_item(item_obj)
            if len(text) < 10:
                continue
            title = self._title_from_item(item_obj, idx)
            chapters.append(self._make_chapter(idx, title, text))
            idx += 1
        return chapters

    def _text_from_item(self, item_obj) -> str:
        """Extract cleaned text from a spine item."""
        content = item_obj.get_content()
        if not content:
            return ""
        soup = BeautifulSoup(content, "lxml-xml")
        text = self._extract_text(soup)
        return re.sub(r"\s+", " ", text).strip()

    def _title_from_item(self, item_obj, fallback_idx: int) -> str:
        """Extract title from a spine item."""
        content = item_obj.get_content()
        if content:
            soup = BeautifulSoup(content, "lxml-xml")
            return self._extract_title(soup, fallback_idx)
        return f"Chapter {fallback_idx + 1}"

    def _make_chapter(self, idx: int, title: str, text: str) -> Chapter:
        return Chapter(
            index=idx,
            title=title,
            text=text,
            char_count=len(text),
            estimated_duration_seconds=TextProcessor.estimate_speech_duration(text),
        )

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
