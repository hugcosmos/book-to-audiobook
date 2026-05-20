from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from config.settings import settings
from core.models import ConversionRequest, ConversionStatus, TTSConfig

router = APIRouter()


class ConvertBody(BaseModel):
    selected_chapters: list[int]
    provider: str | None = None
    voice: str = "vivian"
    language: str = "zh-CN"
    speed: float | None = None
    output_m4b: bool = True
    output_mp3: bool = True


@router.post("/api/convert/{book_id}")
async def start_convert(book_id: str, body: ConvertBody):
    from app.main import app
    converter = app.state.converter
    book = converter.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    # Resolve speed: use conversion page value if set, otherwise provider default from settings
    effective_speed = body.speed
    if effective_speed is None:
        provider = body.provider or settings.tts.provider
        if provider == "qwen3_mlx":
            effective_speed = settings.qwen3_mlx.speed
        elif provider == "voxcpm":
            effective_speed = 1.0
        else:
            effective_speed = 1.0
    req = ConversionRequest(
        book_id=book_id,
        selected_chapters=body.selected_chapters,
        tts_config=TTSConfig(
            voice=body.voice,
            language=body.language,
            speed=effective_speed,
        ),
        tts_provider=body.provider,
        output_m4b=body.output_m4b,
        output_mp3=body.output_mp3,
    )
    converter.start_conversion(req)
    return {"book_id": book_id, "status": "started"}


@router.get("/api/convert/{book_id}/status")
async def get_status(book_id: str):
    from app.main import app
    converter = app.state.converter
    status = converter.get_status(book_id)
    # For terminal states (failed/cancelled), check if resumable manifest exists
    if not status or status.state in ("failed", "cancelled"):
        resumable = converter.get_resumable()
        for r in resumable:
            if r["book_id"] == book_id:
                return ConversionStatus(
                    book_id=book_id,
                    state="resumable",
                    total_chapters=r["total"],
                    completed_chapters=r["completed"],
                    progress_percent=r["progress_percent"],
                ).model_dump()
        if not status:
            return ConversionStatus(book_id=book_id, state="lost").model_dump()
    return status.model_dump()


@router.get("/api/convert/resumable")
async def list_resumable():
    from app.main import app
    converter = app.state.converter
    return converter.get_resumable()


@router.post("/api/convert/{book_id}/resume")
async def resume_convert(book_id: str):
    from app.main import app
    converter = app.state.converter
    try:
        converter.resume_conversion(book_id)
        return {"book_id": book_id, "status": "resumed"}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/api/convert/{book_id}/cancel")
async def cancel_convert(book_id: str):
    from app.main import app
    converter = app.state.converter
    converter.cancel(book_id)
    return {"book_id": book_id, "status": "cancelling"}


@router.delete("/api/books/{book_id}")
async def delete_book(book_id: str):
    """Delete a book and all associated files."""
    from app.main import app
    converter = app.state.converter
    book = converter.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    # Delete output files
    out_dir = settings.output_dir / book_id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    # Delete upload files
    upload_dir = settings.upload_dir / book_id
    if upload_dir.exists():
        shutil.rmtree(upload_dir)
    # Remove from memory
    converter.delete_book(book_id)
    return {"ok": True}


@router.delete("/api/convert/{book_id}/record/{timestamp}")
async def delete_conversion_record(book_id: str, timestamp: str):
    """Delete a conversion record and its output files."""
    from app.main import app
    converter = app.state.converter
    book = converter.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    # Find the record
    record = None
    for rec in book.conversions:
        if rec.timestamp == timestamp:
            record = rec
            break
    if not record:
        raise HTTPException(404, "Conversion record not found")
    # Delete output files
    out_dir = settings.output_dir / book_id
    for f in record.output_files:
        fpath = Path(f.path)
        if fpath.exists():
            fpath.unlink()
    # Remove record from book
    book.conversions = [r for r in book.conversions if r.timestamp != timestamp]
    converter.save_book(book)
    return {"ok": True}


class UpdateBookBody(BaseModel):
    title: str | None = None
    author: str | None = None


@router.put("/api/books/{book_id}")
async def update_book(book_id: str, body: UpdateBookBody):
    """Update book metadata (title, author)."""
    from app.main import app
    converter = app.state.converter
    book = converter.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    if body.title is not None:
        book.title = body.title.strip() or book.title
    if body.author is not None:
        book.author = body.author.strip() or book.author
    converter.save_book(book)
    return {"ok": True, "title": book.title, "author": book.author}
