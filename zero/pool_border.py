"""Verified item quantities for LosetasChile rectangular pool borders.

The business rule was confirmed by its owner on 2026-10-07: straight 50 cm
borders cover the full perimeter and four corner pieces are added separately.
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
_PRICE_REQUEST = re.compile(
    r"\b(?:precios?|presupuesto|cotiz\w*|total|valor|"
    r"cu[aá]nto\s+(?:sale\w*|cuesta\w*|vale\w*|ser[ií]a\w*))\b",
    re.IGNORECASE,
)
_SHIPPING_PRICE = re.compile(
    r"\b(?:precio|valor|costo|cu[aá]nto\s+(?:sale|cuesta|vale))\b"
    r".{0,35}\b(?:despacho|env[ií]o|flete)\b"
    r"|\b(?:despacho|env[ií]o|flete)\b.{0,35}"
    r"\b(?:precio|valor|costo|cu[aá]nto|sale|cuesta|vale)\b",
    re.IGNORECASE,
)
_DIRECT_SHIPPING_PRICE = re.compile(
    r"\b(?:precio|valor|costo|total)\s+(?:de(?:l| la)?\s+)?(?:despacho|env[ií]o|flete)\b"
    r"|\bcu[aá]nto\s+(?:sale|cuesta|vale)\s+(?:el|la)?\s*"
    r"(?:despacho|env[ií]o|flete)\b"
    r"|\bcotiz\w*\s+(?:el|la)?\s*(?:despacho|env[ií]o|flete)\b"
    r"|\b(?:despacho|env[ií]o|flete)\b\s*,?\s*"
    r"(?:cu[aá]nto\s+(?:sale|cuesta|vale)|qu[eé]\s+(?:precio|valor|costo))\b",
    re.IGNORECASE,
)
_OTHER_QUOTED_PRODUCT = re.compile(
    r"\b(?:adoqu[ií]n|deck|dormiente|laja|ladrillo|flor de lis|"
    r"pastel[oó]n|borde ballena|instalaci[oó]n)\b",
    re.IGNORECASE,
)
_ORDER_TOPIC = re.compile(r"\b(?:bordes?|esquinas?|productos?|pedido)\b", re.IGNORECASE)
_MIXED_SHIPPING_AND_PRODUCTS = re.compile(
    r"\b(?:despacho|env[ií]o|flete)\s+(?:y|,)\s+(?:(?:de(?:l| los| las)?|los|las|el|la)\s+)?"
    r"(?:bordes?|esquinas?|productos?|pedido)\b"
    r"|\b(?:bordes?|esquinas?|productos?|pedido)\s+(?:y|,)\s+"
    r"(?:de(?:l| la)?\s+)?(?:despacho|env[ií]o|flete)\b",
    re.IGNORECASE,
)
_WITHOUT_INSTALLATION = re.compile(r"\bsin\s+instalaci[oó]n\b", re.IGNORECASE)
_DELIVERY_DETAIL = re.compile(
    r"^\[location\]$|^(?:mi direcci[oó]n es|la direcci[oó]n es|mi comuna es|estoy en|vivo en)\b",
    re.IGNORECASE,
)


def delegates_piece_calculation(question: str, reply: str) -> bool:
    """Reject instructions to make the customer calculate a requested count."""
    return bool(_COUNT.search(question) and
                re.search(r"\b(?:piscina|bord\w*|pastel\w*|pieza\w*)\b", question,
                          re.IGNORECASE) and
                not re.search(r"\bc[oó]mo\b", question, re.IGNORECASE) and
                _CALCULATION_ADVICE.search(reply))


def border_plan(message: str, history: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """Return confirmed quantities or the one missing detail to ask for."""
    lead_texts = [str(turn.get("text") or "") for turn in history
                  if turn.get("role") == "lead"]
    if re.search(r"\b(?:terraza|interior|fondo|piso)\b", message, re.IGNORECASE):
        return None, "¿Te refieres al borde recto con nariz de la piscina o a otro producto?"
    latest_first = [message, *reversed(lead_texts)]
    product = next((text for text in latest_first if
                    _REJECT_PRODUCT.search(text) or _OTHER_PRODUCT.search(text) or
                    _PRODUCT.search(text)), None)
    if product and (_REJECT_PRODUCT.search(product) or _OTHER_PRODUCT.search(product)):
        return None, "¿Te refieres al borde recto con nariz de la piscina o a otro producto?"
    if product is None:
        return None, "¿Qué modelo de borde o pastelón quieres usar?"
    shape = next((text for text in latest_first if _OTHER_SHAPE.search(text) or
                  re.search(r"\bno\s+(?:es\s+)?rectangular\b", text, re.IGNORECASE) or
                  _RECTANGULAR.search(text)), None)
    if shape and (_OTHER_SHAPE.search(shape) or
                  re.search(r"\bno\s+(?:es\s+)?rectangular\b", shape, re.IGNORECASE)):
        return None, "Necesito revisar la forma de esa piscina antes de calcular las piezas."
    if shape is None:
        return None, "¿La piscina es rectangular?"
    dimensions = None
    for text in [message, *reversed(lead_texts)]:
        match = _SIZE.search(text)
        if match and _OTHER_UNITS.search(text):
            return None, "¿Las medidas de la piscina están en metros?"
        if match:
            dimensions = tuple(Decimal(value.replace(",", "."))
                               for value in match.groups())
            break
    if dimensions is None:
        return None, "¿Cuánto mide cada lado de la piscina rectangular?"
    width, length = dimensions
    if (min(dimensions) <= 0 or max(dimensions) > 50 or
            any((side * 2) % 1 for side in dimensions)):
        return None, "Necesito confirmar los cortes antes de darte una cantidad."
    perimeter = 2 * (width + length)
    straight = int(perimeter * 2)
    return {"width": width, "length": length, "straight": straight, "corners": 4}, ""


def border_count_reply(message: str, history: list[dict[str, Any]]) -> str | None:
    """Answer a rectangular pool piece-count question only from known inputs."""
    if not (_COUNT.search(message) and _PIECES.search(message)):
        return None
    plan, clarification = border_plan(message, history)
    if plan is None:
        return clarification
    return (f"Para tu piscina de {plan['width']:g} × {plan['length']:g} m: "
            f"{plan['straight']} bordes rectos de 50 cm más 4 esquinas.")


def wants_product_quote(message: str) -> bool:
    """A price request or a shared delivery detail can complete a known order."""
    if shipping_price_request(message) or _OTHER_QUOTED_PRODUCT.search(
            _WITHOUT_INSTALLATION.sub("", message)):
        return False
    return bool(_PRICE_REQUEST.search(message) or _DELIVERY_DETAIL.search(message.strip()))


def shipping_price_request(message: str) -> bool:
    """Shipping needs a separate human quote, even if an order is known."""
    if _MIXED_SHIPPING_AND_PRODUCTS.search(message):
        return False
    return bool(_DIRECT_SHIPPING_PRICE.search(message) or
                (_SHIPPING_PRICE.search(message) and not _ORDER_TOPIC.search(message)))


def format_product_quote(plan: dict[str, Any], quote: dict[str, Any]) -> str | None:
    """Present only the product subtotal; shipping has no verified price."""
    lines = {line["id"]: line for line in quote.get("lines", [])}
    straight = lines.get("borde-recto-nariz-50x50")
    corners = lines.get("esquina-piscina-50x50")
    if (quote.get("currency") != "CLP" or quote.get("iva_rate") != 0 or
            quote.get("unmatched") or not straight or not corners or
            straight["qty"] != plan["straight"] or corners["qty"] != plan["corners"]):
        return None
    money = lambda value: "$" + f"{round(value):,}".replace(",", ".")
    return (f"Para tu piscina de {plan['width']:g} × {plan['length']:g} m: "
            f"{straight['qty']} bordes × {money(straight['unit_price'])} = "
            f"{money(straight['subtotal'])}; "
            f"{corners['qty']} esquinas × {money(corners['unit_price'])} = "
            f"{money(corners['subtotal'])}. "
            f"Productos: {money(quote['total'])}. Despacho: por cotizar.")
