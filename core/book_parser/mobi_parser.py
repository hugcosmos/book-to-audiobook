from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from core.book_parser.base_parser import BaseBookParser
from core.book_parser.epub_parser import EpubParser
from core.models import BookFormat, BookMetadata, Chapter
from utils.log import log


class MobiParser(BaseBookParser):
    def __init__(self, file_path: str):
        super().__init__(file_path)
        self._epub_path: str | None = None

    def validate(self) -> bool:
        if not Path(self.file_path).exists():
            return False
        try:
            self._convert_to_epub()
            return True
        except Exception as e:
            log.error("MOBI/AZW3 conversion failed: %s", e)
            return False

    def _convert_to_epub(self) -> None:
        tmp = tempfile.mkdtemp()
        out = str(Path(tmp) / "converted.epub")
        result = subprocess.run(
            ["ebook-convert", self.file_path, out],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ebook-convert failed: {result.stderr}")
        self._epub_path = out

    def get_metadata(self) -> BookMetadata:
        if not self._epub_path:
            self.validate()
        parser = EpubParser(self._epub_path)
        meta = parser.get_metadata()
        ext = Path(self.file_path).suffix.lower().lstrip(".")
        meta.format = BookFormat(ext)
        meta.file_path = self.file_path
        return meta

    def get_chapters(self) -> list[Chapter]:
        if not self._epub_path:
            self.validate()
        parser = EpubParser(self._epub_path)
        return parser.get_chapters()
