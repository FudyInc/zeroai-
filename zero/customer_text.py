"""Read what customers actually type: typos, number words and loose sizes.

People write «pisina», «kiero cotisar», «ocho por cuatro», «8 de largo y 4 de
ancho» or «7,25 x 3,5». The deterministic readers (product, pool size, paver
area) only understood the tidy forms, and one of them read «7,25» as 25 —
quoting 114 borders for a 7 × 3.5 pool (ensayo 2026-11-09).

`normalize` returns a copy for those readers only. The model and the stored
history keep the customer's own words.
"""
from __future__ import annotations

import re

# Domain words worth correcting. Only these: correcting free text in general
# would turn real words into others.
_VOCABULARY = ("piscina", "piscinas", "cotizar", "cotizacion", "necesito", "pastelones",
               "pastelon", "bordes", "presupuesto", "rectangular", "quiero", "metros")
_KNOWN_TYPOS = {
    "kiero": "quiero", "qiero": "quiero", "quero": "quiero",
    "bordez": "bordes", "vordes": "bordes", "bordess": "bordes",
    "pasteones": "pastelones", "pastelons": "pastelones", "pastelone": "pastelones",
    "nesesito": "necesito", "nesecito": "necesito", "nececito": "necesito",
    "cotisar": "cotizar", "cotisacion": "cotizacion", "cotisación": "cotización",
    "pisina": "piscina", "picina": "piscina", "pissina": "piscina", "pisinas": "piscinas",
    "mtrs": "metros", "mts": "metros", "mt": "metros",
}
_NUMBER_WORDS = {
    "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13,
    "catorce": 14, "quince": 15, "dieciseis": 16, "dieciséis": 16, "diecisiete": 17,
    "dieciocho": 18, "diecinueve": 19, "veinte": 20, "veinticinco": 25, "treinta": 30,
    "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80,
    "noventa": 90, "cien": 100,
}
_TENS = {"treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
         "ochenta": 80, "noventa": 90}
_UNITS = {k: v for k, v in _NUMBER_WORDS.items() if 1 <= v <= 9 and k not in ("un", "una")}
_NUM = r"\d{1,3}(?:[.,]\d{1,2})?"
# «un»/«una» are articles far more often than numbers: only as a size next to «por/x».
_SIZE_WORD = r"(?:x|×|por|\*)"


def _one_edit_away(value: str, target: str) -> bool:
    if value == target or abs(len(value) - len(target)) > 1:
        return value == target
    if len(value) == len(target):
        return sum(a != b for a, b in zip(value, target)) == 1
    short, long_ = sorted((value, target), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def fix_typos(text: str) -> str:
    def correct(match: re.Match[str]) -> str:
        word = match.group()
        folded = word.casefold()
        if folded in _KNOWN_TYPOS:
            return _KNOWN_TYPOS[folded]
        if len(folded) >= 6 and folded not in _VOCABULARY:
            for target in _VOCABULARY:
                if len(target) >= 6 and _one_edit_away(folded, target):
                    return target
        return word
    return re.sub(r"\b[a-záéíóúñ]{2,12}\b", correct, text or "", flags=re.IGNORECASE)


def _words_to_digits(text: str) -> str:
    # «treinta y cinco» → 35 before the single words.
    def compound(match: re.Match[str]) -> str:
        return str(_TENS[match.group(1).lower()] + _UNITS[match.group(2).lower()])
    text = re.sub(rf"\b({'|'.join(_TENS)})\s+y\s+({'|'.join(_UNITS)})\b", compound, text,
                  flags=re.IGNORECASE)
    words = "|".join(sorted((w for w in _NUMBER_WORDS if w not in ("un", "una")),
                            key=len, reverse=True))
    text = re.sub(rf"\b({words})\b", lambda m: str(_NUMBER_WORDS[m.group(1).lower()]), text,
                  flags=re.IGNORECASE)
    # «una piscina de un metro por 3» is rare; «un/una» only right next to a size sign.
    text = re.sub(rf"\b(?:un|una)\b(?=\s*(?:metros?\s*)?{_SIZE_WORD})", "1", text,
                  flags=re.IGNORECASE)
    # «un metro por cuatro» — article-like one only when it is a dimension.
    text = re.sub(r"\b(?:un|una)\b(?=\s+(?:metro|metros|mt|mts|mtrs?)\b)", "1", text,
                  flags=re.IGNORECASE)
    # Number-words as direct dimension answers: «largo ocho ancho cuatro».
    text = re.sub(r"\b(un|una)\b(?=\s*(?:de\s+)?(?:largo|ancho)\b)", "1", text,
                  flags=re.IGNORECASE)
    return text


def normalize_numbers(text: str) -> str:
    text = _words_to_digits(text or "")
    # «8 y medio», «8 1/2», «8 ½» → 8,5
    text = re.sub(r"(\d+)\s*(?:y\s+medio|1/2|½)", r"\1,5", text, flags=re.IGNORECASE)
    # «8 ,5» / «8 , 5»: a stray space inside a decimal.
    text = re.sub(r"(\d)\s+,\s*(\d)", r"\1,\2", text)
    # Decimal comma may contain whitespace on both sides («8 , 5»).
    text = re.sub(r"(\d)\s+\.\s*(\d)", r"\1.\2", text)
    # «8 * 4»
    text = re.sub(r"(\d)\s*\*\s*(\d)", r"\1 x \2", text)
    unit = r"(?:\s*m(?:ts?|trs?|etros?)?\.?)?"
    # «8 de largo y 4 de ancho», «8 largo x 4 ancho»
    text = re.sub(rf"({_NUM}){unit}\s*(?:de\s+)?largo\s*(?:y|,|x|por)?\s*({_NUM}){unit}\s*"
                  r"(?:de\s+)?ancho\b", r"\1 x \2", text, flags=re.IGNORECASE)
    text = re.sub(rf"({_NUM}){unit}\s*(?:de\s+)?ancho\s*(?:y|,|x|por)?\s*({_NUM}){unit}\s*"
                  r"(?:de\s+)?largo\b", r"\2 x \1", text, flags=re.IGNORECASE)
    # «largo 8 ancho 4», «largo: 8 m, ancho: 4 m»
    text = re.sub(rf"\blargo\s*(?:de\s*)?:?\s*({_NUM}){unit}\s*(?:y|,)?\s*ancho\s*(?:de\s*)?:?"
                  rf"\s*({_NUM}){unit}", r"\1 x \2", text, flags=re.IGNORECASE)
    text = re.sub(rf"\bancho\s*(?:de\s*)?:?\s*({_NUM}){unit}\s*(?:y|,)?\s*largo\s*(?:de\s*)?:?"
                  rf"\s*({_NUM}){unit}", r"\2 x \1", text, flags=re.IGNORECASE)
    return text


def normalize(text: str) -> str:
    """Typos fixed and numbers made digits, for the deterministic readers only."""
    return normalize_numbers(fix_typos(text or ""))
