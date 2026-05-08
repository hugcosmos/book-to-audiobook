from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.models import ConversionRequest, TTSConfig

router = APIRouter()


class ConvertBody(BaseModel):
    selected_chapters: list[int]
    voice: str = "zh-CN-XiaoxiaoNeural"
    language: str = "zh-CN"
    rate: str = "+0%"
    volume: str = "+0%"
    pitch: str = "+0Hz"
    output_m4b: bool = True
    output_mp3: bool = True


@router.post("/api/convert/{book_id}")
async def start_convert(book_id: str, body: ConvertBody):
    from app.main import app
    converter = app.state.converter
    book = converter.get_book(book_id)
    if not book:
        raise HTTPException(404, "Book not found")
    req = ConversionRequest(
        book_id=book_id,
        selected_chapters=body.selected_chapters,
        tts_config=TTSConfig(
            voice=body.voice,
            language=body.language,
            rate=body.rate,
            volume=body.volume,
            pitch=body.pitch,
        ),
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
    if not status:
        raise HTTPException(404, "Conversion job not found")
    return status.model_dump()


@router.post("/api/convert/{book_id}/cancel")
async def cancel_convert(book_id: str):
    from app.main import app
    converter = app.state.converter
    converter.cancel(book_id)
    return {"book_id": book_id, "status": "cancelling"}
