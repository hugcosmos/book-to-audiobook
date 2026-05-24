from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

from core.audio_builder import AudioBuilder
from core.models import (
    BookMetadata,
    ConversionManifest,
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
        self._resumable: dict[str, ConversionManifest] = {}
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
                # Mark chapters with edited text files on disk
                chapters_dir = book_dir / "chapters"
                if chapters_dir.exists():
                    for ch in book.chapters:
                        if (chapters_dir / f"{ch.index}.txt").exists():
                            ch.edited = True
                self._books[book.id] = book
                log.info("Loaded book from disk: %s (%s)", book.title, book.id)
                # Backfill detected_language using available text only (no re-parse)
                if not book.detected_language:
                    self._detect_and_save_language(book)
            except Exception as e:
                log.warning("Failed to load %s: %s", meta_path, e)
        # Scan for resumable conversions
        self._scan_resumable()

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

    def _detect_and_save_language(self, book: BookMetadata) -> None:
        """Detect book text language and store in metadata.
        Samples up to 5 chapters, each using only first 500 chars.
        Uses only in-memory text or on-disk chapter files — never triggers re-parse.
        """
        from collections import Counter
        samples: list[str] = []
        for ch in book.chapters:
            text = ch.text or ""
            if not text:
                text_path = settings.upload_dir / book.id / "chapters" / f"{ch.index}.txt"
                if text_path.exists():
                    text = text_path.read_text(encoding="utf-8")
            text = text.strip()[:500]
            if len(text) > 20:
                samples.append(TextProcessor.detect_language(text))
            if len(samples) >= 5:
                break
        if samples:
            # Store unique detected languages as comma-separated string
            # e.g. "zh-CN" (single) or "zh-CN,en-US" (mixed)
            unique = sorted(set(samples))
            book.detected_language = ",".join(unique)
            log.info("Detected language for %s: %s", book.id, book.detected_language)

    def add_book(self, book: BookMetadata) -> None:
        self._detect_and_save_language(book)
        self._books[book.id] = book
        self._save_book(book)

    def delete_book(self, book_id: str) -> None:
        self._books.pop(book_id, None)

    def save_book(self, book: BookMetadata) -> None:
        self._save_book(book)

    def get_chapter_text(self, book_id: str, chapter_index: int) -> str | None:
        book = self._books.get(book_id)
        if not book:
            return None
        chapter = next((ch for ch in book.chapters if ch.index == chapter_index), None)
        if not chapter:
            return None
        # Priority: disk file → in-memory → re-parse
        text_path = settings.upload_dir / book_id / "chapters" / f"{chapter_index}.txt"
        if text_path.exists():
            return text_path.read_text(encoding="utf-8")
        if chapter.text:
            return chapter.text
        # Re-parse from original file
        try:
            from core.book_parser.parser_factory import get_parser
            parser = get_parser(book.file_path)
            for ch in parser.get_chapters():
                if ch.index == chapter_index:
                    return ch.text
        except Exception as e:
            log.error("Failed to re-parse chapter %d: %s", chapter_index, e)
        return None

    def save_chapter_text(self, book_id: str, chapter_index: int, text: str) -> bool:
        book = self._books.get(book_id)
        if not book:
            return False
        chapter = next((ch for ch in book.chapters if ch.index == chapter_index), None)
        if not chapter:
            return False
        # Write to disk
        chapters_dir = settings.upload_dir / book_id / "chapters"
        chapters_dir.mkdir(parents=True, exist_ok=True)
        text_path = chapters_dir / f"{chapter_index}.txt"
        text_path.write_text(text, encoding="utf-8")
        # Update in-memory metadata
        chapter.edited = True
        chapter.char_count = len(text)
        from core.text_processor import TextProcessor
        cleaned = TextProcessor.clean(text)
        chars_per_second = 4.0
        chapter.estimated_duration_seconds = len(cleaned) / chars_per_second
        self._save_book(book)
        return True

    def discard_task(self, book_id: str) -> None:
        """Discard a cancelled/failed task, its manifest and output files."""
        self._jobs.pop(book_id, None)
        self._cancel_flags.pop(book_id, None)
        self._resumable.pop(book_id, None)
        # Delete manifest and output files
        out_dir = settings.output_dir / book_id
        if out_dir.exists():
            shutil.rmtree(out_dir)

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

    def _manifest_path(self, book_id: str) -> Path:
        return settings.output_dir / book_id / "_conversion.json"

    def _write_manifest(self, manifest: ConversionManifest) -> None:
        path = self._manifest_path(manifest.book_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")

    def _load_manifest(self, book_id: str) -> ConversionManifest | None:
        path = self._manifest_path(book_id)
        if not path.exists():
            return None
        try:
            return ConversionManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Failed to load manifest for %s: %s", book_id, e)
            return None

    def _scan_resumable(self) -> None:
        output_dir = settings.output_dir
        if not output_dir.exists():
            return
        for manifest_path in output_dir.glob("*/_conversion.json"):
            try:
                manifest = ConversionManifest.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
                if manifest.state in ("running", "failed") and manifest.book_id in self._books:
                    self._resumable[manifest.book_id] = manifest
                    log.info(
                        "Resumable conversion found: %s (%d/%d chapters done)",
                        manifest.book_id,
                        len(manifest.completed_chapters),
                        len(manifest.selected_chapters),
                    )
            except Exception as e:
                log.warning("Failed to scan manifest %s: %s", manifest_path, e)

    def get_resumable(self) -> list[dict]:
        result = []
        for book_id, manifest in self._resumable.items():
            book = self._books.get(book_id)
            if not book:
                continue
            done = len(manifest.completed_chapters)
            total = len(manifest.selected_chapters)
            result.append({
                "book_id": book_id,
                "book_title": book.title,
                "completed": done,
                "total": total,
                "progress_percent": round(done / total * 100, 1) if total else 0,
            })
        return result

    def resume_conversion(self, book_id: str) -> str:
        manifest = self._resumable.pop(book_id, None)
        if not manifest:
            raise ValueError(f"No resumable conversion for {book_id}")
        book = self._books.get(book_id)
        if not book:
            raise ValueError(f"Book not found: {book_id}")
        remaining = [i for i in manifest.selected_chapters if i not in manifest.completed_chapters]
        if not remaining:
            # All chapter MP3s done — check if M4B/combined MP3 still needed
            out_dir = settings.output_dir / book_id
            needs_merge = False
            if manifest.output_m4b:
                # Check if any m4b file exists
                if not list(out_dir.glob("*.m4b")):
                    needs_merge = True
            if manifest.output_mp3:
                combined_label = self._combined_label(
                    [ch for ch in book.chapters if ch.index in manifest.selected_chapters], book
                )
                combined_name = self._safe_filename(f"{combined_label}.mp3")
                if not (out_dir / combined_name).exists():
                    needs_merge = True
            if not needs_merge:
                raise ValueError("All chapters already completed")
        request = ConversionRequest(
            book_id=book_id,
            selected_chapters=remaining,
            tts_config=manifest.tts_config,
            tts_provider=manifest.tts_provider,
            output_m4b=manifest.output_m4b,
            output_mp3=manifest.output_mp3,
        )
        # Pre-populate completed count for accurate progress
        job_id = self.start_conversion(request)
        status = self._jobs[job_id]
        status.completed_chapters = len(manifest.completed_chapters)
        status.total_chapters = len(manifest.selected_chapters)
        status.progress_percent = status.completed_chapters / status.total_chapters * 100
        # Store completed indices for manifest tracking in _run_conversion
        self._resume_completed = getattr(self, '_resume_completed', {})
        self._resume_completed[book_id] = manifest.completed_chapters
        return job_id

    def start_conversion(self, request: ConversionRequest) -> str:
        book_id = request.book_id
        if book_id not in self._books:
            raise ValueError(f"Book not found: {book_id}")
        existing = self._jobs.get(book_id)
        if existing and existing.state in ("pending", "running"):
            raise ValueError(f"Conversion already running for {book_id}")
        # Clear stale job from previous cancelled/failed attempt
        if existing and existing.state in ("cancelled", "failed"):
            self._jobs.pop(book_id, None)
            self._cancel_flags.pop(book_id, None)
            self._resumable.pop(book_id, None)
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
        # Write manifest for crash recovery
        completed_indices = list(getattr(self, '_resume_completed', {}).pop(book_id, []))
        all_selected = sorted(set(request.selected_chapters + completed_indices))
        manifest = ConversionManifest(
            book_id=book_id,
            selected_chapters=all_selected,
            completed_chapters=completed_indices,
            tts_provider=request.tts_provider,
            tts_config=request.tts_config,
            output_m4b=request.output_m4b,
            output_mp3=request.output_mp3,
        )
        self._write_manifest(manifest)
        total_all = len(all_selected)
        base_completed = len(completed_indices)
        try:
            book = self._books[book_id]
            selected = [ch for ch in book.chapters if ch.index in request.selected_chapters]
            tts = get_tts_provider(provider=request.tts_provider, config=request.tts_config)
            audio_builder = AudioBuilder()
            out_dir = settings.output_dir / book_id
            out_dir.mkdir(parents=True, exist_ok=True)
            chapter_files: list[tuple[Chapter, Path]] = []
            # Collect already-completed chapter MP3s (from previous resume sessions)
            if completed_indices:
                for ch in book.chapters:
                    if ch.index in completed_indices:
                        named_mp3 = out_dir / self._safe_filename(f"{book.title} - {ch.title}.mp3")
                        if named_mp3.exists():
                            chapter_files.append((ch, named_mp3))
                        else:
                            # Fallback: check for temp MP3 left by interrupted merge
                            temp_mp3 = out_dir / f"_tmp_{ch.index:04d}.mp3"
                            if temp_mp3.exists() and temp_mp3.stat().st_size > 0:
                                temp_mp3.rename(named_mp3)
                                chapter_files.append((ch, named_mp3))
            
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
                    text_path = settings.upload_dir / book_id / "chapters" / f"{chapter.index}.txt"
                    if text_path.exists():
                        chapter.text = text_path.read_text(encoding="utf-8")
                        log.info(f"Loaded edited text from disk, length: {len(chapter.text)}")
                    else:
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
                def make_progress_cb(ch_idx, total_ch, base_done, total_all_ch):
                    def cb(chunk_done, chunk_total):
                        if chunk_total <= 0:
                            return
                        chapter_frac = chunk_done / chunk_total
                        overall = (base_done + ch_idx + chapter_frac) / total_all_ch * 100
                        status.progress_percent = overall
                        status.current_chapter = (
                            f"{chapter.title} (chunk {chunk_done}/{chunk_total})"
                        )
                        log.info(
                            "Progress: %.1f%% — %s chunk %d/%d",
                            overall, chapter.title, chunk_done, chunk_total,
                        )
                    return cb

                named_mp3 = out_dir / self._safe_filename(f"{book.title} - {chapter.title}.mp3")
                temp_mp3 = out_dir / f"_tmp_{chapter.index:04d}.mp3"
                if named_mp3.exists() and named_mp3.stat().st_size > 0:
                    log.info("Skipping chapter %d, MP3 already exists: %s", chapter.index, named_mp3.name)
                    chapter_files.append((chapter, named_mp3))
                    status.completed_chapters = base_completed + i + 1
                    status.progress_percent = (base_completed + i + 1) / total_all * 100
                    status.current_chapter = chapter.title
                    manifest.completed_chapters.append(chapter.index)
                    self._write_manifest(manifest)
                    continue
                if temp_mp3.exists() and temp_mp3.stat().st_size > 0:
                    log.info("Renaming temp MP3 for chapter %d: %s -> %s", chapter.index, temp_mp3.name, named_mp3.name)
                    temp_mp3.rename(named_mp3)
                    chapter_files.append((chapter, named_mp3))
                    status.completed_chapters = base_completed + i + 1
                    status.progress_percent = (base_completed + i + 1) / total_all * 100
                    status.current_chapter = chapter.title
                    manifest.completed_chapters.append(chapter.index)
                    self._write_manifest(manifest)
                    continue
                log.info(f"Starting TTS synthesis to: {temp_mp3}")
                cancel_check = lambda: self._cancel_flags.get(book_id, False)
                await tts.synthesize(text, temp_mp3, progress=make_progress_cb(i, len(selected), base_completed, total_all), cancelled=cancel_check)
                # Rename temp to final named MP3
                if temp_mp3.exists():
                    temp_mp3.rename(named_mp3)
                chapter_files.append((chapter, named_mp3))
                status.completed_chapters = base_completed + i + 1
                status.progress_percent = (base_completed + i + 1) / total_all * 100
                status.current_chapter = chapter.title
                # Update manifest after each chapter
                manifest.completed_chapters.append(chapter.index)
                self._write_manifest(manifest)
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
            # Combined file name based on all chapters in output (not just newly synthesized)
            combined_label = self._combined_label([ch for ch, _ in chapter_files], book)
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
            manifest.state = "completed"
            self._write_manifest(manifest)
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
            status.progress_percent = (len(manifest.completed_chapters) / len(all_selected) * 100) if all_selected else 0
            manifest.state = "cancelled"
            self._write_manifest(manifest)
            if manifest.book_id in self._books:
                self._resumable[manifest.book_id] = manifest
        except Exception as e:
            log.error("Conversion failed: %s", e, exc_info=True)
            status.state = "failed"
            status.error_message = str(e)
            status.progress_percent = (len(manifest.completed_chapters) / len(all_selected) * 100) if all_selected else 0
            manifest.state = "failed"
            self._write_manifest(manifest)
            # Re-add to resumable so user can retry without restart
            if manifest.book_id in self._books:
                self._resumable[manifest.book_id] = manifest

    @staticmethod
    def _safe_filename(name: str) -> str:
        """Remove/replace filesystem-unsafe characters."""
        for ch in ('/', '\\', ':', '*', '?', '"', '<', '>', '|'):
            name = name.replace(ch, '-')
        return name[:200]

    @staticmethod
    def _combined_label(selected: list[Chapter], book: BookMetadata) -> str:
        """Generate combined file label from chapter titles."""
        if not selected:
            return book.title
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
