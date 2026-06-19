from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse

from config.settings import settings
from core.models import TTSConfig
from core.tts_provider.tts_factory import _PROVIDER_MAP, get_tts_provider
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


class LanguageItem(BaseModel):
    code: str
    name: str


_LANG_DISPLAY = {
    "zh-CN": "Chinese",
    "en-US": "English (US)", "en-GB": "English (UK)",
    "ja-JP": "Japanese", "ko-KR": "Korean",
    "fr-FR": "French", "de-DE": "German", "ru-RU": "Russian",
    "es-ES": "Spanish", "pt-PT": "Portuguese (Portugal)", "pt-BR": "Portuguese (Brazil)",
    "it-IT": "Italian", "nl-NL": "Dutch",
    "ar-SA": "Arabic", "hi-IN": "Hindi",
    "bg-BG": "Bulgarian", "cs-CZ": "Czech", "da-DK": "Danish", "el-GR": "Greek",
    "et-EE": "Estonian", "fi-FI": "Finnish", "hr-HR": "Croatian", "hu-HU": "Hungarian",
    "id-ID": "Indonesian", "lt-LT": "Lithuanian", "lv-LV": "Latvian",
    "pl-PL": "Polish", "ro-RO": "Romanian", "sk-SK": "Slovak", "sl-SI": "Slovenian",
    "sv-SE": "Swedish", "tr-TR": "Turkish", "uk-UA": "Ukrainian", "vi-VN": "Vietnamese",
}


_PROVIDER_LABELS = {
    "qwen3_mlx": "Qwen3 TTS (MLX · Apple Silicon)",
    "edge": "Edge TTS (免费在线)",
    "baidu": "百度语音合成",
    "iflytek": "科大讯飞语音合成",
    "elevenlabs": "ElevenLabs",
    "supertonic": "Supertonic (Local · 31 langs)",
    "cosyvoice": "CosyVoice (本地 · ONNX/CPU)",
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
    if provider == "supertonic":
        try:
            import supertonic  # noqa: F401
            return True
        except ImportError:
            return False
    if provider == "cosyvoice":
        try:
            import sherpa_onnx  # noqa: F401
            return True
        except ImportError:
            return False
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


@router.get("/languages")
async def list_languages(provider: str):
    """Get supported languages for a provider."""
    if provider not in _PROVIDER_MAP:
        raise HTTPException(400, f"Unknown provider: {provider}")
    from importlib import import_module
    module_path, class_name = _PROVIDER_MAP[provider]
    cls = getattr(import_module(module_path), class_name)
    return [
        LanguageItem(code=lang, name=_LANG_DISPLAY.get(lang, lang))
        for lang in cls.supported_languages
    ]


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
    "en-US": "Hello, this is a voice preview.",
    "en-GB": "Hello, this is a voice preview.",
    "ja-JP": "こんにちは、これは音声プレビューです。",
    "ko-KR": "안녕하세요, 음성 미리보기입니다.",
    "fr-FR": "Bonjour, ceci est un aperçu vocal.",
    "de-DE": "Hallo, dies ist eine Sprachvorschau.",
    "ru-RU": "Здравствуйте, это предпрослушивание голоса.",
    "es-ES": "Hola, esta es una vista previa de voz.",
    "pt-PT": "Olá, esta é uma prévia de voz.",
    "pt-BR": "Olá, esta é uma prévia de voz.",
    "it-IT": "Ciao, questa è un'anteprima vocale.",
    "ar-SA": "مرحبا، هذا معاينة صوتية.",
    "hi-IN": "नमस्ते, यह एक आवाज़ पूर्वावलोकन है।",
    "nl-NL": "Hallo, dit is een spraakvoorbeeld.",
    "pl-PL": "Cześć, to jest podgląd głosu.",
    "tr-TR": "Merhaba, bu bir ses önizlemesidir.",
    "vi-VN": "Xin chào, đây là bản xem trước giọng nói.",
    "sv-SE": "Hej, det här är en förhandsgranskning av rösten.",
    "uk-UA": "Привіт, це попередній перегляд голосу.",
    "bg-BG": "Здравейте, това е предварителен преглед на гласа.",
    "cs-CZ": "Dobrý den, toto je náhled hlasu.",
    "da-DK": "Hej, dette er en forhåndsvisning af stemmen.",
    "el-GR": "Γεια σας, αυτή είναι μια προεπισκόπηση φωνής.",
    "et-EE": "Tere, see on hääle eelvaade.",
    "fi-FI": "Hei, tämä on äänen esikatselu.",
    "hr-HR": "Pozdrav, ovo je pregled glasa.",
    "hu-HU": "Helló, ez egy hang előnézet.",
    "id-ID": "Halo, ini adalah pratinjau suara.",
    "lt-LT": "Sveiki, tai balso peržiūra.",
    "lv-LV": "Sveiki, šis ir balss priekšskatījums.",
    "ro-RO": "Bună, aceasta este o previzualizare vocală.",
    "sk-SK": "Dobrý deň, toto je náhľad hlasu.",
    "sl-SI": "Pozdravljeni, to je predoglas glasu.",
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
