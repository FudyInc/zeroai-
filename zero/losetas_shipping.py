"""Verified shipping coverage reply for LosetasChile WhatsApp questions."""
from __future__ import annotations

import re


_SHIPPING_TOPIC = re.compile(
    r"\b(?:despach\w*|flete\w*|env[ií]o\w*|env[ií]an|enviamos|"
    r"entrega\w*)\b",
    re.IGNORECASE,
)

SHIPPING_COVERAGE_REPLY = (
    "Sí, hacemos despachos en Santiago y revisamos envíos a zonas cercanas "
    "a la Región Metropolitana. Para cotizar el flete, puedes escribir tu "
    "dirección o compartir tu ubicación actual desde 📎/+ → Ubicación. "
    "El equipo confirmará cobertura y valor."
)

_SHARED_LOCATION = re.compile(
    r"^\[location\]\s+(https://www\.google\.com/maps\?q=[-\d.]+,[-\d.]+)$",
    re.IGNORECASE,
)
_LOCATION_MARKER = re.compile(r"^\[location\](?:\s|$)", re.IGNORECASE)
_WRITTEN_ADDRESS = re.compile(
    r"^(?:mi direcci[oó]n es|la direcci[oó]n es|mi comuna es|"
    r"la comuna es|estoy en|vivo en)\s+(.+)$",
    re.IGNORECASE,
)
_DELIVERY_PROMPT = re.compile(r"\b(?:direcci[oó]n|ubicaci[oó]n|comuna|sector)\b", re.IGNORECASE)
_SHIPPING_PROMPT = re.compile(r"\b(?:despach\w*|flete\w*|env[ií]o\w*|cobertura)\b", re.IGNORECASE)
_NON_ADDRESS = {"hola", "gracias", "sí", "si", "no", "gris", "beige", "rojo",
                "blanco", "crema", "amarillo", "anaranjado"}


def shipping_coverage_request(message: str) -> bool:
    """Recognize delivery questions; shipping price gets its own answer first."""
    content = (message or "").strip()
    if _WRITTEN_ADDRESS.match(content):
        return False
    return bool(_SHIPPING_TOPIC.search(content))


def shipping_delivery_followup(message: str, history: list[dict]) -> bool:
    """Recognize a short destination sent after the agent asks for delivery details."""
    content = " ".join((message or "").split())
    if _LOCATION_MARKER.match(content) or _WRITTEN_ADDRESS.match(content):
        return True
    if not history or len(content) < 3 or len(content) > 200 or content.casefold() in _NON_ADDRESS:
        return False
    previous = history[-1]
    prompt = str(previous.get("text") or "") if previous.get("role") == "agent" else ""
    return bool(_DELIVERY_PROMPT.search(prompt) and _SHIPPING_PROMPT.search(prompt))


def delivery_detail(message: str, history: list[dict]) -> str | None:
    """Preserve a lead supplied map location or written address for review."""
    turns = list(history) + [{"role": "lead", "text": message}]
    for index in range(len(turns) - 1, -1, -1):
        turn = turns[index]
        if turn.get("role") != "lead":
            continue
        raw = str(turn.get("text") or "")
        content = " ".join(raw.split())
        found = _SHARED_LOCATION.match(content)
        if found:
            return f"Ubicación compartida: {found.group(1)}"
        found = _WRITTEN_ADDRESS.match(content)
        if found:
            return f"Dirección indicada: {found.group(1)[:200]}"
        if shipping_delivery_followup(content, turns[:index]):
            return f"Destino indicado: {content[:200]}"
    return None
