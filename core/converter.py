from __future__ import annotations

import asyncio
import json
from pathlib import Path

from core.audio_builder import AudioBuilder
from core.models import (
    BookMetadata,
    ConversionRecord,
    ConversionRequest,
    ConversionStatus,
    Chapter,
    OutputFile,
)
from core.tts_provider.tts_factory import get_tts_provider
from core.text_processor import TextProcessor
from config.settings import settings
from utils.log import log


class Converter:
    def __init__(self) -> None:
        self._books: dict[str, BookMetadata] = {}
        self._jobs: dict[str, ConversionStatus] = {}
        self._cancel_flags: dict[str, bool] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._load_books()

    def _load_books(self) -> None:
        upload_dir = settings.upload_dir
        if not upload_dir.exists():
            return
        for meta_path in upload_dir.glob("*/meta.json"):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                book = BookMetadata.model_validate(data)
                # Verify the book directory exists
                book_dir = meta_path.parent
                if not book_dir.exists():
                    log.warning("Book directory missing for %s, skipping", book.id)
                    continue
                # Verify the main file exists
                if book.file_path and not Path(book.file_path).exists():
                    log.warning("Book file missing for %s: %s, skipping", book.id, book.file_path)
                    continue
                self._books[book.id] = book
                log.info("Loaded book from disk: %s (%s)", book.title, book.id)
            except Exception as e:
                log.warning("Failed to load %s: %s", meta_path, e)

    def _save_book(self, book: BookMetadata) -> None:
        book_dir = settings.upload_dir / book.id
        book_dir.mkdir(parents=True, exist_ok=True)
        meta_path = book_dir / "meta.json"
        # Serialize without chapter text to keep file small
        data = book.model_dump()
        data["chapters"] = [
            {k: v for k, v in ch.items() if k != "text"}
            for ch in data["chapters"]
        ]
        meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_book(self, book: BookMetadata) -> None:
        self._books[book.id] = book
        self._save_book(book)

    def delete_book(self, book_id: str) -> None:
        self._books.pop(book_id, None)

    def save_book(self, book: BookMetadata) -> None:
        self._save_book(book)

    def get_book(self, book_id: str) -> BookMetadata | None:
        book = self._books.get(book_id)
        if book:
            # Validate that the book file still exists
            if book.file_path and not Path(book.file_path).exists():
                log.warning("Book file missing for %s, removing from memory", book_id)
                del self._books[book_id]
                return None
        return book

    def get_all_books(self) -> list[BookMetadata]:
        return list(self._books.values())

    def get_status(self, book_id: str) -> ConversionStatus | None:
        return self._jobs.get(book_id)

    def cancel(self, book_id: str) -> None:
        self._cancel_flags[book_id] = True
        task = self._tasks.get(book_id)
        if task and not task.done():
            task.cancel()

    def start_conversion(self, request: ConversionRequest) -> str:
        book_id = request.book_id
        if book_id not in self._books:
            raise ValueError(f"Book not found: {book_id}")
        status = ConversionStatus(
            book_id=book_id,
            state="pending",
            total_chapters=len(request.selected_chapters),
        )
        self._jobs[book_id] = status
        self._cancel_flags[book_id] = False
        task = asyncio.create_task(self._run_conversion(request))
        self._tasks[book_id] = task
        return book_id

    async def _run_conversion(self, request: ConversionRequest) -> None:
        book_id = request.book_id
        status = self._jobs[book_id]
        status.state = "running"
        try:
            book = self._books[book_id]
            selected = [ch for ch in book.chapters if ch.index in request.selected_chapters]
            tts = get_tts_provider(provider=request.tts_provider, config=request.tts_config)
            audio_builder = AudioBuilder()
            out_dir = settings.output_dir / book_id
            out_dir.mkdir(parents=True, exist_ok=True)
            chapter_files: list[tuple[Chapter, Path]] = []
            
            from core.book_parser.parser_factory import get_parser
            parser = get_parser(book.file_path)
            
            for i, chapter in enumerate(selected):
                if self._cancel_flags.get(book_id):
                    status.state = "cancelled"
                    status.current_chapter = "cancelled"
                    return
                status.current_chapter = chapter.title
                
                log.info(f"Processing chapter {i+1}: {chapter.title} (index: {chapter.index})")
                
                if not chapter.text:
                    log.info(f"Chapter text is empty, reloading from file...")
                    all_chapters = parser.get_chapters()
                    for ch in all_chapters:
                        if ch.index == chapter.index:
                            chapter.text = ch.text
                            log.info(f"Reloaded text length: {len(chapter.text) if chapter.text else 0}")
                            break
                
                text = TextProcessor.clean(chapter.text)
                log.info(f"Cleaned text length: {len(text)}")

                # Show current chapter immediately
                status.current_chapter = f"{chapter.title} (preparing...)"

                # Progress callback: chapter base + chunk progress within chapter
                def make_progress_cb(ch_idx, total_ch):
                    def cb(chunk_done, chunk_total):
                        if chunk_total <= 0:
                            return
                        chapter_frac = chunk_done / chunk_total
                        overall = (ch_idx + chapter_frac) / total_ch * 100
                        status.progress_percent = overall
                        status.current_chapter = (
                            f"{chapter.title} (chunk {chunk_done}/{chunk_total})"
                        )
                        log.info(
                            "Progress: %.1f%% — %s chunk %d/%d",
                            overall, chapter.title, chunk_done, chunk_total,
                        )
                    return cb

                temp_mp3 = out_dir / f"_tmp_{chapter.index:04d}.mp3"
                log.info(f"Starting TTS synthesis to: {temp_mp3}")
                cancel_check = lambda: self._cancel_flags.get(book_id, False)
                await tts.synthesize(text, temp_mp3, progress=make_progress_cb(i, len(selected)), cancelled=cancel_check)
                named_mp3 = out_dir / self._safe_filename(f"{book.title} - {chapter.title}.mp3")
                temp_mp3.rename(named_mp3)
                chapter_files.append((chapter, named_mp3))
                status.completed_chapters = i + 1
                status.progress_percent = (i + 1) / len(selected) * 100
                status.current_chapter = chapter.title
                log.info(
                    "Chapter %d/%d done: %s",
                    i + 1, len(selected), chapter.title,
                )
            output_files: list[OutputFile] = []
            # Per-chapter MP3s
            for chapter, ch_path in chapter_files:
                output_files.append(OutputFile(
                    path=str(ch_path),
                    filename=ch_path.name,
                    type="chapter",
                    title=chapter.title,
                ))
            # Combined file name based on titles
            combined_label = self._combined_label(selected, book)
            if request.output_m4b:
                m4b_name = self._safe_filename(f"{combined_label}.m4b")
                m4b_path = out_dir / m4b_name
                audio_builder.build_m4b(chapter_files, m4b_path, book.title, book.author, book.cover_path or None)
                output_files.append(OutputFile(
                    path=str(m4b_path),
                    filename=m4b_name,
                    type="m4b",
                ))
            if request.output_mp3:
                mp3_name = self._safe_filename(f"{combined_label}.mp3")
                mp3_path = out_dir / mp3_name
                audio_builder.build_combined_mp3(chapter_files, mp3_path)
                output_files.append(OutputFile(
                    path=str(mp3_path),
                    filename=mp3_name,
                    type="mp3",
                ))
            status.state = "completed"
            status.output_files = output_files
            status.progress_percent = 100.0
            # Persist conversion record
            record = ConversionRecord(
                selected_chapters=request.selected_chapters,
                output_files=output_files,
            )
            book.conversions.append(record)
            self._save_book(book)
            log.info("Conversion completed for book: %s", book.title)
        except asyncio.CancelledError:
            status.state = "cancelled"
            status.current_chapter = "cancelled"
        except Exception as e:
            log.error("Conversion failed: %s", e, exc_info=True)
            status.state = "failed"
            status.error_message = str(e)

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Remove/replace filesystem-unsafe characters."""
        for ch in ('/', '\\', ':', '*', '?', '"', '<', '>', '|'):
            name = name.replace(ch, '-')
        return name[:200]

    @staticmethod
    def _combined_label(selected: list[Chapter], book: BookMetadata) -> str:
        """Generate combined file label from chapter titles."""
        total = len(book.chapters)
        n = len(selected)
        if n == total:
            return book.title
        if n == 1:
            return f"{book.title} - {selected[0].title}"
        indices = sorted(ch.index for ch in selected)
        is_contiguous = indices == list(range(indices[0], indices[0] + n))
        if is_contiguous:
            return f"{book.title} - {selected[0].title}~{selected[-1].title}"
        return f"{book.title} - {selected[0].title}等{n}章"
