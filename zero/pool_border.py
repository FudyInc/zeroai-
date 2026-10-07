"""Verified piece count for LosetasChile rectangular pool borders.

This is a quantity estimate, not a price quote. The business rule was
confirmed by its owner on 2026-10-07: straight 50 cm borders cover the full
perimeter and four corner pieces are added separately.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any


_COUNT = re.compile(r"\b(?:cu[aá]nt[oa]s|cantidad)\b", re.IGNORECASE)
_PIECES = re.compile(r"\b(?:pastelones?|bordes?|bordea|piezas?)\b", re.IGNORECASE)
_SIZE = re.compile(
    r"\b(\d{1,2}(?:[.,]\d)?)\s*(?:m(?:etros?)?\s*)?"
    r"(?:x|×|por)\s*(\d{1,2}(?:[.,]\d)?)\s*(?:m(?:etros?)?)?\b",
    re.IGNORECASE,
)
_PRODUCT = re.compile(r"\bbordes? rectos?(?: con nariz)?\b", re.IGNORECASE)
_OTHER_PRODUCT = re.compile(
    r"\bbordes? ballena\b|\bpastel[oó]n(?:es)?\s+(?:sol|adoqu[ií]n|laja|ladrillo)\b"
    r"|\b40\s*[x×]\s*40\b", re.IGNORECASE)
_REJECT_PRODUCT = re.compile(
    r"\b(?:ya\s+)?no\s+(?:quiero|necesito|uso|usar[eé]|me interesa)\b"
    r".{0,50}\bbordes? rectos?\b",
    re.IGNORECASE)
_RECTANGULAR = re.compile(r"\brectangular?\b|\brect[aá]ngulo\b", re.IGNORECASE)
_OTHER_SHAPE = re.compile(r"\b(?:ovalad[ao]|circular|redond[ao]|irregular)\b", re.IGNORECASE)
_OTHER_UNITS = re.compile(
    r"\b(?:cm|cent[ií]metros?|pies?|ft|pulgadas?|inches|yardas?|yd)\b",
    re.IGNORECASE,
)
_CALCULATION_ADVICE = re.compile(
    r"\bpara calcular\b.{0,90}\b(?:divide|dividir|multiplica|suma|per[ií]metro)\b"
    r"|\b(?:divide|divid[ae]|calcula|calcul[ae])\b.{0,90}"
    r"\b(?:per[ií]metro|metros lineales|largo del borde)\b",
    re.IGNORECASE,
)


def delegates_piece_calculation(question: str, reply: str) -> bool:
    """Reject instructions to make the customer calculate a requested count."""
    return bool(_COUNT.search(question) and
                re.search(r"\b(?:piscina|bord\w*|pastel\w*|pieza\w*)\b", question,
                          re.IGNORECASE) and
                not re.search(r"\bc[oó]mo\b", question, re.IGNORECASE) and
                _CALCULATION_ADVICE.search(reply))


def border_count_reply(message: str, history: list[dict[str, Any]]) -> str | None:
    """Answer a rectangular pool piece-count question only from known inputs."""
    if not (_COUNT.search(message) and _PIECES.search(message)):
        return None
    lead_texts = [str(turn.get("text") or "") for turn in history
                  if turn.get("role") == "lead"]
    if re.search(r"\b(?:terraza|interior|fondo|piso)\b", message, re.IGNORECASE):
        return "¿Te refieres al borde recto con nariz de la piscina o a otro producto?"
    latest_first = [message, *reversed(lead_texts)]
    product = next((text for text in latest_first if
                    _REJECT_PRODUCT.search(text) or _OTHER_PRODUCT.search(text) or
                    _PRODUCT.search(text)), None)
    if product and (_REJECT_PRODUCT.search(product) or _OTHER_PRODUCT.search(product)):
        return "¿Te refieres al borde recto con nariz de la piscina o a otro producto?"
    if product is None:
        return ("¿Qué modelo de borde o pastelón quieres usar? Con ese dato "
                "puedo calcular las piezas para el perímetro.")
    shape = next((text for text in latest_first if _OTHER_SHAPE.search(text) or
                  re.search(r"\bno\s+(?:es\s+)?rectangular\b", text, re.IGNORECASE) or
                  _RECTANGULAR.search(text)), None)
    if shape and (_OTHER_SHAPE.search(shape) or
                  re.search(r"\bno\s+(?:es\s+)?rectangular\b", shape, re.IGNORECASE)):
        return "Esa fórmula es solo para piscinas rectangulares; necesito revisar la forma."
    if shape is None:
        return "¿La piscina es rectangular? Así calculo el perímetro correctamente."
    dimensions = None
    for text in [message, *reversed(lead_texts)]:
        match = _SIZE.search(text)
        if match and _OTHER_UNITS.search(text):
            return "¿Las medidas de la piscina están en metros?"
        if match:
            dimensions = tuple(Decimal(value.replace(",", "."))
                               for value in match.groups())
            break
    if dimensions is None:
        return "¿Cuánto mide cada lado de la piscina rectangular?"
    width, length = dimensions
    if (min(dimensions) <= 0 or max(dimensions) > 50 or
            any((side * 2) % 1 for side in dimensions)):
        return ("Para esa medida necesito confirmar cómo se resolverán los cortes "
                "antes de darte una cantidad de piezas.")
    perimeter = 2 * (width + length)
    straight = int(perimeter * 2)
    return (f"Para tu piscina de {width:g} × {length:g} m: "
            f"{straight} bordes rectos de 50 cm más 4 esquinas.")
