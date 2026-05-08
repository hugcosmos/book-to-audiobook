from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routes import chapters, convert, download, upload
from config.settings import settings
from core.converter import Converter

app = FastAPI(title="Book to Audiobook")

BASE_DIR = Path(__file__).resolve().parent

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

converter = Converter()

app.state.converter = converter
app.state.templates = templates

app.include_router(upload.router)
app.include_router(chapters.router)
app.include_router(convert.router)
app.include_router(download.router)


@app.get("/")
async def index(request: Request):
    books = converter.get_all_books()
    from core.book_parser.parser_factory import SUPPORTED_FORMATS
    return templates.TemplateResponse(
        request, "index.html",
        {"books": books, "supported_formats": sorted(SUPPORTED_FORMATS)},
    )


def main():
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)


if __name__ == "__main__":
    main()
