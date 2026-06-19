from __future__ import annotations

import re
from pathlib import Path

import pdfplumber
from pdfminer.pdfparser import PDFParser as MinerParser
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage
from pdfminer.psparser import PSException
from pdfminer.pdftypes import resolve1

from config.settings import settings
from core.book_parser.base_parser import BaseBookParser
from core.models import BookFormat, BookMetadata, Chapter
from core.text_processor import TextProcessor
from utils.log import log


class PdfParser(BaseBookParser):
    def __init__(self, file_path: str):
        super().__init__(file_path)
        self.pdf: pdfplumber.PDF | None = None
        self._page_text_cache: dict[int, str] = {}  # Cache for extracted page text

    def validate(self) -> bool:
        try:
            self.pdf = pdfplumber.open(self.file_path)
            self._pre_extract_all_text()
            return True
        except Exception as e:
            log.error("Failed to read PDF: %s", e)
            return False
    
    def _pre_extract_all_text(self) -> None:
        """Pre-extract text from all pages and cache it."""
        log.info("PDF: Pre-extracting text from %d pages", len(self.pdf.pages))
        for page_num, page in enumerate(self.pdf.pages):
            text = page.extract_text(x_tolerance=2, y_tolerance=2)
            if not text:
                self._page_text_cache[page_num] = ""
                continue
            lines = text.split("\n")
            filtered = [
                line for line in lines
                if not re.match(r"^\s*\d+\s*$", line)
            ]
            self._page_text_cache[page_num] = "\n".join(filtered)

    def get_metadata(self) -> BookMetadata:
        if not self.pdf:
            self.validate()
        meta = self.pdf.metadata or {}
        return BookMetadata(
            id="",
            title=meta.get("Title") or Path(self.file_path).stem,
            author=meta.get("Author") or "Unknown",
            format=BookFormat.PDF,
            file_path=self.file_path,
        )

    def extract_cover(self, output_dir: Path) -> str | None:
        """Render first page as cover image. Return path or None."""
        if not self.pdf:
            self.validate()
        if not self.pdf.pages:
            return None
        try:
            page = self.pdf.pages[0]
            img = page.to_image(resolution=150)
            output_dir.mkdir(parents=True, exist_ok=True)
            cover_path = output_dir / "cover.png"
            img.save(cover_path)
            return str(cover_path)
        except Exception as e:
            log.warning("Failed to render PDF cover: %s", e)
            return None

    def get_chapters(self) -> list[Chapter]:
        if not self.pdf:
            self.validate()
        # 1. Try PDF outlines (TOC)
        toc = self._extract_toc()
        if toc and len(toc) >= 2:
            log.info("PDF: using TOC (%d entries)", len(toc))
            return self._chapters_from_toc(toc)
        # 2. Try heading detection via font analysis
        heading_chapters = self._chapters_from_headings()
        if heading_chapters:
            log.info("PDF: using heading detection (%d chapters)", len(heading_chapters))
            return heading_chapters
        # 3. Fallback: page-based splitting
        log.info("PDF: falling back to page-based splitting")
        chapters = self._chapters_from_pages()
        if not chapters:
            # No extractable text at all — almost certainly a scanned/image PDF.
            # Raise explicitly so the user gets an actionable error instead of a
            # silently empty book with zero chapters.
            total_chars = sum(len(t) for t in self._page_text_cache.values())
            raise ValueError(
                "PDF contains no extractable text (possibly a scanned/image-only "
                f"PDF; {len(self.pdf.pages)} pages, {total_chars} chars extracted). "
                "OCR is not supported — please provide a text-based PDF or an "
                "EPUB/TXT version."
            )
        return chapters

    def _extract_page_text(self, page: pdfplumber.page.Page) -> str:
        """Extract text from a single page, filtering noise."""
        # Check cache first
        page_num = page.page_number - 1  # 0-indexed
        if page_num in self._page_text_cache:
            return self._page_text_cache[page_num]
        
        text = page.extract_text(x_tolerance=2, y_tolerance=2)
        if not text:
            self._page_text_cache[page_num] = ""
            return ""
        lines = text.split("\n")
        filtered = [
            line for line in lines
            if not re.match(r"^\s*\d+\s*$", line)
        ]
        result = "\n".join(filtered)
        self._page_text_cache[page_num] = result
        return result

    # ------------------------------------------------------------------
    # Heading detection via font analysis
    # ------------------------------------------------------------------

    # Common chapter heading patterns — must be primary chapter divider
    _CHAPTER_PATTERN = re.compile(
        r"^("
        r"第[一二三四五六七八九十百千零〇\d]+[章章节回卷篇部]"
        r"|\bChapter\s+[\dIVXivx]+"
        r"|\bPart\s+[\dIVXivx]+"
        r"|\bCHAPTER\s+[\dIVXivx]+"
        r"|\bPART\s+[\dIVXivx]+"
        r")",
    )
    # Sub-heading patterns (小节标题) — these should NOT create new chapters
    _SUB_HEADING = re.compile(r"^(——|–|—|◎|●|◆|◇|▪|▸|>)")
    _TRAILING_PAGE_NUM = re.compile(r"\d{1,4}$")

    def _detect_headings(self) -> list[tuple[int, str]]:
        """Detect chapter headings using pattern matching + font size analysis.

        Strategy:
        1. Pattern-based: scan ALL lines (any font size) for 第X章/Chapter X patterns
        2. Size-based: if patterns found < 3, supplement with large-font lines

        Returns [(page_num_0indexed, heading_text), ...]
        """
        if not self.pdf:
            return []

        # Step 1: Determine body font size
        size_counter: dict[float, int] = {}
        for page in self.pdf.pages:
            for c in page.chars:
                size = round(c["size"], 1)
                size_counter[size] = size_counter.get(size, 0) + 1

        if not size_counter:
            return []

        body_size = max(size_counter, key=size_counter.get)
        heading_threshold = body_size * 1.15
        log.info("PDF heading detection: body_size=%.1f, threshold=%.1f", body_size, heading_threshold)

        # Step 2: Find TOC pages to skip
        toc_pages = self._detect_toc_pages(heading_threshold)

        # Step 3: Pre-compute header candidates for efficient duplicate detection
        # Instead of checking every page for each line, we build a frequency map first
        line_frequency: dict[str, int] = {}
        for page_idx, page in enumerate(self.pdf.pages):
            if page_idx in toc_pages:
                continue
            lines = self._extract_text_lines(page)
            for line_text, _ in lines:
                stripped = line_text.strip()
                if len(stripped) < 4 or len(stripped) > 60:
                    continue
                base = re.sub(r"\d+$", "", stripped).strip()
                if len(base) >= 4:
                    line_frequency[base] = line_frequency.get(base, 0) + 1

        # Step 4: Pattern-based scan (all font sizes)
        chapter_level: list[tuple[int, str]] = []
        seen_bases: set[str] = set()
        for page_idx, page in enumerate(self.pdf.pages):
            if page_idx in toc_pages:
                continue
            lines = self._extract_text_lines(page)
            for line_text, _line_size in lines:
                stripped = line_text.strip()
                if not self._CHAPTER_PATTERN.match(stripped):
                    continue
                # Strip trailing page number
                base = self._TRAILING_PAGE_NUM.sub("", stripped).strip()
                # Skip body-text references: "第X章，我们学习了..."
                # Real chapter headings are short and don't contain punctuation
                if any(c in base for c in "，。；：！？,.;:!?") and len(base) > 15:
                    continue
                # Skip repeated header (same base title, e.g. page headers)
                if base in seen_bases:
                    continue
                # Handle standalone "CHAPTER" without number — merge with next line
                if re.match(r"^(CHAPTER|PART|Chapter|Part)\s*$", base):
                    for next_text, _ in lines:
                        m = re.match(r"^([\dIVXivx]+)\s*$", next_text.strip())
                        if m:
                            base = f"{base} {m.group(1)}"
                            break
                seen_bases.add(base)
                chapter_level.append((page_idx, base))

        # Step 5: Deduplicate — merge nearby headings for the same chapter
        deduped: list[tuple[int, str]] = []
        for pg, title in chapter_level:
            if deduped:
                prev_pg, prev_title = deduped[-1]
                # Same page → skip duplicate
                if pg == prev_pg:
                    continue
                # Within 5 pages and both are chapter-level → merge
                if pg - prev_pg <= 5:
                    # Prefer the one with more info (longer title)
                    if len(title) > len(prev_title):
                        deduped[-1] = (prev_pg, title)
                    continue
            deduped.append((pg, title))

        # Step 6: Use deduped list
        chapter_level = deduped

        # Step 7: If we have enough, return
        if len(chapter_level) >= 3:
            log.info("PDF: found %d chapter-level headings via pattern", len(chapter_level))
            return chapter_level

        # Step 8: Supplement with size-based headings
        size_level: list[tuple[int, str]] = []
        for page_idx, page in enumerate(self.pdf.pages):
            if page_idx in toc_pages:
                continue
            lines = self._extract_text_lines(page)
            for line_text, line_size in lines:
                stripped = line_text.strip()
                if len(stripped) > 80 or len(stripped) < 2:
                    continue
                if line_size < heading_threshold:
                    continue
                # Check if this line appears on many pages (header/footer) using pre-computed frequency
                base = re.sub(r"\d+$", "", stripped).strip()
                if len(base) >= 4 and line_frequency.get(base, 0) >= 3:
                    continue
                if self._looks_like_noise(stripped):
                    continue
                # Merge sub-headings
                if self._SUB_HEADING.match(stripped):
                    if size_level and size_level[-1][0] == page_idx:
                        prev = size_level[-1][1]
                        size_level[-1] = (page_idx, f"{prev} {stripped}")
                    continue
                if size_level and size_level[-1][1] == stripped:
                    continue
                size_level.append((page_idx, stripped))

        if len(chapter_level) >= 1:
            merged = chapter_level + size_level
            merged.sort(key=lambda x: x[0])
            log.info("PDF: merged %d chapter + %d size headings", len(chapter_level), len(size_level))
            return merged

        if len(size_level) >= 2:
            log.info("PDF: using %d size-based headings", len(size_level))
            return size_level

        return []

    _NOISE_PATTERN = re.compile(
        r"^([\d+\-*/=().,\s]|"
        r"[\+\-]{2,}|"
        r"[a-z]{4,}\d+|"
        r"\d+[a-z]+\d+|"
        r"N{3,}|"
        r"[\+\-]?\d+[\+\-]?)$",
    )
    _CID_PATTERN = re.compile(r"\(cid:\d+\)")

    def _looks_like_noise(self, text: str) -> bool:
        """Filter out lines that look like formula fragments or noise."""
        if len(text) < 3:
            return True
        if self._NOISE_PATTERN.match(text):
            return True
        # More digits than letters → likely formula
        digits = sum(c.isdigit() for c in text)
        if digits > len(text) * 0.5 and len(text) < 30:
            return True
        # Check for cid:xxx patterns (LaTeX math symbols converted to Unicode)
        cid_count = len(self._CID_PATTERN.findall(text))
        if cid_count > 0:
            # Filter out any text containing cid patterns in heading detection
            # These are typically LaTeX math symbols that don't make good chapter titles
            return True
        return False

    def _detect_toc_pages(self, heading_threshold: float) -> set[int]:
        """Detect table of contents pages: pages with many large-font short lines."""
        toc_pages: set[int] = set()
        for page_idx, page in enumerate(self.pdf.pages):
            lines = self._extract_text_lines(page)
            large_short = sum(
                1 for text, size in lines
                if size >= heading_threshold and 2 < len(text.strip()) < 60
            )
            # TOC pages have 4+ large-font short lines on one page
            if large_short >= 4:
                toc_pages.add(page_idx)
        return toc_pages

    def _extract_text_lines(self, page: pdfplumber.page.Page) -> list[tuple[str, float]]:
        """Group chars into text lines, return [(text, max_font_size), ...]."""
        if not page.chars:
            return []
        # Sort by vertical position (top), then horizontal
        sorted_chars = sorted(page.chars, key=lambda c: (round(c["top"], 1), c["x0"]))
        lines: list[tuple[str, float]] = []
        current_text: list[str] = []
        current_max_size = 0.0
        current_y: float | None = None

        for c in sorted_chars:
            y = round(c["top"], 1)
            if current_y is not None and abs(y - current_y) > 3:
                # New line
                if current_text:
                    line = "".join(current_text).strip()
                    if line:
                        lines.append((line, current_max_size))
                current_text = []
                current_max_size = 0.0
            current_y = y
            current_text.append(c["text"])
            if c["size"] > current_max_size:
                current_max_size = c["size"]

        if current_text:
            line = "".join(current_text).strip()
            if line:
                lines.append((line, current_max_size))

        return lines

    def _is_repeated_header(self, page_idx: int, text: str) -> bool:
        """Check if this text appears on many pages (likely page header/footer).

        Strips trailing digits before comparing, since page headers often
        include a varying page number.
        """
        if len(text) > 60:
            return False
        # Strip trailing numbers (page numbers in headers)
        base = re.sub(r"\d+$", "", text).strip()
        if len(base) < 4:
            return True  # Very short text after stripping numbers → likely noise
        count = 0
        for i, page in enumerate(self.pdf.pages):
            if i == page_idx:
                continue
            page_text = page.extract_text() or ""
            if base in page_text:
                count += 1
            if count >= 3:  # Appears on 3+ other pages → header/footer
                return True
        return False

    def _chapters_from_headings(self) -> list[Chapter]:
        """Split content by detected headings."""
        headings = self._detect_headings()
        if len(headings) < 2:
            return []

        total_pages = len(self.pdf.pages)
        chapters: list[Chapter] = []

        for i, (start_page, title) in enumerate(headings):
            end_page = headings[i + 1][0] if i + 1 < len(headings) else total_pages
            text = ""
            for page_num in range(start_page, min(end_page, total_pages)):
                text += self._extract_page_text(self.pdf.pages[page_num]) + "\n"
            text = re.sub(r"\s+", " ", text).strip()
            if not text or len(text) < 10:
                continue
            chapters.append(
                Chapter(
                    index=len(chapters),
                    title=title[:100],
                    text=text,
                    char_count=len(text),
                    estimated_duration_seconds=TextProcessor.estimate_speech_duration(text),
                )
            )
        return chapters

    def _chapters_from_toc(self, toc: list) -> list[Chapter]:
        chapters = []
        total_pages = len(self.pdf.pages)
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
                text += self._extract_page_text(self.pdf.pages[page_num]) + "\n"
            text = re.sub(r"\s+", " ", text).strip()
            if not text or len(text) < 10:
                continue
            chapters.append(
                Chapter(
                    index=len(chapters),
                    title=title[:100],
                    text=text,
                    char_count=len(text),
                    estimated_duration_seconds=TextProcessor.estimate_speech_duration(text),
                )
            )
        return chapters if chapters else self._chapters_from_pages()

    def _chapters_from_pages(self) -> list[Chapter]:
        chapters = []
        pages_per_chapter = 5
        total = len(self.pdf.pages)
        for start in range(0, total, pages_per_chapter):
            text = ""
            for page_num in range(start, min(start + pages_per_chapter, total)):
                text += self._extract_page_text(self.pdf.pages[page_num]) + "\n"
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
                    estimated_duration_seconds=TextProcessor.estimate_speech_duration(text),
                )
            )
        return chapters

    def _extract_toc(self) -> list[tuple[int, str, int]]:
        """Extract TOC as [(level, title, page_number), ...].

        Returns empty list on any failure — caller falls back to page-based splitting.
        """
        try:
            with open(self.file_path, "rb") as f:
                parser = MinerParser(f)
                doc = PDFDocument(parser)
                if "Outlines" not in doc.catalog:
                    return []
                outlines = resolve1(doc.catalog["Outlines"])
                if not outlines:
                    return []
                # Build objid → page number mapping
                page_map: dict[int, int] = {}
                for i, page in enumerate(PDFPage.create_pages(doc)):
                    page_map[id(page)] = i + 1  # 1-indexed
                result: list[tuple[int, str, int]] = []
                self._walk_outlines(outlines, result, 1, page_map, doc)
                return result
        except (PSException, Exception) as e:
            log.warning("TOC extraction failed, falling back to page-based: %s", e)
            return []

    def _walk_outlines(
        self,
        node: object,
        result: list[tuple[int, str, int]],
        level: int,
        page_map: dict[int, int],
        doc: PDFDocument,
    ) -> None:
        """Recursively walk outline tree following /First and /Next links."""
        while node:
            title = node.get("Title")
            if isinstance(title, bytes):
                title = title.decode("utf-8", errors="replace")
            if not title:
                node = node.get("Next")
                continue
            page_num = self._resolve_dest_page(node, page_map, doc)
            if page_num:
                result.append((level, title, page_num))
            child = node.get("First")
            if child:
                self._walk_outlines(child, result, level + 1, page_map, doc)
            node = node.get("Next")

    def _resolve_dest_page(
        self,
        node: object,
        page_map: dict[int, int],
        doc: PDFDocument,
    ) -> int | None:
        """Resolve an outline node to a 1-indexed page number."""
        try:
            dest = node.get("Dest")
            if dest:
                if isinstance(dest, str):
                    dest = resolve1(dest)
                if isinstance(dest, list) and len(dest) > 0:
                    page_ref = dest[0]
                    return self._page_ref_to_num(page_ref, page_map)
            action = node.get("A")
            if action:
                a_dest = resolve1(action).get("D")
                if a_dest and isinstance(a_dest, list) and len(a_dest) > 0:
                    return self._page_ref_to_num(a_dest[0], page_map)
        except Exception:
            pass
        return None

    def _page_ref_to_num(
        self, page_ref: object, page_map: dict[int, int]
    ) -> int | None:
        """Map a pdfminer page reference to a 1-indexed page number."""
        try:
            objid = page_ref.objid if hasattr(page_ref, "objid") else None
            if objid:
                for pid, num in page_map.items():
                    if hasattr(pid, "objid") and pid.objid == objid:
                        return num
            # Fallback: resolve and check id()
            resolved = resolve1(page_ref)
            return page_map.get(id(resolved))
        except Exception:
            return None
