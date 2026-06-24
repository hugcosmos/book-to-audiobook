from __future__ import annotations

import asyncio
import os
import platform
import subprocess
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse

from config.settings import settings
from core.models import InstallStatus, TTSConfig
from core.tts_provider.tts_factory import _PROVIDER_MAP, get_tts_provider
from core.tts_provider.voices import VoiceGender, VoiceInfo, get_voices

router = APIRouter(prefix="/api/tts")


class ProviderInfo(BaseModel):
    name: str
    label: str
    configured: bool
    # Human-readable reason when not configured (missing API key, missing model
    # files, etc.). Empty when configured. Shown in the UI next to the provider.
    note: str = ""
    # True if an unconfigured provider can be made ready via the install API
    # (downloading a model / pip-installing a package). False for providers
    # that need manual setup (API keys) or are unusable on this machine.
    installable: bool = False
    # Live install state: idle | installing. Set by /providers when an install
    # task is in flight so the UI can show a spinner instead of the button.
    status: str = "idle"


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
    "kokoro": "Kokoro TTS (本地 · ONNX · 中文)",
}


def _kokoro_model_ready() -> bool:
    """True if both Kokoro model files are present in the cache dir."""
    from core.tts_provider import kokoro_tts
    cache = Path(settings.kokoro.model_dir).expanduser() if settings.kokoro.model_dir \
        else kokoro_tts._DEFAULT_CACHE_DIR
    return (cache / "kokoro-v1.1-zh.onnx").exists() \
        and (cache / "voices-v1.1-zh.bin").exists()


def _check_configured(provider: str) -> tuple[bool, str, bool]:
    """Return (configured, note, installable) for a provider.

    For local-model providers this checks both the runtime package AND the
    model files actually being present — merely having the package installed
    is not enough, since first-use download can fail on a slow link. This
    prevents the UI from advertising a provider the user cannot actually use.

    ``installable`` is True only when an unconfigured provider can be made
    ready by the install API (model download / pip install), so the UI knows
    when to show an Install button. API-key providers and providers that are
    unusable on this machine (e.g. MLX on Intel) are not installable.
    """
    if provider == "qwen3_mlx":
        # MLX is Apple-Silicon-only. On Intel this is a hard "unavailable"
        # (no install button); on Apple Silicon the only blocker is the
        # package, which the user installs manually — we don't auto-pip it.
        if platform.machine() != "arm64":
            return False, "本机不支持(需 Apple Silicon)", False
        try:
            import mlx_audio  # noqa: F401
        except ImportError:
            return False, "未安装 mlx-audio 包", False
        return True, "", False
    if provider == "edge":
        return True, "", False  # free, no auth needed
    if provider == "baidu":
        ok = bool(settings.baidu_tts.api_key and settings.baidu_tts.secret_key)
        return ok, "" if ok else "需要百度 API Key", False
    if provider == "iflytek":
        ok = bool(settings.iflytek_tts.api_key and settings.iflytek_tts.api_secret)
        return ok, "" if ok else "需要讯飞 API Key", False
    if provider == "elevenlabs":
        ok = bool(settings.elevenlabs.api_key)
        return ok, "" if ok else "需要 ElevenLabs API Key", False
    if provider == "supertonic":
        try:
            import supertonic  # noqa: F401
            return True, "", False
        except ImportError:
            return False, "需安装 supertonic 包", True
    if provider == "kokoro":
        try:
            import onnxruntime  # noqa: F401
            from kokoro_onnx import Kokoro  # noqa: F401
        except ImportError:
            return False, "需安装 kokoro-onnx 并下载模型", True
        if _kokoro_model_ready():
            return True, "", False
        return False, "需下载模型", True
    return False, "未知 provider", False


def _is_configured(provider: str) -> bool:
    """Backward-compat shim; prefer _check_configured for the note."""
    return _check_configured(provider)[0]


# --- Install task registry (mirrors Converter's _jobs pattern) -------------
# In-memory, keyed by provider name. Cleared on process restart, which is
# acceptable: installs take minutes, not the hours a conversion can.
_install_jobs: dict[str, "InstallStatus"] = {}


def _install_state(provider: str) -> str:
    """Current install state for a provider, or 'idle'."""
    job = _install_jobs.get(provider)
    return job.state if job and job.state in ("installing",) else "idle"


@router.get("/providers")
async def list_providers():
    """List all TTS providers with configured status, notes, and install info."""
    providers = []
    for name, label in _PROVIDER_LABELS.items():
        configured, note, installable = _check_configured(name)
        providers.append(ProviderInfo(
            name=name,
            label=label,
            configured=configured,
            note=note,
            installable=installable,
            status=_install_state(name),
        ))
    return providers


# --- Provider install (model download / pip install) -----------------------

def _install_supertonic() -> None:
    """Install the supertonic package, then warm up its model (auto-download)."""
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "supertonic"],
    )
    from core.tts_provider.supertonic_tts import SupertonicTTSProvider
    SupertonicTTSProvider.warmup()


def _install_kokoro() -> None:
    """Install kokoro-onnx (if missing) then download model files."""
    try:
        import onnxruntime  # noqa: F401
        from kokoro_onnx import Kokoro  # noqa: F401
    except ImportError:
        from core.tts_provider.kokoro_tts import _install_kokoro_onnx
        _install_kokoro_onnx()
        import onnxruntime  # noqa: F401  (ensure sherpa-style deps present)
    from core.tts_provider.kokoro_tts import _ensure_model
    _ensure_model()


_INSTALLERS: dict[str, callable] = {
    "supertonic": _install_supertonic,
    "kokoro": _install_kokoro,
}


async def _run_install(provider: str) -> None:
    """Run a provider's installer in a worker thread, updating _install_jobs."""
    job = _install_jobs[provider]
    job.state = "installing"
    installer = _INSTALLERS[provider]
    try:
        await asyncio.to_thread(installer)
        job.state = "completed"
        job.message = "安装完成"
    except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
        job.state = "failed"
        job.error = str(exc)
        job.message = f"安装失败: {exc}"


@router.post("/install/{provider}")
async def start_install(provider: str):
    """Trigger a provider install (model download / pip install).

    Returns immediately with the install status; the frontend polls
    GET /install/{provider}/status until state is completed/failed.
    """
    if provider not in _INSTALLERS:
        raise HTTPException(400, f"Provider '{provider}' cannot be installed "
                                 f"via the UI. Installable: {list(_INSTALLERS)}")
    # supertonic needs onnxruntime, which has no wheel for py>=3.13.
    if provider == "supertonic" and sys.version_info >= (3, 13):
        raise HTTPException(400, "supertonic 需要 Python < 3.13(onnxruntime 无 3.13 wheel)")
    existing = _install_jobs.get(provider)
    if existing and existing.state == "installing":
        raise HTTPException(409, f"{provider} 已在安装中")
    # Already configured? Nothing to do.
    if _check_configured(provider)[0]:
        return InstallStatus(provider=provider, state="completed",
                             message="已就绪,无需安装")
    job = InstallStatus(provider=provider, state="pending", message="安装中…")
    _install_jobs[provider] = job
    asyncio.create_task(_run_install(provider))
    return job


@router.get("/install/{provider}/status")
async def install_status(provider: str):
    """Poll an install task's state."""
    job = _install_jobs.get(provider)
    if not job:
        # No install task recorded — reflect current configured state instead.
        configured = _check_configured(provider)[0]
        return InstallStatus(provider=provider,
                             state="completed" if configured else "idle")
    return job


@router.get("/languages")
async def list_languages(provider: str):
    """Get supported languages for a provider.

    Derived from the provider's registered voices (voices.get_languages) so a
    language is only listed when the provider actually has a voice for it —
    never showing a language the user can't then pick a voice for.
    """
    if provider not in _PROVIDER_MAP:
        raise HTTPException(400, f"Unknown provider: {provider}")
    from core.tts_provider.voices import get_languages
    return [
        LanguageItem(code=lang, name=_LANG_DISPLAY.get(lang, lang))
        for lang in get_languages(provider)
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
