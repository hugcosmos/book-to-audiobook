from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from config.settings import settings

router = APIRouter()


@router.get("/download/{book_id}/{fmt}")
async def download_file(book_id: str, fmt: str):
    out_dir = settings.output_dir / book_id
    if not out_dir.exists():
        raise HTTPException(404, "Output not found")
    if fmt == "m4b":
        files = list(out_dir.glob("*.m4b"))
    elif fmt == "mp3":
        files = list(out_dir.glob("*.mp3"))
        files = [f for f in files if not f.name.startswith("_tmp_")]
    else:
        raise HTTPException(400, "Invalid format. Use 'm4b' or 'mp3'.")
    if not files:
        raise HTTPException(404, f"No {fmt} file found")
    return FileResponse(
        str(files[0]),
        media_type="application/octet-stream",
        filename=files[0].name,
    )


@router.get("/download/{book_id}/file/{filename:path}")
async def download_named_file(book_id: str, filename: str):
    out_dir = settings.output_dir / book_id
    file_path = out_dir / filename
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(404, "File not found")
    # Security: ensure path doesn't escape output dir
    try:
        file_path.resolve().relative_to(out_dir.resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")
    return FileResponse(
        str(file_path),
        media_type="application/octet-stream",
        filename=file_path.name,
    )
