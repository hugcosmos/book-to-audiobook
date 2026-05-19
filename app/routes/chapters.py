from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class ChapterTextUpdate(BaseModel):
    text: str


@router.get("/books/{book_id}")
async def book_detail_page(request: Request, book_id: str):
    converter = request.app.state.converter
    book = converter.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    templates = request.app.state.templates
    return templates.TemplateResponse(
        request, "chapters.html", {"book": book},
    )


@router.get("/api/books")
async def list_books(request: Request):
    converter = request.app.state.converter
    books = converter.get_all_books()
    return [
        {
            "id": b.id,
            "title": b.title,
            "author": b.author,
            "format": b.format.value,
            "chapter_count": len(b.chapters),
            "uploaded_at": b.uploaded_at,
            "conversion_count": len(b.conversions),
        }
        for b in books
    ]


@router.get("/api/books/{book_id}")
async def get_book_api(book_id: str):
    from app.main import app
    converter = app.state.converter
    book = converter.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    return {
        "book_id": book.id,
        "title": book.title,
        "author": book.author,
        "format": book.format.value,
        "chapters": [
            {
                "index": ch.index,
                "title": ch.title,
                "char_count": ch.char_count,
                "estimated_duration_seconds": round(ch.estimated_duration_seconds, 1),
                "edited": ch.edited,
            }
            for ch in book.chapters
        ],
        "conversions": [
            {
                "timestamp": c.timestamp,
                "selected_chapters": c.selected_chapters,
                "output_files": [
                    {"filename": f.filename, "type": f.type, "title": f.title}
                    for f in c.output_files
                ],
            }
            for c in book.conversions
        ],
    }


@router.get("/api/books/{book_id}/chapters/{chapter_index}/text")
async def get_chapter_text(request: Request, book_id: str, chapter_index: int):
    converter = request.app.state.converter
    text = converter.get_chapter_text(book_id, chapter_index)
    if text is None:
        raise HTTPException(404, "Chapter not found")
    return {"index": chapter_index, "text": text}


@router.put("/api/books/{book_id}/chapters/{chapter_index}/text")
async def update_chapter_text(
    request: Request, book_id: str, chapter_index: int, body: ChapterTextUpdate,
):
    converter = request.app.state.converter
    book = converter.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    chapter = next((ch for ch in book.chapters if ch.index == chapter_index), None)
    if not chapter:
        raise HTTPException(404, "Chapter not found")
    ok = converter.save_chapter_text(book_id, chapter_index, body.text)
    if not ok:
        raise HTTPException(500, "Failed to save chapter text")
    return {
        "ok": True,
        "char_count": chapter.char_count,
        "estimated_duration_seconds": round(chapter.estimated_duration_seconds, 1),
        "edited": True,
    }
