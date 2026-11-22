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


_BARE_GREETING = re.compile(
    r"^[¡\s]*(?:hola|buen[oa]s\s+(?:d[ií]as|tardes|noches)|perfecto|muy bien|listo|gracias|"
    r"disculpe la demora)[\s,.!]*$", re.IGNORECASE)


def agent_bubbles(text: str, max_parts: int = 3) -> list:
    """Burbujas ordenadas para el agente de PoolEdge (Diego, 2026-11-21: «ordenaditos»).

    1) el saludo junto con la respuesta, 2) la información (opciones, horario,
    ubicación), 3) la pregunta que sigue con sus opciones. Nunca un «Buenas
    noches.» solo ni una frase suelta. `"\n\n".join(...)` no siempre rehace el
    texto: el saludo se une a la línea siguiente con un salto simple.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", (text or "").strip()) if p.strip()]
    if len(paragraphs) <= 1:
        return paragraphs or [""]
    if _BARE_GREETING.match(paragraphs[0]):
        paragraphs = [paragraphs[0] + "\n" + paragraphs[1]] + paragraphs[2:]
    asks = [i for i, p in enumerate(paragraphs) if p.rstrip().endswith("?")]
    if asks == [0]:
        return ["\n\n".join(paragraphs)]  # una pregunta con sus opciones: una sola burbuja
    tail_at = asks[-1] if asks and asks[-1] > 0 else len(paragraphs)
    head, middle, tail = paragraphs[:1], paragraphs[1:tail_at], paragraphs[tail_at:]
    parts = head + (["\n\n".join(middle)] if middle else []) + (["\n\n".join(tail)] if tail else [])
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
