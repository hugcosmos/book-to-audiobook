from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse

from config.settings import settings
from core.models import TTSConfig
from core.tts_provider.tts_factory import get_tts_provider
from core.tts_provider.voices import VoiceGender, VoiceInfo, get_voices

router = APIRouter(prefix="/api/tts")


class ProviderInfo(BaseModel):
    name: str
    label: str
    configured: bool


class VoiceItem(BaseModel):
    id: str
    name: str
    gender: str
    language: str
    description: str


_PROVIDER_LABELS = {
    "qwen3_mlx": "Qwen3 TTS (MLX · Apple Silicon)",
    "edge": "Edge TTS (免费在线)",
    "baidu": "百度语音合成",
    "iflytek": "科大讯飞语音合成",
    "elevenlabs": "ElevenLabs",
}


def _is_configured(provider: str) -> bool:
    """Check if provider has required credentials configured."""
    if provider == "qwen3_mlx":
        return True  # local model, no API key needed
    if provider == "edge":
        return True  # free, no auth needed
    if provider == "baidu":
        return bool(settings.baidu_tts.api_key and settings.baidu_tts.secret_key)
    if provider == "iflytek":
        return bool(settings.iflytek_tts.api_key and settings.iflytek_tts.api_secret)
    if provider == "elevenlabs":
        return bool(settings.elevenlabs.api_key)
    return False


@router.get("/providers")
async def list_providers():
    """List all TTS providers with configured status."""
    providers = []
    for name, label in _PROVIDER_LABELS.items():
        providers.append(ProviderInfo(
            name=name,
            label=label,
            configured=_is_configured(name),
        ))
    return providers


@router.get("/voices")
async def list_voices(provider: str, language: str | None = None):
    """Get available voices for a provider, optionally filtered by language."""
    voices = get_voices(provider, language)
    return [
        VoiceItem(
            id=v.id,
            name=v.name,
            gender=v.gender.value,
            language=v.language,
            description=v.description,
        )
        for v in voices
    ]


class PreviewBody(BaseModel):
    provider: str
    voice: str
    language: str = "zh-CN"
    speed: float = 1.0


_PREVIEW_DIR = Path(settings.output_dir) / "_preview"
_PREVIEW_TEXTS = {
    "zh-CN": "你好，这是语音预览。",
    "zh-TW": "你好，這是語音預覽。",
    "zh-HK": "你好，這是語音預覽。",
    "en-US": "Hello, this is a voice preview.",
    "en-GB": "Hello, this is a voice preview.",
    "ja-JP": "こんにちは、これは音声プレビューです。",
    "ko-KR": "안녕하세요, 음성 미리보기입니다.",
}


def _cleanup_preview(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


@router.post("/preview")
async def preview_voice(body: PreviewBody, background_tasks: BackgroundTasks):
    text = _PREVIEW_TEXTS.get(body.language, "Hello, this is a voice preview.")
    config = TTSConfig(voice=body.voice, language=body.language, speed=body.speed)
    try:
        provider = get_tts_provider(config=config, provider=body.provider)
    except Exception as e:
        raise HTTPException(400, str(e))
    _PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _PREVIEW_DIR / f"preview_{uuid.uuid4().hex[:8]}.mp3"
    try:
        await provider.synthesize(text, out_path)
    except Exception as e:
        _cleanup_preview(out_path)
        raise HTTPException(502, f"TTS synthesis failed: {e}")
    background_tasks.add_task(_cleanup_preview, out_path)
    return FileResponse(
        str(out_path),
        media_type="audio/mpeg",
        filename="preview.mp3",
    )
