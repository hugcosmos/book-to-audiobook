from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VoiceGender(str, Enum):
    MALE = "male"
    FEMALE = "female"


@dataclass(frozen=True)
class VoiceInfo:
    id: str  # provider-internal voice id
    name: str  # display name
    gender: VoiceGender
    language: str  # primary language code
    provider: str
    description: str = ""
    custom: bool = False


# --- Qwen3 TTS (9 speakers, all multilingual) ---
_QWEN3_VOICES = [
    VoiceInfo("vivian", "Vivian", VoiceGender.FEMALE, "multi", "qwen3_mlx", "明亮略带棱角的年轻女声"),
    VoiceInfo("serena", "Serena", VoiceGender.FEMALE, "multi", "qwen3_mlx", "温暖柔和的年轻女声"),
    VoiceInfo("uncle_fu", "Uncle Fu", VoiceGender.MALE, "multi", "qwen3_mlx", "沉稳低沉的男声"),
    VoiceInfo("dylan", "Dylan", VoiceGender.MALE, "multi", "qwen3_mlx", "北京口音年轻男声"),
    VoiceInfo("eric", "Eric", VoiceGender.MALE, "multi", "qwen3_mlx", "成都口音男声，略带沙哑"),
    VoiceInfo("ryan", "Ryan", VoiceGender.MALE, "multi", "qwen3_mlx", "Dynamic male, strong rhythm"),
    VoiceInfo("aiden", "Aiden", VoiceGender.MALE, "multi", "qwen3_mlx", "Sunny American male voice"),
    VoiceInfo("ono_anna", "Ono Anna", VoiceGender.FEMALE, "multi", "qwen3_mlx", "Playful Japanese female"),
    VoiceInfo("sohee", "Sohee", VoiceGender.FEMALE, "multi", "qwen3_mlx", "Warm Korean female"),
]

# --- Edge TTS (common subset) ---
_EDGE_VOICES = [
    VoiceInfo("zh-CN-XiaoxiaoNeural", "晓晓", VoiceGender.FEMALE, "zh-CN", "edge"),
    VoiceInfo("zh-CN-XiaoyiNeural", "晓伊", VoiceGender.FEMALE, "zh-CN", "edge"),
    VoiceInfo("zh-CN-YunxiNeural", "云希", VoiceGender.MALE, "zh-CN", "edge"),
    VoiceInfo("zh-CN-YunjianNeural", "云健", VoiceGender.MALE, "zh-CN", "edge"),
    VoiceInfo("zh-CN-YunyangNeural", "云扬", VoiceGender.MALE, "zh-CN", "edge", "新闻播报风格"),
    VoiceInfo("en-US-EmmaNeural", "Emma", VoiceGender.FEMALE, "en-US", "edge"),
    VoiceInfo("en-US-JennyNeural", "Jenny", VoiceGender.FEMALE, "en-US", "edge"),
    VoiceInfo("en-US-GuyNeural", "Guy", VoiceGender.MALE, "en-US", "edge"),
    VoiceInfo("en-US-ChristopherNeural", "Christopher", VoiceGender.MALE, "en-US", "edge"),
    VoiceInfo("ja-JP-NanamiNeural", "Nanami", VoiceGender.FEMALE, "ja-JP", "edge"),
    VoiceInfo("ja-JP-KeitaNeural", "Keita", VoiceGender.MALE, "ja-JP", "edge"),
    VoiceInfo("ko-KR-SunHiNeural", "SunHi", VoiceGender.FEMALE, "ko-KR", "edge"),
    VoiceInfo("ko-KR-InJoonNeural", "InJoon", VoiceGender.MALE, "ko-KR", "edge"),
    VoiceInfo("fr-FR-DeniseNeural", "Denise", VoiceGender.FEMALE, "fr-FR", "edge"),
    VoiceInfo("fr-FR-HenriNeural", "Henri", VoiceGender.MALE, "fr-FR", "edge"),
    VoiceInfo("de-DE-KatjaNeural", "Katja", VoiceGender.FEMALE, "de-DE", "edge"),
    VoiceInfo("de-DE-ConradNeural", "Conrad", VoiceGender.MALE, "de-DE", "edge"),
    VoiceInfo("es-ES-ElviraNeural", "Elvira", VoiceGender.FEMALE, "es-ES", "edge"),
    VoiceInfo("es-ES-AlvaroNeural", "Alvaro", VoiceGender.MALE, "es-ES", "edge"),
    VoiceInfo("ru-RU-SvetlanaNeural", "Svetlana", VoiceGender.FEMALE, "ru-RU", "edge"),
    VoiceInfo("ru-RU-DmitryNeural", "Dmitry", VoiceGender.MALE, "ru-RU", "edge"),
]

# --- Baidu TTS ---
_BAIDU_VOICES = [
    VoiceInfo("3", "度逍遥", VoiceGender.MALE, "zh", "baidu", "情感-磁性男声"),
    VoiceInfo("4", "度丫丫", VoiceGender.FEMALE, "zh", "baidu", "情感-甜美女声"),
    VoiceInfo("5", "度小娇", VoiceGender.FEMALE, "zh", "baidu", "精品女声"),
    VoiceInfo("103", "度米朵", VoiceGender.FEMALE, "zh", "baidu", "精品-温柔女声"),
    VoiceInfo("106", "度博文", VoiceGender.MALE, "zh", "baidu", "精品-磁性男声"),
    VoiceInfo("110", "度小童", VoiceGender.FEMALE, "zh", "baidu", "精品-童声"),
    VoiceInfo("111", "度小萌", VoiceGender.FEMALE, "zh", "baidu", "精品-活泼女声"),
    VoiceInfo("5003", "度逍遥", VoiceGender.MALE, "zh", "baidu", "专业版-磁性男声"),
    VoiceInfo("5118", "度小鹿", VoiceGender.FEMALE, "zh", "baidu", "专业版-温柔女声"),
]

# --- iFlytek TTS (free voices) ---
_IFLYTEK_VOICES = [
    VoiceInfo("x4_xiaoyan", "小燕", VoiceGender.FEMALE, "zh", "iflytek", "X4高品质女声"),
    VoiceInfo("x4_yezi", "小露", VoiceGender.FEMALE, "zh", "iflytek", "X4高品质女声"),
    VoiceInfo("aisjiuxu", "许久", VoiceGender.MALE, "zh", "iflytek", "亲和男声"),
    VoiceInfo("aisjinger", "小婧", VoiceGender.FEMALE, "zh", "iflytek", "柔美女声"),
    VoiceInfo("aisbabyxu", "许小宝", VoiceGender.FEMALE, "zh", "iflytek", "童声"),
]

# --- Supertonic (10 built-in voices, 31 languages) ---
_SUPERTONIC_VOICES = [
    VoiceInfo("M1", "M1 · Marcus", VoiceGender.MALE, "multi", "supertonic", "Warm, clear male"),
    VoiceInfo("M2", "M2 · James", VoiceGender.MALE, "multi", "supertonic", "Deep, resonant male"),
    VoiceInfo("M3", "M3 · Kai", VoiceGender.MALE, "multi", "supertonic", "Bright, energetic male"),
    VoiceInfo("M4", "M4 · Lucas", VoiceGender.MALE, "multi", "supertonic", "Smooth, narrator male"),
    VoiceInfo("M5", "M5 · Oscar", VoiceGender.MALE, "multi", "supertonic", "Soft, gentle male"),
    VoiceInfo("F1", "F1 · Clara", VoiceGender.FEMALE, "multi", "supertonic", "Bright, professional female"),
    VoiceInfo("F2", "F2 · Nova", VoiceGender.FEMALE, "multi", "supertonic", "Warm, friendly female"),
    VoiceInfo("F3", "F3 · Luna", VoiceGender.FEMALE, "multi", "supertonic", "Soft, calm female"),
    VoiceInfo("F4", "F4 · Iris", VoiceGender.FEMALE, "multi", "supertonic", "Clear, articulate female"),
    VoiceInfo("F5", "F5 · Sophie", VoiceGender.FEMALE, "multi", "supertonic", "Sweet, melodic female"),
]

# --- ElevenLabs (native premade voices, all multilingual via eleven_multilingual_v2) ---
_ELEVENLABS_VOICES = [
    VoiceInfo("pNInz6obpgDQGcFmaJgB", "Adam", VoiceGender.MALE, "multi", "elevenlabs", "Dominant, Firm · American"),
    VoiceInfo("hpp4J3VqNfWAUOO0d1Us", "Bella", VoiceGender.FEMALE, "multi", "elevenlabs", "Professional, Bright · American"),
    VoiceInfo("nPczCjzI2devNBz1zQrb", "Brian", VoiceGender.MALE, "multi", "elevenlabs", "Deep, Resonant · American"),
    VoiceInfo("onwK4e9ZLuTAKqWW03F9", "Daniel", VoiceGender.MALE, "multi", "elevenlabs", "Steady Broadcaster · British"),
    VoiceInfo("cjVigY5qzO86Huf0OWal", "Eric", VoiceGender.MALE, "multi", "elevenlabs", "Smooth, Trustworthy · American"),
    VoiceInfo("JBFqnCBsd6RMkjVDRZzb", "George", VoiceGender.MALE, "multi", "elevenlabs", "Warm Storyteller · British"),
    VoiceInfo("Xb7hH8MSUJpSbSDYk0k2", "Alice", VoiceGender.FEMALE, "multi", "elevenlabs", "Clear Educator · British"),
    VoiceInfo("pFZP5JQG7iQjIQuC4Bku", "Lily", VoiceGender.FEMALE, "multi", "elevenlabs", "Velvety Actress · British"),
    VoiceInfo("XrExE9yKIg1WjnnlVkGX", "Matilda", VoiceGender.FEMALE, "multi", "elevenlabs", "Professional · American"),
    VoiceInfo("pqHfZKP75CvOlQylNhV4", "Bill", VoiceGender.MALE, "multi", "elevenlabs", "Wise, Mature · American"),
    VoiceInfo("iP95p4xoKVk53GoZ742B", "Chris", VoiceGender.MALE, "multi", "elevenlabs", "Charming · American"),
    VoiceInfo("SAz9YHcvj6GT2YYXdXww", "River", VoiceGender.FEMALE, "multi", "elevenlabs", "Calm, Informative · American"),
]


# --- Kokoro TTS (kokoro-onnx, local CPU, v1.1-zh model) ---
# v1.1-zh ships 100 Chinese (z*) + 3 English (af_maple/af_sol American,
# bf_vale British) voices. We register a Chinese subset plus all 3 English
# voices so the model is usable for both languages offline.
_KOKORO_VOICES = [
    VoiceInfo("zf_003", "Kokoro 女声 003", VoiceGender.FEMALE, "zh", "kokoro"),
    VoiceInfo("zf_024", "Kokoro 女声 024", VoiceGender.FEMALE, "zh", "kokoro"),
    VoiceInfo("zf_038", "Kokoro 女声 038", VoiceGender.FEMALE, "zh", "kokoro"),
    VoiceInfo("zf_047", "Kokoro 女声 047", VoiceGender.FEMALE, "zh", "kokoro"),
    VoiceInfo("zf_048", "Kokoro 女声 048", VoiceGender.FEMALE, "zh", "kokoro"),
    VoiceInfo("zf_059", "Kokoro 女声 059", VoiceGender.FEMALE, "zh", "kokoro"),
    VoiceInfo("zm_011", "Kokoro 男声 011", VoiceGender.MALE, "zh", "kokoro"),
    VoiceInfo("zm_012", "Kokoro 男声 012", VoiceGender.MALE, "zh", "kokoro"),
    VoiceInfo("zm_029", "Kokoro 男声 029", VoiceGender.MALE, "zh", "kokoro"),
    VoiceInfo("zm_069", "Kokoro 男声 069", VoiceGender.MALE, "zh", "kokoro"),
    VoiceInfo("zm_089", "Kokoro 男声 089", VoiceGender.MALE, "zh", "kokoro"),
    VoiceInfo("zm_098", "Kokoro 男声 098", VoiceGender.MALE, "zh", "kokoro"),
    VoiceInfo("af_maple", "Maple", VoiceGender.FEMALE, "en-US", "kokoro", "American female"),
    VoiceInfo("af_sol", "Sol", VoiceGender.FEMALE, "en-US", "kokoro", "American female"),
    VoiceInfo("bf_vale", "Vale", VoiceGender.FEMALE, "en-GB", "kokoro", "British female"),
]


VOICE_REGISTRY: dict[str, list[VoiceInfo]] = {
    "qwen3_mlx": _QWEN3_VOICES,
    "edge": _EDGE_VOICES,
    "baidu": _BAIDU_VOICES,
    "iflytek": _IFLYTEK_VOICES,
    "elevenlabs": _ELEVENLABS_VOICES,
    "supertonic": _SUPERTONIC_VOICES,
    "kokoro": _KOKORO_VOICES,
}


def get_voices(provider: str, language: str | None = None) -> list[VoiceInfo]:
    """Get available voices for a provider, optionally filtered by language prefix."""
    voices = VOICE_REGISTRY.get(provider, [])
    if language:
        prefix = language.split("-")[0].lower()
        voices = [v for v in voices if v.language == "multi" or v.language.split("-")[0].lower() == prefix]
    return voices


def get_languages(provider: str) -> list[str]:
    """Languages a provider can actually serve — derived from registered voices.

    This is the source of truth for the language dropdown. A language appears
    only if the provider has a voice for it (a ``multi`` voice covers every
    language the provider declares in ``supported_languages``; a specific voice
    covers its own language). This guarantees the UI never offers a language
    with no selectable voice — the root cause of "unsupported language" bugs.
    """
    from importlib import import_module
    from core.tts_provider.tts_factory import _PROVIDER_MAP

    voices = VOICE_REGISTRY.get(provider, [])
    has_multi = any(v.language == "multi" for v in voices)
    # Specific languages covered by a non-multi voice.
    covered = {v.language for v in voices if v.language != "multi"}

    # Resolve the provider's declared languages to know what "multi" expands to.
    declared: list[str] = []
    if provider in _PROVIDER_MAP:
        mod_path, cls_name = _PROVIDER_MAP[provider]
        declared = getattr(import_module(mod_path), cls_name).supported_languages

    result: list[str] = []
    for lang in declared:
        prefix = lang.split("-")[0].lower()
        if lang in covered or prefix in {c.split("-")[0].lower() for c in covered}:
            result.append(lang)            # has a specific voice
        elif has_multi:
            result.append(lang)            # covered by a multi voice
    return result
