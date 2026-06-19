from __future__ import annotations

from importlib import import_module

from config.settings import settings
from core.models import TTSConfig
from core.tts_provider.base_tts import BaseTTSProvider

_PROVIDER_MAP: dict[str, tuple[str, str]] = {
    "qwen3_mlx": ("core.tts_provider.qwen3_mlx_tts", "Qwen3MLXTTSProvider"),
    "edge": ("core.tts_provider.edge_tts", "EdgeTTSProvider"),
    "baidu": ("core.tts_provider.baidu_tts", "BaiduTTSProvider"),
    "iflytek": ("core.tts_provider.iflytek_tts", "IflytekTTSProvider"),
    "elevenlabs": ("core.tts_provider.elevenlabs_tts", "ElevenLabsTTSProvider"),
    "supertonic": ("core.tts_provider.supertonic_tts", "SupertonicTTSProvider"),
    "cosyvoice": ("core.tts_provider.cosyvoice_tts", "CosyVoiceTTSProvider"),
}


def get_tts_provider(provider: str | None = None, model_path: str | None = None, config: TTSConfig | None = None) -> BaseTTSProvider:
    if config is None:
        config = TTSConfig()
    name = provider or settings.tts.provider
    if name not in _PROVIDER_MAP:
        raise ValueError(
            f"Unknown TTS provider: {name}. Available: {list(_PROVIDER_MAP)}"
        )
    if model_path:
        config.model_path = model_path
    module_path, class_name = _PROVIDER_MAP[name]
    module = import_module(module_path)
    cls = getattr(module, class_name)
    cls.validate_config(config)
    return cls(config)
