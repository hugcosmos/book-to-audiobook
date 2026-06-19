from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.routes import chapters, convert, download, settings as settings_route, tts, upload
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
app.include_router(tts.router)
app.include_router(settings_route.router)

# Load persisted user settings
from config.user_settings import load_user_settings
load_user_settings()

# Eagerly preload the default local TTS model in background (non-blocking).
# qwen3_mlx: always warm up (model is local, fast on Apple Silicon).
# cosyvoice: only warm up if the model is already on disk — never trigger a
# multi-hundred-MB download at startup; the first synthesis downloads on demand.
def _preload_tts_model():
    import threading
    from utils.log import log

    provider = settings.tts.provider
    try:
        if provider == "qwen3_mlx":
            from core.tts_provider.qwen3_mlx_tts import Qwen3MLXTTSProvider
            if Qwen3MLXTTSProvider._model is not None or Qwen3MLXTTSProvider._worker_started:
                return
            log.info("Preloading MLX model in background (non-blocking)...")
            Qwen3MLXTTSProvider._request_queue = __import__("queue").Queue()
            Qwen3MLXTTSProvider._worker_started = True
            t = threading.Thread(target=Qwen3MLXTTSProvider._worker_loop, daemon=True)
            t.start()
        elif provider == "cosyvoice":
            from core.tts_provider.cosyvoice_tts import _resolve_model_dir, _find_onnx
            model_dir = _resolve_model_dir()
            # Only preload if model already downloaded; don't fetch at startup.
            if (model_dir / "tokens.txt").exists() and _find_onnx(model_dir).exists():
                from core.tts_provider.cosyvoice_tts import CosyVoiceTTSProvider
                log.info("Preloading CosyVoice model in background (non-blocking)...")
                t = threading.Thread(target=CosyVoiceTTSProvider.warmup, daemon=True)
                t.start()
            else:
                log.info("CosyVoice model not yet downloaded — will fetch on first synthesis")
    except Exception as e:
        log.warning("TTS preload skipped: %s", e)

_preload_tts_model()


def get_available_formats() -> list[str]:
    """Get list of actually available formats based on system dependencies."""
    from core.book_parser.parser_factory import SUPPORTED_FORMATS
    available = []
    for fmt in sorted(SUPPORTED_FORMATS):
        if fmt in {"epub", "pdf", "txt"}:
            available.append(fmt)
        elif fmt in {"mobi", "azw3"}:
            from utils.ffmpeg_utils import check_ebook_convert
            if check_ebook_convert():
                available.append(fmt)
    return available


@app.get("/")
async def index(request: Request):
    books = converter.get_all_books()
    return templates.TemplateResponse(
        request, "index.html",
        {"books": books, "supported_formats": get_available_formats()},
    )


def main():
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        reload_dirs=["app", "core", "config", "cli", "utils"],
    )


if __name__ == "__main__":
    main()
