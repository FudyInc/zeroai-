"""Verified item quantities for LosetasChile rectangular pool borders.

The business rule was confirmed by its owner on 2026-10-07: straight 50 cm
borders cover the full perimeter and four corner pieces are added separately.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from .config import (LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE,
                     LOSETASCHILE_WHATSAPP_CATALOG_URL)


_COUNT = re.compile(r"\b(?:cu[aá]nt[oa]s|cantidad)\b", re.IGNORECASE)
_PIECES = re.compile(r"\b(?:pastelones?|bordes?|bordea|piezas?)\b", re.IGNORECASE)
_GENERIC_PASTELON_REQUEST = re.compile(
    r"\b(?:necesito|quiero|busco|me interesan)\b.{0,100}\bpastelones?\b",
    re.IGNORECASE,
)
_POOL_BORDER_REQUEST = re.compile(
    r"\b(?:necesito|quiero|busco|me interesan)\b.{0,100}"
    r"\bbordes?\s+(?:de|para)\s+(?:la|mi|una)?\s*piscina\b",
    re.IGNORECASE,
)
_MEASUREMENT_QUESTION_MARKER = "medidas de tu piscina"
_MEASUREMENT_QUESTION = (
    "¿Cuáles son las medidas de tu piscina? "
    "Necesito largo y ancho en metros (por ejemplo, 6 × 3 m)."
)
_MODEL_QUESTION = re.compile(
    r"\b(?:qu[eé]|cu[aá]les?)\s+(?:modelos?|tipos?)\b|"
    r"\b(?:modelos?|tipos?)\s+(?:hay|tienen|disponibles?)\b|"
    r"\b(?:qu[eé]|cu[aá]les?)\s+bordes?\b|"
    r"\b(?:tienen|hay)\s+(?:otros?\s+)?bordes?\b",
    re.IGNORECASE,
)
_CATALOG_REQUEST = re.compile(
    r"\b(?:tien(?:e|es|en)|hay)\s+(?:(?:un|el|alg[uú]n)\s+)?cat[aá]logos?\b|"
    r"\b(?:solo\s+)?(?:env[ií]a|manda|pasa|comparte|muestra)\s+"
    r"(?:el\s+)?cat[aá]logos?\b|"
    r"\bsolo\s+(?:el\s+)?cat[aá]logos?\b|"
    r"\b(?:env[ií]ame|m[aá]ndame|p[aá]same|comp[aá]rteme|mu[eé]strame|"
    r"me\s+(?:env[ií]as|mandas|pasas|compartes|muestras)|"
    r"me\s+(?:puedes|podr[ií]as?)\s+(?:mandar|enviar|pasar|compartir|mostrar)|"
    r"(?:puedes|podr[ií]as?)\s+(?:mandarme|enviarme|pasarme|compartirme|mostrarme)|"
    r"(?:quiero|quisiera|puedo|podr[ií]a)\s+(?:ver|recibir|revisar))"
    r"\b.{0,60}\b(?:(?:el|un)\s+)?cat[aá]logos?\b|"
    r"^\s*¿?\s*(?:el\s+)?cat[aá]logos?\s*(?:[?!.]|por\s+favor[.!]?)?\s*$",
    re.IGNORECASE,
)
_CATALOG_NEGATION = re.compile(
    r"\b(?:no|sin)\s+(?:(?:quiero|quisiera)\s+ver\s+|"
    r"me\s+(?:mandes|env[ií]es|pases|compartas)\s+|"
    r"(?:quiero|necesito)\s+)?(?:el\s+)?cat[aá]logos?\b"
    r"|\bno\s+(?:tienen|tiene|hay)\s+"
    r"(?:(?:un|el|alg[uú]n)\s+)?cat[aá]logos?\b",
    re.IGNORECASE,
)
_CATALOG_SEND_NEGATION = re.compile(
    r"\bno\s+me\s+(?:mandes|env[ií]es|pases|compartas)\s+"
    r"(?:(?:el|un)\s+)?(?:cat[aá]logos?|enlace|link|nada)\b|"
    r"\bcat[aá]logos?\b.{0,60}\b(?:pero\s+)?no\s+ahora\b|"
    r"\bcat[aá]logos?\b.{0,60}\b(?:pero\s+)?no\s+me\s+lo\s+"
    r"(?:mandes|env[ií]es|pases|compartas)\b|"
    r"\b(?:todav[ií]a|a[uú]n)\s+no\s+(?:lo\s+)?"
    r"(?:mandes|env[ií]es|pases|compartas)\b|"
    r"\bmejor\s+(?:despu[eé]s|m[aá]s\s+tarde)\b"
    r"|\bcat[aá]logos?\b.{0,80}\b(?:ma[nñ]ana|m[aá]s\s+tarde|despu[eé]s)\b"
    r"|\bno\s+me\s+lo\s+(?:manden|env[ií]en|pasen|compartan)\b",
    re.IGNORECASE,
)
_POOL_MEASUREMENTS = re.compile(
    r"\b(?:mi|la|nuestra|una)\s+piscina\b.{0,55}\b(?:mide|medidas?|tiene)\b"
    r"|\b(?:mide|medidas?)\b.{0,55}\bpiscina\b",
    re.IGNORECASE,
)
_SIZE = re.compile(
    r"\b(\d{1,3}(?:[.,]\d)?)\s*(?:m(?:etros?)?\s*)?"
    r"(?:x|×|por)\s*(\d{1,3}(?:[.,]\d)?)\s*(?:m(?:etros?)?)?\b",
    re.IGNORECASE,
)
_ITEM_SIZE_PREFIX = re.compile(
    r"\b(?:pastelones?|esquinas?|bordes?(?:\s+rectos?(?:\s+con\s+nariz)?)?)"
    r"\s+(?:de\s+)?$", re.IGNORECASE)
_REJECT_PASTELON = re.compile(
    r"\b(?:ya\s+)?no\s+(?:quiero|necesito|busco)\s+"
    r"(?:(?:los|unos?|algunos)\s+)?pastelones?\b", re.IGNORECASE)
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
_UNQUOTED_PIECE_COUNT = re.compile(
    r"\b(?:\d{1,4}|un(?:o|a|os|as)?|dos|tres|cuatro|cinco|seis|siete|"
    r"ocho|nueve|diez|once|doce|trece|catorce|quince|diecis[eé]is|"
    r"diecisiete|dieciocho|diecinueve|veinte|veinti\w+|treinta(?:\s+y\s+\w+)?|"
    r"cuarenta(?:\s+y\s+\w+)?|cincuenta|cien|ciento)\s+"
    r"(?:pastelones?|bordes?|esquinas?|piezas?|unidades?)\b",
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
    r"^\[location\](?:\s+https://www\.google\.com/maps\?q=[-\d.]+,[-\d.]+)?$"
    r"|^(?:mi direcci[oó]n es|la direcci[oó]n es|mi comuna es|estoy en|vivo en)\b",
    re.IGNORECASE,
)


def _one_edit_away(value: str, target: str) -> bool:
    """Recognize one dropped, added or substituted letter in a product word."""
    if abs(len(value) - len(target)) > 1:
        return False
    if len(value) == len(target):
        return sum(left != right for left, right in zip(value, target)) == 1
    shorter, longer = sorted((value, target), key=len)
    return any(shorter == longer[:skip] + longer[skip + 1:]
               for skip in range(len(longer)))


def normalize_pool_border_terms(message: str) -> str:
    """Correct a single typo in 'borde(s)' when the lead mentions a pool."""
    if not re.search(r"\bpiscinas?\b", message or "", re.IGNORECASE):
        return message or ""

    def correct(match: re.Match[str]) -> str:
        word = match.group()
        folded = word.casefold()
        if folded in {"borde", "bordes"}:
            return word
        if _one_edit_away(folded, "bordes") or _one_edit_away(folded, "borde"):
            return "bordes"
        return word

    return re.sub(r"\b[a-záéíóúñ]{4,8}\b", correct, message, flags=re.IGNORECASE)


def pool_border_models_reply(message: str, history: list[dict[str, Any]],
                             pricing: dict[str, Any]) -> str | None:
    """List current priced border models in a pool conversation, without quoting."""
    if catalog_requested(message):
        return LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE
    if (_CATALOG_NEGATION.search(message or "") or
            _CATALOG_SEND_NEGATION.search(message or "") or
            not _MODEL_QUESTION.search(message or "")):
        return None
    if re.search(r"\b(?:pastelones?|adoquines?|lajas?|ladrillos?|deck|dormientes?|"
                 r"pago|despacho|flete|env[ií]o)\b",
                 message, re.IGNORECASE):
        return None
    lead_text = " ".join(str(turn.get("text") or "") for turn in history
                         if turn.get("role") == "lead")
    context = normalize_pool_border_terms(f"{lead_text} {message}")
    if not re.search(r"\b(?:piscinas?|bordes?)\b", context, re.IGNORECASE):
        return ("Puedes ver nuestros modelos en el catálogo de WhatsApp: "
                f"{LOSETASCHILE_WHATSAPP_CATALOG_URL} ¿Qué producto buscas?")
    models = [str(item["name"]).strip() for item in pricing.get("items", [])
              if str(item.get("id") or "").startswith("borde-") and item.get("name")]
    if not models:
        return ("Puedes ver nuestros modelos en el catálogo de WhatsApp: "
                f"{LOSETASCHILE_WHATSAPP_CATALOG_URL} ¿Cuál te interesa?")
    corner = any(str(item.get("id") or "").startswith("esquina-piscina")
                 for item in pricing.get("items", []))
    return ("En la lista de precios figuran estos bordes: " + "; ".join(models) + "." +
            (" También figura la esquina para piscina." if corner else "") +
            f" Mira el catálogo de WhatsApp: {LOSETASCHILE_WHATSAPP_CATALOG_URL} "
            "¿Cuál modelo te interesa?")


def catalog_requested(message: str) -> bool:
    """Whether the lead explicitly asks to see the WhatsApp catalog."""
    return bool(_CATALOG_REQUEST.search(message or "") and
                not _CATALOG_NEGATION.search(message or "") and
                not _CATALOG_SEND_NEGATION.search(message or ""))


def visual_catalog_category(message: str) -> str | None:
    """Category requested explicitly for the LosetasChile photo catalog."""
    value = message or ""
    if not (catalog_requested(value) or re.search(
            r"^\s*¿?\s*(?:cat[aá]logo|cagalogo)\s+(?:de\s+)?"
            r"(?:bordes?|pastelones?)\s*[?!.]?\s*$", value,
            re.IGNORECASE)):
        return None
    if _CATALOG_NEGATION.search(value) or _CATALOG_SEND_NEGATION.search(value):
        return None
    borders = bool(re.search(r"\bbordes?\b", value, re.IGNORECASE))
    pavers = bool(re.search(r"\bpastelones?\b", value, re.IGNORECASE))
    if borders == pavers:
        return None
    return "bordes" if borders else "pastelones"


def pool_measurement_message(message: str) -> bool:
    """Recognize a pool size even when an earlier reply broke the question flow."""
    return bool(_POOL_MEASUREMENTS.search(message or "") and _SIZE.search(message or ""))


def delegates_piece_calculation(question: str, reply: str) -> bool:
    """Reject instructions to make the customer calculate a requested count."""
    return bool(_COUNT.search(question) and
                re.search(r"\b(?:piscina|bord\w*|pastel\w*|pieza\w*)\b", question,
                          re.IGNORECASE) and
                not re.search(r"\bc[oó]mo\b", question, re.IGNORECASE) and
                _CALCULATION_ADVICE.search(reply))


def unquoted_piece_count(reply: str, quote: dict[str, Any] | None) -> bool:
    """Keep model-generated quantities out of replies without a structured budget."""
    return bool(not quote and _UNQUOTED_PIECE_COUNT.search(reply or ""))


def measurement_followup(message: str, history: list[dict[str, Any]]) -> bool:
    """Continue a pool order when the lead answers the measurements question."""
    for turn in reversed(history):
        if turn.get("role") == "agent":
            return (_MEASUREMENT_QUESTION_MARKER in str(turn.get("text") or "").lower()
                    and bool(_SIZE.search(message)))
    return False


def border_plan(message: str, history: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """Return confirmed quantities or the one missing detail to ask for."""
    message = normalize_pool_border_terms(message)
    lead_texts = [normalize_pool_border_terms(str(turn.get("text") or "")) for turn in history
                  if turn.get("role") == "lead"]
    if re.search(r"\b(?:terraza|interior|fondo|piso)\b", message, re.IGNORECASE):
        return None, "¿Te refieres al borde recto con nariz de la piscina o a otro producto?"
    latest_first = [message, *reversed(lead_texts)]
    dimensions = None
    for text in latest_first:
        for match in _SIZE.finditer(text):
            if _ITEM_SIZE_PREFIX.search(text[max(0, match.start() - 35):match.start()]):
                continue
            if _OTHER_UNITS.search(text[match.end():match.end() + 18]):
                return None, "¿Las medidas de la piscina están en metros?"
            dimensions = tuple(Decimal(value.replace(",", "."))
                               for value in match.groups())
            break
        if dimensions is not None:
            break
    if dimensions is None and any(re.search(r"\bpiscina\b", text, re.IGNORECASE)
                                  for text in latest_first):
        return None, _MEASUREMENT_QUESTION
    if dimensions is not None and (min(dimensions) <= 0 or max(dimensions) > 50):
        return None, ("Las medidas indicadas necesitan confirmación. "
                      "¿Puedes confirmar el largo y ancho de tu piscina en metros?")
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
    if dimensions is None:
        return None, _MEASUREMENT_QUESTION
    width, length = dimensions
    if any((side * 2) % 1 for side in dimensions):
        return None, "Necesito confirmar los cortes antes de darte una cantidad."
    perimeter = 2 * (width + length)
    straight = int(perimeter * 2)
    return {"width": width, "length": length, "straight": straight, "corners": 4}, ""


def wants_border_budget(message: str) -> bool:
    """Use the structured budget for a confirmed pool-border order."""
    message = normalize_pool_border_terms(message)
    if _REJECT_PASTELON.search(message):
        return False
    if wants_product_quote(message) or (_COUNT.search(message) and _PIECES.search(message)):
        return True
    if (re.search(r"\b(?:no\s+(?:necesito|quiero|busco)|modelo|terraza|interior|fondo|piso)\b",
                  message, re.IGNORECASE) or
            _PRODUCT.search(message) or _OTHER_PRODUCT.search(message)):
        return False
    return bool(_GENERIC_PASTELON_REQUEST.search(message) or
                _POOL_BORDER_REQUEST.search(message))


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
    return ("📋 *Presupuesto de productos*\n"
            f"• Borde recto con nariz 50x50: {straight['qty']} × "
            f"{money(straight['unit_price'])} = {money(straight['subtotal'])}\n"
            f"• Esquina piscina 50x50: {corners['qty']} × "
            f"{money(corners['unit_price'])} = {money(corners['subtotal'])}\n"
            f"*Total productos: {money(quote['total'])}*\n"
            "Despacho: por cotizar.")
