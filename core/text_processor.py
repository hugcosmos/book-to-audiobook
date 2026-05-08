from __future__ import annotations

import re

from config.settings import settings


class TextProcessor:
    @staticmethod
    def clean(text: str, remove_endnotes: bool = True) -> str:
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if remove_endnotes:
            text = re.sub(r"\[\d+\]", "", text)
            text = re.sub(r"\(\d+\)", "", text)
        return text

    @staticmethod
    def chunk(text: str, max_chars: int | None = None, language: str = "en") -> list[str]:
        max_chars = max_chars or settings.tts_chunk_max_chars
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
