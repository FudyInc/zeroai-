"""Poll definitions and answer parsing for the LosetasChile WhatsApp flow."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


PRODUCT_POLL_QUESTION = "¿Qué producto estás buscando?"
PRODUCT_POLL_BORDERS = "Bordes de piscina"
PRODUCT_POLL_PASTELONES = "Pastelones"
PRODUCT_POLL_OPTIONS = (PRODUCT_POLL_BORDERS, PRODUCT_POLL_PASTELONES)

COLOR_POLL_QUESTION = "¿Qué color prefieres?"
COLOR_POLL_OPTIONS = ("Anaranjado", "Blanco", "Rojo", "Crema", "Beige", "Gris", "Amarillo")

DELIVERY_POLL_QUESTION = "¿Cómo prefieres recibir tu pedido?"
DELIVERY_POLL_DELIVERY_LOCATION = "📍 Despacho · compartir ubicación"
DELIVERY_POLL_DELIVERY_ADDRESS = "✍️ Despacho · escribir dirección"
DELIVERY_POLL_FACTORY_PICKUP = "🏭 Retiro en fábrica"
DELIVERY_POLL_OPTIONS = (DELIVERY_POLL_DELIVERY_LOCATION, DELIVERY_POLL_DELIVERY_ADDRESS,
                         DELIVERY_POLL_FACTORY_PICKUP)

FACTORY_ADDRESS = "Los Granados 029, La Pintana"
# Same location PoolEdge shares with customers (docs/ficha-pooledge.md).
FACTORY_MAP_URL = "https://maps.app.goo.gl/yd4CKEr1bqi7RwsZA"


BORDER_MODEL_QUESTION = "¿Qué modelo de borde quieres?"
BORDER_MODEL_STRAIGHT = "Borde recto con nariz 50×50"
BORDER_MODEL_WHALE = "Borde ballena 50×40"
BORDER_MODEL_OPTIONS = (BORDER_MODEL_STRAIGHT, BORDER_MODEL_WHALE)

POOL_SHAPE_QUESTION = "¿La piscina es rectangular?"
POOL_SHAPE_OPTIONS = ("Sí, es rectangular", "No es rectangular")

CHOICE_PROMPTS = {
    "shape": (POOL_SHAPE_QUESTION, POOL_SHAPE_OPTIONS),
    "border_model": (BORDER_MODEL_QUESTION, BORDER_MODEL_OPTIONS),
    "product": (PRODUCT_POLL_QUESTION, PRODUCT_POLL_OPTIONS),
    "color": (COLOR_POLL_QUESTION, COLOR_POLL_OPTIONS),
    "delivery": (DELIVERY_POLL_QUESTION, DELIVERY_POLL_OPTIONS),
}
# Questions the WhatsApp Web bridge can send as a poll (poll-definitions.js).
WHATSAPP_WEB_POLL_KEYS = frozenset({"product", "color", "delivery"})
NUMBERED_HINT = "Responde con el número o el nombre."


def numbered_choices(key: str, reply: str = "") -> str:
    """The options as a numbered list; the question is added only if missing."""
    question, options = CHOICE_PROMPTS[key]
    lines = [] if question.casefold() in (reply or "").casefold() else [question]
    lines += [f"{number}. {option}" for number, option in enumerate(options, 1)]
    return "\n".join(lines + ["", NUMBERED_HINT])


def _plain(value: str) -> str:
    text = unicodedata.normalize("NFKD", (value or "").casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", text))


_KEYCAPS = {"1️⃣": "1", "2️⃣": "2", "3️⃣": "3", "4️⃣": "4", "5️⃣": "5", "6️⃣": "6", "7️⃣": "7"}


_YES_NO = {"si": 0, "s": 0, "rectangular": 0, "no": 1}


def canonical_choice(message: str, history: list[dict[str, Any]]) -> str | None:
    """Turn «2», «opción 2» or a typed option name into the exact option text.

    Only an answer to the latest agent prompt counts: a later agent message
    closes the question, as with poll votes.
    """
    value = (message or "").strip()
    for keycap, digit in _KEYCAPS.items():
        value = value.replace(keycap, digit)
    for turn in reversed(history):
        if turn.get("role") != "agent":
            continue
        prompt = str(turn.get("text") or "").casefold()
        for question, options in CHOICE_PROMPTS.values():
            if question.casefold() not in prompt:
                continue
            number = re.fullmatch(r"(?:(?:la\s+)?opci[oó]n\s+|n[uú]mero\s+)?(\d{1,2})\s*[.)]?",
                                  value, re.IGNORECASE)
            if number and 1 <= int(number.group(1)) <= len(options):
                return options[int(number.group(1)) - 1]
            typed = _plain(value)
            if options is POOL_SHAPE_OPTIONS and typed in _YES_NO:
                return options[_YES_NO[typed]]
            return next((option for option in options if typed and _plain(option) == typed), None)
        return None
    return None


def _previous_poll(message: str, history: list[dict[str, Any]]) -> str | None:
    choice = (message or "").strip()
    for turn in reversed(history):
        if turn.get("role") != "agent":
            continue
        prompt = str(turn.get("text") or "")
        for key, question, options in (("product", PRODUCT_POLL_QUESTION, PRODUCT_POLL_OPTIONS),
                                       ("color", COLOR_POLL_QUESTION, COLOR_POLL_OPTIONS),
                                       ("delivery", DELIVERY_POLL_QUESTION, DELIVERY_POLL_OPTIONS)):
            if question.casefold() in prompt.casefold():
                if any(choice.casefold() == option.casefold() for option in options):
                    return key
                return None
        return None
    return None


def category_for_poll_choice(message: str, history: list[dict[str, Any]]) -> str | None:
    """Return a PDF category only for a choice that answered our product poll."""
    if _previous_poll(message, history) != "product":
        return None
    choice = (message or "").strip().casefold()
    if choice == PRODUCT_POLL_BORDERS.casefold():
        return "bordes"
    if choice == PRODUCT_POLL_PASTELONES.casefold():
        return "pastelones"
    return None


def selected_category_from_history(history: list[dict[str, Any]]) -> str | None:
    """Find the latest category selected in text or through our product poll."""
    for index in range(len(history) - 1, -1, -1):
        turn = history[index]
        if turn.get("role") != "lead":
            continue
        choice = str(turn.get("text") or "").strip().casefold()
        if re.search(r"\bbordes?\s+(?:de|para)\s+(?:la\s+)?piscina\b", choice):
            return "bordes"
        if re.search(r"\bpastelones?\b", choice):
            return "pastelones"
        if choice not in {option.casefold() for option in PRODUCT_POLL_OPTIONS}:
            continue
        if any(previous.get("role") == "agent" and
               PRODUCT_POLL_QUESTION.casefold() in str(previous.get("text") or "").casefold()
               for previous in history[:index][-4:]):
            return "bordes" if choice == PRODUCT_POLL_BORDERS.casefold() else "pastelones"
    return None


_BARE_PRODUCT = re.compile(
    r"[\s¡]*(?:(?:quiero|busco|necesito|me\s+interesan?|cotizar)\s+)?"
    r"(?:(?:los|unos|el|un)\s+)?"
    r"(?:(?P<borders>bordes?(?:\s+(?:de|para)\s+(?:la\s+)?piscinas?|\s+piscinas?)?)|"
    r"(?P<pavers>pastel[oó]n(?:es)?))[\s!.,]*",
    re.IGNORECASE)


def direct_product_category(message: str) -> str | None:
    """Recognize a clear category request without interpreting catalog questions."""
    value = (message or "").strip()
    # The product name alone answers the product question even when the lead
    # types it instead of voting. Seen live (2026-10-15): «Bordes de piscina»
    # reached the model, and no PDF or color poll was sent. A question
    # («¿Pastelones?») is not a selection and keeps its own path.
    bare = _BARE_PRODUCT.fullmatch(value)
    if bare:
        return "bordes" if bare.group("borders") else "pastelones"
    if not re.search(r"\b(?:quiero|busco|necesito|me interesan|cotizar|presupuesto)\b",
                     value, re.IGNORECASE):
        return None
    borders = bool(re.search(r"\bbordes?\s+(?:de|para)\s+(?:la\s+)?piscina\b",
                             value, re.IGNORECASE))
    pavers = bool(re.search(r"\bpastelones?\b", value, re.IGNORECASE))
    return "bordes" if borders and not pavers else "pastelones" if pavers and not borders else None


def poll_answer_for_history(message: str, history: list[dict[str, Any]]) -> str | None:
    """Map a vote to its prompt; unknown/free-text answers remain untouched."""
    return _previous_poll(message, history)


_PAVER_AREA = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(?:m\s*(?:2|²)|mt2|metros?\s+cuadrados?)\b",
    re.IGNORECASE,
)
_PAVER_MODELS = (
    ("Laja española", re.compile(r"\blaja(?:\s+espa[nñ]ola)?\b", re.I)),
    ("Ladrillo cruzado", re.compile(r"\bladrillo\s+cruzado\b", re.I)),
    ("Sol rústico", re.compile(r"\bsol\s+r[uú]stico\b", re.I)),
    ("Sol", re.compile(r"\bsol\b", re.I)),
    ("Adoquín", re.compile(r"\badoqu[ií]n\b", re.I)),
    ("Gregioriano", re.compile(r"\bgregioriano\b", re.I)),
    ("Octagonal Piedra", re.compile(r"\boctagonal(?:\s+piedra)?\b", re.I)),
    ("40x40", re.compile(r"\b40\s*[x×]\s*40\b", re.I)),
    ("50x50", re.compile(r"\b50\s*[x×]\s*50\b", re.I)),
)


def paver_order_details(message: str, history: list[dict[str, Any]]) -> dict[str, str | None]:
    """Collect model and covered area only from answers after the paver prompt."""
    turns = list(history) + [{"role": "lead", "text": message}]
    prompt_index = -1
    for index in range(len(turns) - 1, -1, -1):
        turn = turns[index]
        prompt = str(turn.get("text") or "").casefold()
        if (turn.get("role") == "agent" and "cuántos m²" in prompt and
                "qué modelo" in prompt):
            prompt_index = index
            break
    if prompt_index < 0:
        for index in range(len(turns) - 1, -1, -1):
            turn = turns[index]
            if (turn.get("role") == "agent" and "cuántos m²" in
                    str(turn.get("text") or "").casefold()):
                prompt_index = index
                break
    candidate_text = " ".join(
        str(turn.get("text") or "") for turn in turns[prompt_index + 1:]
        if turn.get("role") == "lead") if prompt_index >= 0 else ""
    model = next((label for label, pattern in _PAVER_MODELS if pattern.search(candidate_text)), None)
    area = _PAVER_AREA.search(candidate_text)
    return {"model": model, "area_m2": area.group(1).replace(",", ".") if area else None}


def is_factory_pickup(message: str) -> bool:
    return (message or "").strip() == DELIVERY_POLL_FACTORY_PICKUP
