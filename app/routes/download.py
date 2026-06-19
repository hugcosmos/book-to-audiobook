from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from config.settings import settings

router = APIRouter()

# Cover images served from uploads dir
_COVER_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Filename prefixes that mark intermediate/transient artifacts, not user-facing
# outputs. These must never be served by the generic download route (a stale
# combined_temp.mp3 from a failed run could otherwise be returned as "the mp3").
_INTERMEDIATE_PREFIXES = ("_tmp_", "combined_temp", "_concat_")


def _is_intermediate(name: str) -> bool:
    return name.startswith(_INTERMEDIATE_PREFIXES)


@router.get("/download/{book_id}/{fmt}")
async def download_file(book_id: str, fmt: str):
    out_dir = settings.output_dir / book_id
    if not out_dir.exists():
        raise HTTPException(404, "Output not found")
    if fmt == "m4b":
        files = [f for f in out_dir.glob("*.m4b") if not _is_intermediate(f.name)]
        # Prefer the combined/whole-book m4b over any per-chapter artifact.
        files.sort(key=lambda f: _is_intermediate(f.name))
    elif fmt == "mp3":
        all_mp3 = [f for f in out_dir.glob("*.mp3") if not _is_intermediate(f.name)]
        # Per-chapter MP3s now carry an index segment
        # ("Book - 0001 - Title.mp3"); the combined output does not. Prefer the
        # combined file so "download mp3" yields the whole book, not one chapter.
        combined = [f for f in all_mp3 if " - " not in f.stem]
        files = combined or all_mp3
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


@router.get("/cover/{book_id}")
async def get_cover(book_id: str):
    """Serve book cover image from uploads dir."""
    upload_dir = settings.upload_dir / book_id
    if not upload_dir.exists():
        raise HTTPException(404, "Book not found")
    for ext in _COVER_EXTS:
        cover = upload_dir / f"cover{ext}"
        if cover.exists():
            media = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}
            return FileResponse(str(cover), media_type=media.get(ext.lstrip("."), "image/jpeg"))
    raise HTTPException(404, "No cover found")
