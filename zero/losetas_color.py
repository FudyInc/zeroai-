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
    # Availability is not confirmed per color: the review group confirms it.
    return ("Te comparto la gama de colores para los bordes y pastelones: "
            "anaranjado, blanco, rojo, crema, beige, gris y amarillo. "
            f"{COLOR_POLL_QUESTION}")


# «¿Qué colores tienen?» se responde con la imagen de la gama, nunca con texto del
# modelo: Sonnet 5.5 contestó «no tengo confirmados los colores» en la prueba del
# 2026-11-11, con la gama ya definida por Diego.
_COLORS_ASKED = re.compile(
    r"\b(?:qu[eé]|cu[aá]l(?:es)?|cu[aá]nt[oa]s|tienen|hay|vienen|otros?|m[aá]s|"
    r"opciones|gama|ver|muestr\w*|disponibles?)\b[^.?!\n]{0,30}\bcolou?r(?:es)?\b"
    r"|\bcolou?r(?:es)?\b[^.?!\n]{0,25}\b(?:tienen|hay|vienen|disponibles?|manejan)\b"
    r"|^\s*(?:y\s+)?(?:los\s+|en\s+)?colou?r(?:es)?\s*\?+\s*$",
    re.IGNORECASE,
)
# Otra consulta en el mismo mensaje (precio, medidas, despacho, duración del color)
# no se tapa con la gama: sigue el flujo normal.
_COLORS_OTHER_TOPIC = re.compile(
    r"\d|\b(?:cu[aá]nto|precio|valor|cuesta|cobran|presupuesto|despach\w*|env[ií]\w*|"
    r"medidas?|metros?|desti[ñn]\w*|decolor\w*|pint\w*|dura\w*|garant[ií]a|stock)\b",
    re.IGNORECASE,
)

_QUESTION_START = re.compile(
    r"\s*(?:y\s+)?(?:qu[eé]|cu[aá]l|cu[aá]nt|hay|tienen|vienen|en\s+qu[eé]|"
    r"me\s+muestr|mu[eé]str|(?:los\s+)?colou?res\s+que)",
    re.IGNORECASE,
)


def asks_for_colors(message: str) -> bool:
    """El cliente pregunta qué colores hay, sin otra consulta en el mismo mensaje."""
    text = " ".join(str(message or "").split())
    if not text or len(text) > 120 or _COLORS_OTHER_TOPIC.search(text):
        return False
    # «mejor con otro color» cambia un pedido; no pregunta por la gama.
    if "?" not in text and not _QUESTION_START.match(text):
        return False
    return bool(_COLORS_ASKED.search(text))


def color_range_reply() -> str:
    """Pie de la imagen de la gama. No afirma stock: lo confirma el equipo."""
    return ("Te comparto la gama de colores para los bordes y pastelones: "
            "anaranjado, blanco, rojo, crema, beige, gris y amarillo.")


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


def names_color(message: str) -> str | None:
    """A color the lead wrote, whether or not the color question was asked yet."""
    return _parse_preference(message)


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
