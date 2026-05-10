from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from config.settings import settings
from config.user_settings import (
    add_cloned_voice,
    add_custom_voice,
    delete_cloned_voice,
    delete_custom_voice,
    get_cloned_voices,
    get_custom_voices,
    get_hidden_voices,
    get_user_settings_dict,
    hide_voice,
    save_user_settings,
    unhide_voice,
)
from core.tts_provider.voices import get_voices

router = APIRouter()

_PROVIDER_FIELDS = {
    "edge_tts": [],
    "baidu_tts": ["app_id", "api_key", "secret_key"],
    "iflytek_tts": ["app_id", "api_key", "api_secret"],
    "elevenlabs": ["api_key", "model_id"],
    "qwen3_mlx": ["model_name", "chunk_max_seconds", "speed"],
}

_PROVIDER_LABELS = {
    "edge_tts": "Edge TTS",
    "baidu_tts": "Baidu TTS",
    "iflytek_tts": "iFlytek TTS",
    "elevenlabs": "ElevenLabs",
    "qwen3_mlx": "Qwen3 MLX",
}

# Maps settings section name to VOICE_REGISTRY provider key
_SECTION_TO_VOICE_PROVIDER = {
    "edge_tts": "edge",
    "baidu_tts": "baidu",
    "iflytek_tts": "iflytek",
    "elevenlabs": "elevenlabs",
    "qwen3_mlx": "qwen3_mlx",
}


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    from app.main import templates

    provider_configs = {}
    for section, fields in _PROVIDER_FIELDS.items():
        section_obj = getattr(settings, section, None)
        provider_configs[section] = {
            "label": _PROVIDER_LABELS.get(section, section),
            "fields": {},
            "voice_provider": _SECTION_TO_VOICE_PROVIDER.get(section, section),
        }
        for f in fields:
            provider_configs[section]["fields"][f] = getattr(section_obj, f, "")

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "provider_configs": provider_configs,
            "tts_default_provider": settings.tts.provider,
            "tts_default_voice": settings.tts.default_voice,
            "tts_default_language": settings.tts.default_language,
        },
    )


class SettingsBody(BaseModel):
    settings: dict


@router.get("/api/settings")
async def get_settings():
    return get_user_settings_dict()


@router.post("/api/settings")
async def update_settings(body: SettingsBody):
    save_user_settings(body.settings)
    return {"ok": True}


# --- Voice management APIs ---


@router.get("/api/settings/voices")
async def list_settings_voices(provider: str):
    """Return built-in (including hidden) + custom voices for a provider."""
    voices = get_voices(provider)
    custom = get_custom_voices(provider)
    hidden_ids = set(get_hidden_voices(provider))
    # Need all built-in voices including hidden ones, so fetch from original lists
    from core.tts_provider.voices import VOICE_REGISTRY, _QWEN3_VOICES, _EDGE_VOICES, _BAIDU_VOICES, _IFLYTEK_VOICES, _ELEVENLABS_VOICES
    _orig = {
        "qwen3_mlx": _QWEN3_VOICES, "edge": _EDGE_VOICES, "baidu": _BAIDU_VOICES,
        "iflytek": _IFLYTEK_VOICES, "elevenlabs": _ELEVENLABS_VOICES,
    }
    all_builtin = _orig.get(provider, [])
    return {
        "built_in": [
            {
                "id": v.id,
                "name": v.name,
                "gender": v.gender.value,
                "language": v.language,
                "description": v.description,
                "hidden": v.id in hidden_ids,
            }
            for v in all_builtin
        ],
        "custom": custom,
    }


class AddVoiceBody(BaseModel):
    provider: str
    id: str
    name: str
    language: str
    gender: str = ""
    description: str = ""


@router.post("/api/settings/voices")
async def add_voice(body: AddVoiceBody):
    try:
        add_custom_voice(body.provider, body.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


class DeleteVoiceBody(BaseModel):
    provider: str
    id: str


@router.delete("/api/settings/voices")
async def remove_voice(body: DeleteVoiceBody):
    delete_custom_voice(body.provider, body.id)
    return {"ok": True}


class HideVoiceBody(BaseModel):
    provider: str
    id: str


@router.post("/api/settings/voices/hide")
async def hide_voice_endpoint(body: HideVoiceBody):
    hide_voice(body.provider, body.id)
    return {"ok": True}


@router.post("/api/settings/voices/unhide")
async def unhide_voice_endpoint(body: HideVoiceBody):
    unhide_voice(body.provider, body.id)
    return {"ok": True}


# --- Voice cloning (Qwen3 MLX local only) ---


@router.get("/api/settings/cloned-voices")
async def list_cloned_voices():
    return get_cloned_voices()


@router.post("/api/settings/cloned-voices")
async def clone_voice(
    name: str = Form(""),
    language: str = Form("zh"),
    gender: str = Form("female"),
    description: str = Form(""),
    ref_text: str = Form(""),
    file: UploadFile = File(...),
):
    if not name:
        raise HTTPException(400, "Name is required")
    # Save reference audio
    ref_dir = Path("uploads") / "voice_refs"
    ref_dir.mkdir(parents=True, exist_ok=True)
    voice_id = f"clone_{uuid.uuid4().hex[:8]}"
    ext = Path(file.filename or "audio.wav").suffix or ".wav"
    ref_path = ref_dir / f"{voice_id}{ext}"
    ref_path.write_bytes(await file.read())

    try:
        add_cloned_voice(
            voice_id=voice_id,
            name=name,
            language=language,
            gender=gender,
            description=description,
            ref_audio_path=str(ref_path),
            ref_text=ref_text,
        )
    except ValueError as e:
        ref_path.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    return {"ok": True, "id": voice_id}


class DeleteClonedVoiceBody(BaseModel):
    id: str


@router.delete("/api/settings/cloned-voices")
async def remove_cloned_voice(body: DeleteClonedVoiceBody):
    # Also remove the ref audio file
    for v in get_cloned_voices():
        if v["id"] == body.id:
            try:
                Path(v["ref_audio"]).unlink(missing_ok=True)
            except OSError:
                pass
            break
    delete_cloned_voice(body.id)
    return {"ok": True}
