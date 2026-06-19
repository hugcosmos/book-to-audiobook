from __future__ import annotations

import re

from config.settings import settings


class TextProcessor:
    @staticmethod
    def detect_language(text: str) -> str:
        """Detect text language via character-ratio analysis.
        Returns BCP-47 code: zh-CN, ja-JP, ko-KR, ru-RU, or en-US.
        """
        sample = text[:2000]
        if not sample.strip():
            return "en-US"
        cjk = sum(1 for c in sample if '\u4e00' <= c <= '\u9fff')
        hira_kata = sum(1 for c in sample if '\u3040' <= c <= '\u30ff')
        hangul = sum(1 for c in sample if '\uac00' <= c <= '\ud7af')
        cyrillic = sum(1 for c in sample if '\u0400' <= c <= '\u04ff')
        total = len(sample) or 1
        if hira_kata / total > 0.05:
            return "ja-JP"
        if cjk / total > 0.1:
            return "zh-CN"
        if hangul / total > 0.1:
            return "ko-KR"
        if cyrillic / total > 0.1:
            return "ru-RU"
        return "en-US"

    @staticmethod
    def estimate_speech_duration(text: str) -> float:
        """Estimate speech duration, language-agnostic.
        CJK chars: ~4 chars/sec. Latin words: ~2.5 words/sec (150 wpm).
        Mixed text handled by counting each type separately.
        """
        if not text or not text.strip():
            return 0.0
        cjk_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af')
        non_cjk = ''.join(c for c in text if not ('\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff' or '\uac00' <= c <= '\ud7af'))
        words = len(non_cjk.split())
        return cjk_chars / 4.0 + words / 2.5

    @staticmethod
    def clean(text: str, remove_endnotes: bool = True) -> str:
        if not text:
            return ""
        # 1. Strip HTML tags (escaped entities first, then raw tags). EPUB
        #    extraction mostly uses get_text(), but TXT chapters or edited text
        #    may carry stray markup that TTS would otherwise read aloud.
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&[a-zA-Z]+;", " ", text)
        text = re.sub(r"<[^>]+>", "", text)
        # 2. Strip Markdown formatting so it isn't spoken verbatim.
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)          # images
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)       # links -> label
        text = re.sub(r"^#{1,6}\s*", "", text, flags=re.MULTILINE) # headings
        text = re.sub(r"`{1,3}", "", text)                         # inline/code fences
        text = re.sub(r"\*{1,2}|_{1,2}", "", text)                 # bold/italic markers
        text = re.sub(r"^[\s]*[-*+]\s+", "", text, flags=re.MULTILINE)  # list bullets
        text = re.sub(r"^[\s]*\d+\.\s+", "", text, flags=re.MULTILINE)  # numbered lists
        # 3. Strip bare URLs and emails (they read badly character-by-character).
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b", "", text)
        # 4. Normalize typographic punctuation to ASCII forms some engines handle
        #    more reliably, and replace NBSP.
        text = text.replace("\u00a0", " ")
        text = text.replace("\u201c", '"').replace("\u201d", '"')   # “ ”
        text = text.replace("\u2018", "'").replace("\u2019", "'")   # ‘ ’
        text = text.replace("\u2013", "-").replace("\u2014", "-")   # – —
        text = text.replace("\u2026", "...")                         # …
        # 5. Remove control characters (after the above so we don't clobber them).
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        # 6. Endnote/footnote markers. Strip short numeric references ([1], (12))
        #    that follow a word, but keep 4-digit values like years "(1990)".
        if remove_endnotes:
            text = re.sub(r"(?<=\w)\s*\[\d{1,3}\]", "", text)
            text = re.sub(r"(?<=\w)\s*\(\d{1,3}\)", "", text)
        return text

    @staticmethod
    def chunk(text: str, max_chars: int | None = None, language: str = "en") -> list[str]:
        max_chars = max_chars or settings.tts.chunk_max_chars
        if len(text) <= max_chars:
            return [text] if text.strip() else []
        chunks: list[str] = []
        sentences = TextProcessor._split_sentences(text, language)
        current = ""
        for sent in sentences:
            if len(sent) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(TextProcessor._split_long_sentence(sent, max_chars))
                continue
            if len(current) + len(sent) + 1 > max_chars:
                if current:
                    chunks.append(current)
                current = sent
            else:
                current = (current + " " + sent).strip() if current else sent
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _split_sentences(text: str, language: str) -> list[str]:
        try:
            from sentencex import segment
            sents = list(segment(language, text))
            return [s.strip() for s in sents if s.strip()]
        except Exception:
            return TextProcessor._fallback_split(text)

    @staticmethod
    def _fallback_split(text: str) -> list[str]:
        parts = re.split(r"(?<=[.!?。！？])\s+", text)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
        chunks: list[str] = []
        # Try splitting at commas, semicolons, colons
        delimiters = r"(?<=[,;:，；：])\s*"
        parts = re.split(delimiters, sentence)
        current = ""
        for part in parts:
            if len(current) + len(part) > max_chars:
                if current:
                    chunks.append(current)
                # Hard split if single part is too long
                while len(part) > max_chars:
                    chunks.append(part[:max_chars])
                    part = part[max_chars:]
                current = part
            else:
                current += part
        if current:
            chunks.append(current)
        return chunks
