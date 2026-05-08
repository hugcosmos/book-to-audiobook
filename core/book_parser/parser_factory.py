from __future__ import annotations

from pathlib import Path

from core.book_parser.base_parser import BaseBookParser
from core.book_parser.epub_parser import EpubParser
from core.book_parser.mobi_parser import MobiParser
from core.book_parser.pdf_parser import PdfParser
from core.book_parser.txt_parser import TxtParser

SUPPORTED_FORMATS = {"epub", "mobi", "azw3", "pdf", "txt"}


def get_parser(file_path: str) -> BaseBookParser:
    ext = Path(file_path).suffix.lower().lstrip(".")
    if ext not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format: .{ext}. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}")
    parsers = {
        "epub": EpubParser,
        "pdf": PdfParser,
        "txt": TxtParser,
        "mobi": MobiParser,
        "azw3": MobiParser,
    }
    return parsers[ext](file_path)
