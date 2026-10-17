"""Tolerance for how LosetasChile customers really write on WhatsApp.

Customers misspell («pisina», «pasteloness», «amarrillo»), answer a menu with
words («el uno», «quiero el 2», «retiro») and give sizes loosely («6mts x
3mts», «seis por tres», «6 de largo y 3 de ancho»). These helpers turn that
into the exact text the deterministic flow already understands, so a typo
does not send the chat to the language model or to a person.

Only domain words are corrected: a token is replaced when it is close to one
word of the vocabulary below and is not itself a real word of that list.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# Words the flow keys on, written as the flow expects them.
_VOCABULARY = ("piscina", "bordes", "borde", "pastelones", "pastelón", "catálogo",
               "despacho", "retiro", "fábrica", "medidas", "rectangular", "colores",
               "anaranjado", "blanco", "rojo", "crema", "beige", "gris", "amarillo",
               "ballena", "nariz", "recto", "dirección", "ubicación")
_PLAIN_VOCABULARY = {}


def plain(value: str) -> str:
    """Lowercase, no accents, words and digits only."""
    text = unicodedata.normalize("NFKD", (value or "").casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", text))


for _word in _VOCABULARY:
    _PLAIN_VOCABULARY.setdefault(plain(_word), _word)

# Spellings too far from the word for a generic distance, seen or likely in chats.
_ALIASES = {"pisina": "piscina", "picina": "piscina", "pissina": "piscina",
            "pasteon": "pastelón", "pasteones": "pastelones", "pastelo": "pastelón",
            "bage": "beige", "beich": "beige", "beish": "beige", "beis": "beige",
            "naranjo": "anaranjado", "naranja": "anaranjado", "anaranjao": "anaranjado",
            "catalogo": "catálogo", "catalgo": "catálogo", "blanko": "blanco",
            "bordez": "bordes", "bordesde": "bordes de", "amarilo": "amarillo",
            "amarrilo": "amarillo"}


def closest(word: str, candidates, cutoff: float = 0.82) -> str | None:
    """The single candidate closest to `word`, or None if none is close enough."""
    found = difflib.get_close_matches(word, list(candidates), n=2, cutoff=cutoff)
    if not found:
        return None
    if len(found) > 1 and (difflib.SequenceMatcher(None, word, found[0]).ratio() -
                           difflib.SequenceMatcher(None, word, found[1]).ratio()) < 0.05:
        return None  # two words equally close: do not guess
    return found[0]


# Real Spanish words that sit close to the vocabulary and must stay as written
# («Los Grises», «pastel», «retira»): a typo fix must never change a real word.
_REAL_WORDS = frozenset(
    "grises cremas crema blanca blancas blancos rojas rojos amarillas amarillos beiges "
    "pastel pasteles pastelitos pastelito bordo borda bordas retira retire retiran retirar "
    "retiros recta rectas rectos medida medio media fabricas despachos colore color "
    "ballenas narices direcciones ubicaciones piscinas".split())


def _fix_word(match: re.Match[str]) -> str:
    word = match.group(0)
    key = plain(word)
    if key in _PLAIN_VOCABULARY or key in _REAL_WORDS:
        return word
    if key in _ALIASES:
        return _ALIASES[key]
    if len(key) < 6:
        return word
    near = closest(key, _PLAIN_VOCABULARY, cutoff=0.85)
    return _PLAIN_VOCABULARY[near] if near else word


_NUMBER_WORDS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "dieciseis": 16, "dieciséis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20,
}
_NUM = r"(\d{1,3}(?:[.,]\d{1,2})?)"
_UNIT = r"\s*(?:m|mt|mts|metros?)?\.?"


def _as_number(word: str, half: str | None) -> str:
    value = word if word[0].isdigit() else str(_NUMBER_WORDS[word.casefold()])
    return f"{value},5" if half else value


_WORDS = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_SPOKEN_SIZE = re.compile(
    rf"\b(\d{{1,3}}(?:[.,]\d{{1,2}})?|{_WORDS})(\s+y\s+medio)?\s*(?:metros?\s*)?"
    rf"(?:por|x|×)\s*(\d{{1,3}}(?:[.,]\d{{1,2}})?|{_WORDS})(\s+y\s+medio)?\b", re.IGNORECASE)


def normalize_measurements(text: str) -> str:
    """Rewrite loose pool sizes as «6x3 m», the form the size parser reads."""
    value = text or ""
    # «seis por tres», «seis y medio por tres»: words become digits only here.
    value = _SPOKEN_SIZE.sub(lambda m: f"{_as_number(m.group(1), m.group(2))}x"
                                       f"{_as_number(m.group(3), m.group(4))}"
                             if not (m.group(1)[0].isdigit() and m.group(3)[0].isdigit()
                                     and not m.group(2) and not m.group(4))
                             else m.group(0), value)
    value = re.sub(r"(\d)\s*(?:mts|mt)\b\.?", r"\1 m", value, flags=re.IGNORECASE)
    value = re.sub(rf"\blargo\s*(?:de|:)?\s*{_NUM}{_UNIT}[\s,;y]+(?:de\s+)?ancho\s*(?:de|:)?\s*{_NUM}{_UNIT}",
                   r"\1x\2 m", value, flags=re.IGNORECASE)
    value = re.sub(rf"{_NUM}{_UNIT}\s+de\s+largo[\s,;y]+{_NUM}{_UNIT}\s+de\s+ancho",
                   r"\1x\2 m", value, flags=re.IGNORECASE)
    return value


def normalize_customer_text(text: str) -> str:
    """Domain typos fixed and sizes rewritten; everything else left as written."""
    if not text or len(text) > 300:
        return text
    fixed = re.sub(r"[^\W\d_]+", _fix_word, text)
    return normalize_measurements(fixed)
