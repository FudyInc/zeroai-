"""Poll definitions and answer parsing for the LosetasChile WhatsApp flow."""
from __future__ import annotations

import re
from typing import Any

from .losetas_text import closest, normalize_customer_text, plain


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


BORDER_MODEL_QUESTION = "¿Qué modelo de borde te interesó más?"
BORDER_MODEL_STRAIGHT = "Borde recto con nariz 50×50"
BORDER_MODEL_WHALE = "Borde ballena 50×40"
BORDER_MODEL_OPTIONS = (BORDER_MODEL_STRAIGHT, BORDER_MODEL_WHALE)

PAVER_AREA_QUESTION = "¿Cuántos m² necesitas cubrir con pastelones?"
PAVER_MODEL_QUESTION = "¿Qué pastelón del catálogo te interesó más?"
# Same models, same order as the PDF (whatsapp-web-bridge/catalog-document.js).
PAVER_MODEL_OPTIONS = ("Laja española", "Ladrillo cruzado", "Sol", "Sol rústico",
                       "Gregioriano", "Octagonal Piedra")

POOL_SHAPE_QUESTION = "¿La piscina es rectangular?"
POOL_SHAPE_OPTIONS = ("Sí, es rectangular", "No es rectangular")

CHOICE_PROMPTS = {
    "shape": (POOL_SHAPE_QUESTION, POOL_SHAPE_OPTIONS),
    "paver_model": (PAVER_MODEL_QUESTION, PAVER_MODEL_OPTIONS),
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


_plain = plain

_KEYCAPS = {"1️⃣": "1", "2️⃣": "2", "3️⃣": "3", "4️⃣": "4", "5️⃣": "5", "6️⃣": "6", "7️⃣": "7"}
_ORDINALS = {"uno": 1, "una": 1, "primero": 1, "primera": 1, "dos": 2, "segundo": 2,
             "segunda": 2, "tres": 3, "tercero": 3, "tercera": 3, "cuatro": 4, "cuarto": 4,
             "cuarta": 4, "cinco": 5, "quinto": 5, "quinta": 5, "seis": 6, "sexto": 6,
             "sexta": 6, "siete": 7, "septimo": 7, "septima": 7}
# Words around a menu answer that carry no choice of their own: «quiero el 2 porfa».
_FILLER = frozenset("el la lo opcion numero nro n quiero prefiero elijo escojo me "
                    "quedo con porfa por favor gracias ok oka okey ya esa ese esta este "
                    "de seria sera mejor va dale bueno a al te mando paso yo voy".split())
# Loose words that point to one option, per question («retiro», «el recto»).
_ALIASES = {
    "product": {"bordes": 0, "borde": 0, "piscina": 0, "pastelones": 1, "pastelon": 1},
    "delivery": {"retiro": 2, "retirar": 2, "retiramos": 2, "fabrica": 2, "buscar": 2,
                 "direccion": 1, "escribo": 1, "escribir": 1,
                 "ubicacion": 0, "despacho": 0, "domicilio": 0, "envio": 0, "enviar": 0,
                 "despachen": 0, "traigan": 0},
    "border_model": {"recto": 0, "nariz": 0, "ballena": 1},
    "paver_model": {"laja": 0, "espanola": 0, "ladrillo": 1, "cruzado": 1, "rustico": 3,
                    "gregoriano": 4, "gregioriano": 4, "octagonal": 5, "piedra": 5},
    "shape": {"si": 0, "s": 0, "sip": 0, "rectangular": 0, "correcto": 0,
              "redonda": 1, "ovalada": 1, "irregular": 1, "circular": 1},
}


# «¿hacen despacho a Rancagua?» names an option but asks about it.
_QUESTION = re.compile(r"\?|^\s*¿|\b(?:cu[aá]nto|cuesta|cu[aá]l|qu[eé]|c[oó]mo|d[oó]nde|"
                       r"hacen|tienen|hay|puedo|pueden|sirve|precio|valor)\b", re.IGNORECASE)
_NEGATION = frozenset({"no", "sin", "pero", "nunca", "ninguno", "ninguna", "tampoco"})
_UNSURE = re.compile(r"\b(?:no se|nose|ni idea|no estoy segur[oa]|los dos|las dos|"
                     r"ambos|ambas|todos|todas)\b")


def _menu_number(typed: str, size: int) -> int | None:
    """«2», «el 2», «quiero la dos»: one number and nothing else meaningful."""
    words = typed.split()
    numbers = [int(w) if w.isdigit() else _ORDINALS[w] for w in words
               if w.isdigit() or w in _ORDINALS]
    rest = [w for w in words if not (w.isdigit() or w in _ORDINALS) and w not in _FILLER]
    if len(numbers) == 1 and not rest and 1 <= numbers[0] <= size:
        return numbers[0]
    return None


def _option_from_words(key: str, typed: str, options) -> str | None:
    """An option named loosely: exact name, a distinctive word, or a near spelling."""
    core = [w for w in typed.split() if w not in _FILLER]
    text = " ".join(core)
    by_plain = {_plain(option): option for option in options}
    if text in by_plain:
        return by_plain[text]
    # A keyword only answers the list when it is (almost) the whole message:
    # «no me gusta el recto» or «si pero tiene forma de L» must not pick it.
    if len(core) > 2 or _NEGATION & set(core):
        return None
    aliases = _ALIASES.get(key, {})
    hits = set()
    for word in core:
        if word in aliases:
            hits.add(aliases[word])
        elif len(word) >= 5 and (near := closest(word, aliases, cutoff=0.85)):
            hits.add(aliases[near])  # «octogonal», «retiramo»
    # «sol rústico» names option 4, but «sol» alone is option 3.
    if key == "paver_model" and "sol" in core and not hits:
        hits = {2}
    if len(hits) == 1:
        return options[hits.pop()]
    if text and len(core) <= 3:
        near = closest(text, by_plain, cutoff=0.8)
        if near:
            return by_plain[near]
    return None


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
        for key, (question, options) in CHOICE_PROMPTS.items():
            if question.casefold() not in prompt:
                continue
            typed = _plain(normalize_customer_text(value))
            if len(typed.split()) > 8 or _QUESTION.search(value) or _UNSURE.search(typed):
                return None  # a question or a doubt, not an answer to the list
            if key == "shape" and typed in ("no", "nop", "no es", "nopo"):
                return options[1]
            number = _menu_number(typed, len(options))
            if number:
                return options[number - 1]
            return _option_from_words(key, typed, options)
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
        # «bordes para una piscina de 7 por 3,5» or a border model picked by name
        # is a border order too; missing them left factory pickup without a quote.
        if re.search(r"\bbordes?\s+(?:de|para)\s+(?:(?:la|una|mi)\s+)?piscinas?\b"
                     r"|\bbordes?\s+(?:rectos?|ballena)\b", choice):
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


_BARE_AREA = re.compile(r"(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:m|mts?|metros?)?\.?", re.IGNORECASE)


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
    following = turns[prompt_index + 1] if 0 <= prompt_index < len(turns) - 1 else {}
    if not area and following.get("role") == "lead":
        # «20» alone answers «¿Cuántos m²…?» only as the very next message: a
        # later «1» is a menu choice, not one square metre.
        found = _BARE_AREA.fullmatch(str(following.get("text") or "").strip())
        area = found if found and float(found.group(1).replace(",", ".")) > 0 else None
    return {"model": model, "area_m2": area.group(1).replace(",", ".") if area else None}


def is_factory_pickup(message: str) -> bool:
    return (message or "").strip() == DELIVERY_POLL_FACTORY_PICKUP
