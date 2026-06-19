from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from config.settings import settings
from core.book_parser.parser_factory import SUPPORTED_FORMATS, get_parser
from core.models import BookMetadata

router = APIRouter()


@router.post("/api/upload")
async def upload_file(request: Request, file: UploadFile = File(...)):
    ext = Path(file.filename or "").suffix.lower().lstrip(".")
    if ext not in SUPPORTED_FORMATS:
        raise HTTPException(400, f"Unsupported format: .{ext}")
    book_id = uuid.uuid4().hex[:12]
    upload_dir = settings.upload_dir / book_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / file.filename
    try:
        # Stream the upload to disk in chunks, enforcing the size limit as we go
        # so an oversized file is rejected before consuming its full size in RAM
        # (the previous await file.read() loaded the whole file first).
        max_bytes = settings.max_upload_size_mb * 1024 * 1024
        written = 0
        with open(file_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(400, "File too large")
                out.write(chunk)
        parser = get_parser(str(file_path))
        if not parser.validate():
            raise HTTPException(400, "Failed to parse file")
        metadata = parser.get_metadata()
        metadata.id = book_id
        metadata.file_path = str(file_path)
        chapters = parser.get_chapters()
        metadata.chapters = chapters
        # Extract cover image if supported
        if hasattr(parser, "extract_cover"):
            cover_path = parser.extract_cover(upload_dir)
            if cover_path:
                metadata.cover_path = cover_path
        converter = request.app.state.converter
        converter.add_book(metadata)
        return {"book_id": book_id, "title": metadata.title, "author": metadata.author, "chapter_count": len(chapters)}
    except HTTPException:
        # Clean up the partially-created upload dir on any rejection (oversize,
        # unsupported, parse failure) so it doesn't accumulate orphaned files.
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise
