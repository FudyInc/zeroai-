"""Light touch formatting for short customer replies on WhatsApp."""
from __future__ import annotations

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
