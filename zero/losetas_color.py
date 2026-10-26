"""Ask for a LosetasChile pool-border tone using the owner's labeled image."""
from __future__ import annotations

import re
from typing import Any

from .losetas_polls import COLOR_POLL_QUESTION


COLOR_CATALOG_IMAGE_PATH = "catalog/losetaschile/gama-bordes-piscina.jpeg"
COLOR_CATALOG_IMAGE_URL = (
    "https://zeroai-six.vercel.app/" + COLOR_CATALOG_IMAGE_PATH
)

COLOR_NAMES = ("anaranjado", "blanco", "rojo", "crema", "beige", "gris", "amarillo")
_QUESTION_MARKER = "gama de colores para los bordes"
_COLOR_RE = re.compile(r"\b(?:anaranjado|blanco|rojo|crema|beige|gris|amarillo)\b",
                       re.IGNORECASE)
_REJECT = re.compile(
    r"\b(?:no s[eé]|no tengo|no quiero|cu[aá]nto|precio|presupuesto|"
    r"despacho|medidas?|metros?)\b",
    re.IGNORECASE,
)


def color_question() -> str:
    """Caption for the supplied image, without claiming stock availability."""
    return ("Te comparto la gama de colores disponible para bordes y pastelones: "
            "anaranjado, blanco, rojo, crema, beige, gris y amarillo. "
            f"{COLOR_POLL_QUESTION}")


def _is_color_question(text: str) -> bool:
    value = (text or "").casefold()
    return _QUESTION_MARKER in value or COLOR_POLL_QUESTION.casefold() in value


def _parse_preference(message: str) -> str | None:
    text = " ".join(str(message or "").strip().split())
    if not text or len(text) > 80:
        return None
    if _REJECT.search(text) or re.search(r"\d", text):
        return None
    colors = {match.group(0).lower() for match in _COLOR_RE.finditer(text)}
    if len(colors) == 1 and len(text.split()) <= 10:
        return next(iter(colors))
    return None


def color_preference(message: str, history: list[dict[str, Any]]) -> str | None:
    """Read a lead's answer only after the catalog question was sent.

    A later agent message closes the question, preventing an unrelated color
    mention much later in the conversation from being treated as its answer.
    """
    for turn in reversed(history):
        if turn.get("role") == "agent":
            return _parse_preference(message) if _is_color_question(
                str(turn.get("text") or "")) else None
    return None


def latest_color_preference(history: list[dict[str, Any]]) -> str | None:
    """Return the most recent recognized answer recorded after a color question."""
    for index in range(len(history) - 1, -1, -1):
        turn = history[index]
        if turn.get("role") != "agent" or not _is_color_question(
                str(turn.get("text") or "")):
            continue
        for answer in history[index + 1:]:
            if answer.get("role") == "agent":
                break
            if answer.get("role") == "lead":
                preference = _parse_preference(str(answer.get("text") or ""))
                if preference:
                    return preference
        return None  # A newer unanswered question supersedes an older choice.
    # No color question yet: a bare «gris» typed earlier (to the model question,
    # say) is still the customer's color, and asking it again looks deaf.
    for turn in reversed(history):
        text = str(turn.get("text") or "")
        if turn.get("role") == "lead" and len(text.split()) <= 3:
            preference = _parse_preference(text)
            if preference:
                return preference
    return None
