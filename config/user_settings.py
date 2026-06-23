from __future__ import annotations

import json
from pathlib import Path

from config.settings import Settings, settings

_USER_SETTINGS_FILE = Path(__file__).parent / "user_settings.json"


def load_user_settings() -> None:
    """Load user_settings.json and patch in-memory settings."""
    if not _USER_SETTINGS_FILE.exists():
        return
    try:
        data = json.loads(_USER_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    _patch_settings(settings, data)
    merge_custom_voices()


def save_user_settings(data: dict) -> None:
    """Merge data into existing user settings and persist."""
    existing = get_user_settings_dict()
    existing.update(data)
    _USER_SETTINGS_FILE.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _patch_settings(settings, data)
    merge_custom_voices()


def get_user_settings_dict() -> dict:
    """Read persisted user settings as dict (or empty dict)."""
    if not _USER_SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(_USER_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _patch_settings(obj: Settings, data: dict) -> None:
    """Recursively patch settings attributes from dict."""
    for key, value in data.items():
        if not hasattr(obj, key):
            continue
        current = getattr(obj, key)
        if isinstance(value, dict) and hasattr(current, "__dict__"):
            _patch_settings(current, value)
        else:
            try:
                setattr(obj, key, type(current)(value))
            except (ValueError, TypeError):
                pass


def merge_custom_voices() -> None:
    """Merge custom voices from user_settings.json into VOICE_REGISTRY."""
    from core.tts_provider.voices import VoiceGender, VoiceInfo, VOICE_REGISTRY

    data = get_user_settings_dict()
    custom = data.get("custom_voices", {})
    hidden_map = data.get("hidden_voices", {})
    # Strip previously merged custom voices (those not in built-in lists)
    _rebuild_registry()
    # Filter hidden built-in voices
    for provider, hidden_ids in hidden_map.items():
        if provider in VOICE_REGISTRY:
            VOICE_REGISTRY[provider] = [
                v for v in VOICE_REGISTRY[provider] if v.id not in hidden_ids
            ]
    # Add custom voices
    for provider, voices in custom.items():
        if provider not in VOICE_REGISTRY:
            VOICE_REGISTRY[provider] = []
        for v in voices:
            VOICE_REGISTRY[provider].append(
                VoiceInfo(
                    id=v["id"],
                    name=v["name"],
                    gender=VoiceGender(v.get("gender", "female")),
                    language=v["language"],
                    provider=provider,
                    description=v.get("description", ""),
                    custom=True,
                )
            )
    # Add cloned voices (qwen3_mlx only)
    cloned = data.get("cloned_voices", [])
    for v in cloned:
        VOICE_REGISTRY.setdefault("qwen3_mlx", [])
        VOICE_REGISTRY["qwen3_mlx"].append(
            VoiceInfo(
                id=v["id"],
                name=v["name"],
                gender=VoiceGender(v.get("gender", "female")),
                language=v["language"],
                provider="qwen3_mlx",
                description=v.get("description", ""),
                custom=True,
            )
        )


def _rebuild_registry() -> None:
    """Rebuild VOICE_REGISTRY keeping only built-in voices."""
    from core.tts_provider.voices import (
        VOICE_REGISTRY, _QWEN3_VOICES, _EDGE_VOICES, _BAIDU_VOICES,
        _IFLYTEK_VOICES, _ELEVENLABS_VOICES, _SUPERTONIC_VOICES, _COSYVOICE_VOICES,
        _KOKORO_VOICES,
    )

    VOICE_REGISTRY["qwen3_mlx"] = list(_QWEN3_VOICES)
    VOICE_REGISTRY["edge"] = list(_EDGE_VOICES)
    VOICE_REGISTRY["baidu"] = list(_BAIDU_VOICES)
    VOICE_REGISTRY["iflytek"] = list(_IFLYTEK_VOICES)
    VOICE_REGISTRY["elevenlabs"] = list(_ELEVENLABS_VOICES)
    VOICE_REGISTRY["supertonic"] = list(_SUPERTONIC_VOICES)
    VOICE_REGISTRY["cosyvoice"] = list(_COSYVOICE_VOICES)
    VOICE_REGISTRY["kokoro"] = list(_KOKORO_VOICES)


def get_custom_voices(provider: str) -> list[dict]:
    """Return custom voice dicts for a provider."""
    data = get_user_settings_dict()
    return data.get("custom_voices", {}).get(provider, [])


def add_custom_voice(provider: str, voice: dict) -> None:
    """Add a custom voice and persist."""
    data = get_user_settings_dict()
    data.setdefault("custom_voices", {})
    data["custom_voices"].setdefault(provider, [])
    # Prevent duplicate id
    if any(v["id"] == voice["id"] for v in data["custom_voices"][provider]):
        raise ValueError(f"Voice id '{voice['id']}' already exists for {provider}")
    entry = {
        "id": voice["id"],
        "name": voice["name"],
        "language": voice["language"],
    }
    if voice.get("gender"):
        entry["gender"] = voice["gender"]
    if voice.get("description"):
        entry["description"] = voice["description"]
    data["custom_voices"][provider].append(entry)
    save_user_settings(data)


def delete_custom_voice(provider: str, voice_id: str) -> None:
    """Remove a custom voice by id and persist."""
    data = get_user_settings_dict()
    voices = data.get("custom_voices", {}).get(provider, [])
    data["custom_voices"][provider] = [v for v in voices if v["id"] != voice_id]
    save_user_settings(data)


def get_hidden_voices(provider: str) -> list[str]:
    """Return list of hidden voice ids for a provider."""
    data = get_user_settings_dict()
    return data.get("hidden_voices", {}).get(provider, [])


def hide_voice(provider: str, voice_id: str) -> None:
    """Hide a built-in voice."""
    data = get_user_settings_dict()
    data.setdefault("hidden_voices", {})
    hidden = data["hidden_voices"].setdefault(provider, [])
    if voice_id not in hidden:
        hidden.append(voice_id)
    save_user_settings(data)


def unhide_voice(provider: str, voice_id: str) -> None:
    """Unhide a built-in voice."""
    data = get_user_settings_dict()
    hidden = data.get("hidden_voices", {}).get(provider, [])
    if voice_id in hidden:
        hidden.remove(voice_id)
    data.setdefault("hidden_voices", {})
    data["hidden_voices"][provider] = hidden
    save_user_settings(data)


_CLONED_VOICES_DIR = Path(__file__).parent.parent / "uploads" / "voice_refs"


def get_cloned_voices() -> list[dict]:
    """Return cloned voice list from user settings."""
    data = get_user_settings_dict()
    return data.get("cloned_voices", [])


def add_cloned_voice(voice_id: str, name: str, language: str,
                     gender: str, description: str, ref_audio_path: str,
                     ref_text: str = "") -> None:
    """Add a cloned voice entry."""
    data = get_user_settings_dict()
    voices = data.get("cloned_voices", [])
    if any(v["id"] == voice_id for v in voices):
        raise ValueError(f"Cloned voice id '{voice_id}' already exists")
    voices.append({
        "id": voice_id,
        "name": name,
        "language": language,
        "gender": gender or "female",
        "description": description,
        "ref_audio": ref_audio_path,
        "ref_text": ref_text,
    })
    data["cloned_voices"] = voices
    save_user_settings(data)
    merge_custom_voices()


def delete_cloned_voice(voice_id: str) -> None:
    """Remove a cloned voice by id."""
    data = get_user_settings_dict()
    data["cloned_voices"] = [v for v in data.get("cloned_voices", []) if v["id"] != voice_id]
    save_user_settings(data)
    merge_custom_voices()


def get_cloned_voice_ref(voice_id: str) -> dict | None:
    """Get ref_audio and ref_text for a cloned voice."""
    for v in get_cloned_voices():
        if v["id"] == voice_id:
            return v
    return None
