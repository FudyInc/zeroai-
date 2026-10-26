"""Light touch formatting for short customer replies on WhatsApp."""
from __future__ import annotations

import hashlib
import re


_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[¿¡A-ZÁÉÍÓÚÑ])")
_URL_AT_END = re.compile(r"https?://\S+$", re.IGNORECASE)


def format_whatsapp_reply(reply: str) -> str:
    """Add readable spacing without rewriting facts or structured messages."""
    text = (reply or "").strip()
    if not text:
        return ""
    if "\n" in text:
        return text
    text = " ".join(text.split())
    if not _URL_AT_END.search(text) and text[-1].isalnum():
        text += "."
    if len(text) < 100:
        return text
    sentences = _SENTENCE_BREAK.split(text)
    if len(sentences) < 2:
        return text
    return "\n\n".join(sentences[:2] + ([" ".join(sentences[2:])] if len(sentences) > 2 else []))


_LIST_LINE = re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s", re.MULTILINE)


def _is_structured(paragraph: str) -> bool:
    low = paragraph.lower()
    return (any(c.isdigit() for c in paragraph) or "$" in paragraph
            or "http" in low or "www" in low or "\n" in paragraph.strip()
            or bool(_LIST_LINE.search(paragraph)))


def split_whatsapp_parts(text: str, max_parts: int, min_split_chars: int) -> list:
    """Split a reply into a few chat-sized messages without breaking structure.

    The first structured paragraph (quote, link, list, figures) and everything
    after it stay together as the final part. `"\\n\\n".join(parts)` rebuilds
    the text."""
    text = (text or "").strip()
    if len(text) < min_split_chars or max_parts < 2:
        return [text]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    parts: list = []
    for i, paragraph in enumerate(paragraphs):
        if _is_structured(paragraph):
            parts.append("\n\n".join(paragraphs[i:]))
            break
        parts.append(paragraph)
    if len(parts) > max_parts:
        parts = parts[:max_parts - 1] + ["\n\n".join(parts[max_parts - 1:])]
    return parts


def typing_ms(part: str, cfg: dict) -> int:
    """Typing time for one part, bounded by the delivery policy."""
    raw = len(part or "") * cfg["ms_per_char"]
    return max(cfg["min_typing_ms"], min(cfg["max_typing_ms"], raw))


def pick_variant(variants: tuple, key: str, last: str = "", **fields) -> str:
    """Stable choice among wording variants, never repeating the last agent turn.

    Hash of `key` picks the start; if that wording equals `last`, move on."""
    start = int(hashlib.sha1(str(key).encode("utf-8")).hexdigest(), 16) % len(variants)
    chosen = ""
    for step in range(len(variants)):
        chosen = variants[(start + step) % len(variants)]
        chosen = chosen.format(**fields) if fields else chosen
        if chosen.strip() != (last or "").strip():
            break
    return chosen
