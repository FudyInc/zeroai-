"""Verified shipping coverage reply for LosetasChile WhatsApp questions."""
from __future__ import annotations

import re

from .losetas_polls import (DELIVERY_POLL_DELIVERY_ADDRESS,
                            DELIVERY_POLL_DELIVERY_LOCATION,
                            DELIVERY_POLL_FACTORY_PICKUP,
                            DELIVERY_POLL_QUESTION, FACTORY_ADDRESS, FACTORY_MAP_URL)


_SHIPPING_TOPIC = re.compile(
    r"\b(?:despach\w*|flete\w*|env[ií]o\w*|env[ií]an|enviamos|"
    r"entrega\w*)\b|\bllegan\s+(?:a|hasta)\s+\S+",
    re.IGNORECASE,
)

SHIPPING_COVERAGE_REPLY = (
    "Sí, hacemos despachos en Santiago y revisamos envíos a zonas cercanas "
    "a la Región Metropolitana. ¿Dónde sería la entrega? Puedes escribir "
    "tu dirección o compartir tu ubicación aquí; el equipo confirmará cobertura y valor."
)
SHIPPING_PRICE_REPLY = (
    "El despacho se cotiza por separado. ¿Dónde sería la entrega? "
    "Puedes escribir tu dirección o compartir tu ubicación aquí; "
    "el equipo verificará la ruta y el valor del flete."
)
DELIVERY_POLL_LOCATION = DELIVERY_POLL_DELIVERY_LOCATION
DELIVERY_POLL_ADDRESS = DELIVERY_POLL_DELIVERY_ADDRESS
DELIVERY_LOCATION_PROMPT = "Toca 📎 o + → Ubicación → Enviar ubicación actual para el despacho."
DELIVERY_ADDRESS_PROMPT = "Escríbeme calle, número y comuna de entrega."

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
_SHIPPING_PROMPT = re.compile(
    r"\b(?:despach\w*|flete\w*|env[ií]o\w*|cobertura|entrega)\b", re.IGNORECASE)
_NON_ADDRESS = {"hola", "gracias", "sí", "si", "no", "gris", "beige", "rojo",
                "blanco", "crema", "amarillo", "anaranjado", "ok", "listo", "perfecto"}
_OTHER_REQUEST = re.compile(
    r"[¿?]|\b(?:qu[eé]|cu[aá]l(?:es)?|c[oó]mo|cu[aá]nto|d[oó]nde|"
    r"modelos?|bordes?|pordes?|piscinas?|pastelones?|precios?|"
    r"tienen|hay|necesito|quiero|busco|cotiz\w*)\b",
    re.IGNORECASE,
)
_MIXED_PRODUCT_PROMPT = re.compile(
    r"\b(?:modelos?|medidas?|esquinas?|piezas?|bordes?|pastelones?)\b",
    re.IGNORECASE,
)


def shipping_coverage_request(message: str) -> bool:
    """Recognize delivery questions; shipping price gets its own answer first."""
    content = (message or "").strip()
    if _WRITTEN_ADDRESS.match(content):
        return False
    return bool(_SHIPPING_TOPIC.search(content))


def delivery_poll_choice_response(message: str) -> str | None:
    """One short instruction after a customer chooses a poll option."""
    choice = (message or "").strip()
    if choice == DELIVERY_POLL_LOCATION:
        return DELIVERY_LOCATION_PROMPT
    if choice == DELIVERY_POLL_ADDRESS:
        return DELIVERY_ADDRESS_PROMPT
    if choice == DELIVERY_POLL_FACTORY_PICKUP:
        pin = f"\nUbicación: {FACTORY_MAP_URL}" if FACTORY_MAP_URL else ""
        return f"El retiro es en {FACTORY_ADDRESS}.{pin}"
    return None


def shipping_delivery_followup(message: str, history: list[dict]) -> bool:
    """Recognize a short destination sent after the agent asks for delivery details."""
    content = " ".join((message or "").split())
    if content == DELIVERY_POLL_FACTORY_PICKUP:
        return True
    if _LOCATION_MARKER.match(content):
        return True
    if _WRITTEN_ADDRESS.match(content):
        return not _OTHER_REQUEST.search(content)
    content = content.strip(" ¿?")
    if (not history or len(content) < 3 or len(content) > 200 or
            content.casefold() in _NON_ADDRESS or _OTHER_REQUEST.search(content) or
            (len(content.split()) > 6 and not re.search(r"\d", content))):
        return False
    previous = history[-1]
    prompt = str(previous.get("text") or "") if previous.get("role") == "agent" else ""
    return bool(_DELIVERY_PROMPT.search(prompt) and _SHIPPING_PROMPT.search(prompt) and
                not _MIXED_PRODUCT_PROMPT.search(prompt))


def delivery_detail(message: str, history: list[dict]) -> str | None:
    """Preserve a lead supplied map location or written address for review."""
    turns = list(history) + [{"role": "lead", "text": message}]
    for index in range(len(turns) - 1, -1, -1):
        turn = turns[index]
        if turn.get("role") != "lead":
            continue
        raw = str(turn.get("text") or "")
        content = " ".join(raw.split())
        if content == DELIVERY_POLL_FACTORY_PICKUP:
            return f"Retiro en fábrica: {FACTORY_ADDRESS}"
        found = _SHARED_LOCATION.match(content)
        if found:
            return f"Ubicación compartida: {found.group(1)}"
        found = _WRITTEN_ADDRESS.match(content)
        if found and not _OTHER_REQUEST.search(content):
            return f"Dirección indicada: {found.group(1)[:200]}"
        if shipping_delivery_followup(content, turns[:index]):
            return f"Destino indicado: {content[:200]}"
    return None
