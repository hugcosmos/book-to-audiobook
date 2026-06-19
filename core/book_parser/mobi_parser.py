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
        # Held as an instance attribute so the temp dir lives as long as this
        # parser (get_metadata and get_chapters both need the converted epub),
        # and is cleaned up deterministically in close()/__del__ instead of
        # leaking forever.
        self._tmpdir: tempfile.TemporaryDirectory | None = None

    def validate(self) -> bool:
        if not Path(self.file_path).exists():
            return False
        try:
            self._convert_to_epub()
            return True
        except Exception as e:
            log.error("MOBI/AZW3 conversion failed: %s", e)
            # Make sure no half-created temp dir is left behind on failure.
            self.close()
            return False

    def _convert_to_epub(self) -> None:
        # Clean up any previous conversion's temp dir first.
        self.close()
        self._tmpdir = tempfile.TemporaryDirectory(prefix="b2a_mobi_")
        out = str(Path(self._tmpdir.name) / "converted.epub")
        try:
            result = subprocess.run(
                ["ebook-convert", self.file_path, out],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            self.close()
            raise RuntimeError(
                "Calibre is required for MOBI/AZW3 files. "
                "Install it from https://calibre-ebook.com/ (GPLv3, separate from this project's MIT license)"
            )
        if result.returncode != 0:
            self.close()
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

    def close(self) -> None:
        """Release the converted-epub temp directory."""
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None
            self._epub_path = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
