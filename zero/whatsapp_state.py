"""Conversation state for the local WhatsApp agent, derived on every turn.

The state is rebuilt from the full history with the extractors the LosetasChile
flow already trusts, so it can never go stale and nothing is stored. It tells the
model what the customer asked for, what is already known and the one datum still
missing. Any extractor failure is logged and skipped: a state is a help, never a
reason to lose the reply.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Callable

from . import config
from .losetas_color import latest_color_preference, parse_color
from .losetas_polls import (PAVER_AREA_QUESTION, paver_order_details,
                            selected_category_from_history)
from .losetas_shipping import delivery_detail
from .pool_border import (BORDER_STRAIGHT_PATTERN, BORDER_WHALE_PATTERN,
                          POOL_PHOTO_REQUEST, border_plan,
                          normalize_pool_border_terms)
from .whatsapp_context import find_location, find_measurement

# A bare «ballena» or «recto» is a model name once the category is borders, which
# is how a customer corrects themselves («mejor ballena»). «rectangular» is not it.
_BARE_WHALE = re.compile(r"\bballena\b", re.IGNORECASE)
_BARE_STRAIGHT = re.compile(r"\brectos?\b", re.IGNORECASE)

_CATEGORY_LABELS = {"bordes": "borde de piscina", "pastelones": "pastelones"}


def _safe(label: str, extractor: Callable[[], Any]) -> Any:
    try:
        return extractor()
    except Exception:
        logging.warning("whatsapp_state: falló el extractor %s", label, exc_info=True)
        return None


def _clip(value: Any) -> str:
    return " ".join(str(value).split())[:config.WHATSAPP_STATE_EVIDENCE_CHARS]


def _border_facts(message: str, history: list[dict[str, Any]],
                  lead_texts: list[str]) -> dict[str, str]:
    facts: dict[str, str] = {}
    for text in reversed(lead_texts):  # newest first: a correction wins
        text = normalize_pool_border_terms(text)
        whale = [m.end() for pattern in (BORDER_WHALE_PATTERN, _BARE_WHALE)
                 for m in pattern.finditer(text)]
        straight = [m.end() for pattern in (BORDER_STRAIGHT_PATTERN, _BARE_STRAIGHT)
                    for m in pattern.finditer(text)]
        if whale or straight:  # the last one named in the message wins
            facts["modelo"] = ("ballena" if max(whale, default=-1) > max(straight, default=-1)
                               else "recto con nariz")
            break
    # Sizes are read with a straight model assumed, so a missing model or shape
    # does not hide measurements the customer already gave.
    sized, _ = border_plan(message, history + [{"role": "lead", "text": "rectangular, borde recto con nariz"}])
    if sized:
        facts["medidas"] = f"{sized['width']}x{sized['length']} m"
    plan, clarification = border_plan(message, history)
    if plan or facts.get("modelo") == "recto con nariz":
        facts["forma"] = "rectangular"  # the flow never asks it for straight borders
    elif clarification == POOL_PHOTO_REQUEST:
        facts["forma"] = "no rectangular"
    return facts


def _paver_facts(message: str, history: list[dict[str, Any]],
                 lead_texts: list[str]) -> dict[str, str]:
    details = paver_order_details(message, history)
    model, area = details.get("model"), details.get("area_m2")
    prompt = [{"role": "agent", "text": PAVER_AREA_QUESTION}]
    model_seen = area_seen = False
    for text in reversed(lead_texts):  # newest first: a correction wins
        found = paver_order_details("", prompt + [{"role": "lead", "text": text}])
        if found["model"] and not model_seen:
            model, model_seen = found["model"], True
        if (found["area_m2"] and not area_seen and
                not re.fullmatch(r"[\d.,\s]+", text.strip())):
            area, area_seen = found["area_m2"], True
    facts = {}
    if model:
        facts["modelo"] = model
    if area:
        facts["m2"] = f"{area} m2"
    return facts


def _category_start(turns: list[dict[str, Any]], category: str | None) -> int:
    """Index of the first turn after the last switch away from another category."""
    for end in range(len(turns) - 1, 0, -1):
        earlier = selected_category_from_history(turns[:end])
        if earlier and earlier != category:
            return end
    return 0


def _losetas_state(message: str, history: list[dict[str, Any]]) -> dict[str, Any] | None:
    all_turns = history + [{"role": "lead", "text": message}]
    category = _safe("categoría", lambda: selected_category_from_history(all_turns))
    # Only what the customer said since the last change of category still applies:
    # the color picked for borders is not the color of the pavers asked for later.
    start = _safe("alcance", lambda: _category_start(all_turns, category)) or 0
    turns = all_turns[start:]
    history = turns[:-1] if start else history
    lead_texts = [str(t.get("text") or "") for t in turns if t.get("role") == "lead"]
    known: dict[str, str] = {}
    extra = None
    if category == "bordes":
        extra = _safe("borde", lambda: _border_facts(message, history, lead_texts))
    elif category == "pastelones":
        extra = _safe("pastelones", lambda: _paver_facts(message, history, lead_texts))
    known.update(extra or {})

    def color() -> str | None:
        for text in reversed(lead_texts):
            preference = parse_color(text)
            if preference:
                return preference
        return latest_color_preference(turns)
    found_color = _safe("color", color)
    if found_color:
        known["color"] = found_color
    delivery = _safe("entrega", lambda: delivery_detail(message, history))
    if delivery:
        known["entrega"] = _clip(delivery)

    asked = _CATEGORY_LABELS.get(category)
    required = config.WHATSAPP_REQUIRED_FIELDS.get("losetaschile", {}).get(asked, ())
    missing = next((name for name in required if name not in known), None)
    if not asked and not known:
        return None
    return {"pidio": asked, "conocido": known, "falta": missing}


def _generic_state(message: str, history: list[dict[str, Any]]) -> dict[str, Any] | None:
    turns = history + [{"role": "lead", "text": message}]
    known: dict[str, str] = {}
    # Only measurements and places: a model name is specific to LosetasChile's
    # catalog, and quoting the whole message would carry instructions or phones.
    for index in range(len(turns) - 1, -1, -1):
        turn = turns[index]
        if turn.get("role") != "lead":
            continue
        text = str(turn.get("text") or "")
        previous = (str(turns[index - 1].get("text") or "")
                    if index > 0 and turns[index - 1].get("role") == "agent" else None)
        for key, find in (("medidas", lambda: find_measurement(text)),
                          ("ubicacion", lambda: find_location(text, previous))):
            found = None if key in known else _safe(key, find)
            if found:
                known[key] = f"cliente dijo: «{_clip(found.group(0))}»"
    return {"pidio": None, "conocido": known, "falta": None} if known else None


def build_conversation_state(client_id: str, message: str,
                             history: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """What the customer asked, what is known and what is missing; None if nothing."""
    history = history or []
    builder = _losetas_state if client_id == "losetaschile" else _generic_state
    try:
        return builder(message or "", history)
    except Exception:
        logging.warning("whatsapp_state: no se pudo armar el estado", exc_info=True)
        return None
