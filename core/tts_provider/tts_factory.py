from __future__ import annotations

from core.models import TTSConfig
from core.tts_provider.base_tts import BaseTTSProvider
from core.tts_provider.edge_tts import EdgeTTSProvider


def get_tts_provider(config: TTSConfig | None = None) -> BaseTTSProvider:
    config = config or TTSConfig()
    return EdgeTTSProvider(config)
