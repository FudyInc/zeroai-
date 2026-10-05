"""Small, local context selection for WhatsApp conversations.

The knowledge sheet remains the source of truth. Retrieval only decides which
parts fit in the local model's prompt; it never manufactures business facts.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from math import log
from typing import Any, Dict, List


_STOP = frozenset("a al con cual cuales de del el en es esta este la las le lo los me mi para por que se si su sus un una y ya".split())
_ALIASES = {
    "despachan": "despacho", "despachar": "despacho", "envio": "despacho",
    "envios": "despacho", "envian": "despacho", "entrega": "despacho",
    "entregas": "despacho", "entregan": "despacho", "entregamos": "despacho",
    "precio": "precio", "precios": "precio", "cuesta": "precio",
    "cuestan": "precio", "costo": "precio", "costos": "precio",
    "valor": "precio", "cotizar": "precio", "cotizacion": "precio",
    "medida": "medida", "medidas": "medida", "dimension": "medida",
    "dimensiones": "medida", "tamano": "medida", "m2": "medida",
    "stock": "stock", "disponible": "stock", "disponibilidad": "stock",
    "horario": "horario", "horarios": "horario", "atienden": "horario",
}


def _terms(value: str) -> set[str]:
    plain = "".join(c for c in unicodedata.normalize("NFKD", value.lower())
                    if not unicodedata.combining(c))
    return {_ALIASES.get(word, word) for word in re.findall(r"[a-z0-9]{2,}", plain)
            if word not in _STOP}


def _split_long(paragraph: str, width: int = 500) -> List[str]:
    """Cut on word boundaries so a selected fragment stays readable."""
    words = paragraph.split()
    parts: List[str] = []
    current = ""
    for word in words:
        if current and len(current) + len(word) + 1 > width:
            parts.append(current)
            current = ""
        current = (current + " " + word).strip()
    if current:
        parts.append(current)
    return parts


def _sections(knowledge: str) -> List[str]:
    """Preserve headings and split long free-form paragraphs into bounded parts."""
    result: List[str] = []
    heading = ""
    for paragraph in re.split(r"\n\s*\n", knowledge.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        lines = paragraph.splitlines()
        if len(lines) == 1 and (paragraph.startswith("#") or paragraph.endswith(":")):
            heading = paragraph.lstrip("# ").strip()
            continue
        if len(paragraph) <= 550:
            result.append((heading + ": " if heading else "") + paragraph)
            continue
        for part in _split_long(paragraph):
            result.append((heading + ": " if heading else "") + part)
    return result


def select_knowledge(knowledge: str, question: str, max_chars: int = 1600) -> str:
    """Choose relevant sections while retaining a brief business introduction."""
    sections = _sections(knowledge)
    if not sections or max_chars <= 0:
        return ""
    query = _terms(question)
    terms = [_terms(section) for section in sections]
    frequency = Counter(term for section in terms for term in section)
    def score(index: int) -> float:
        shared = query & terms[index]
        return sum(log(1 + len(sections) / frequency[term]) for term in shared)
    ranked = sorted(range(len(sections)), key=lambda index: (-score(index), index))
    selected = {0}  # the beginning normally identifies the business
    used = min(len(sections[0]), max_chars)
    for index in ranked:
        section = sections[index]
        if index in selected or score(index) == 0:
            continue
        if used + len(section) + 2 <= max_chars:
            selected.add(index)
            used += len(section) + 2
    if len(selected) == 1 and not any(score(index) for index in range(1, len(sections))):
        for index in range(1, len(sections)):
            if used + len(sections[index]) + 2 > max_chars:
                break
            selected.add(index)
            used += len(sections[index]) + 2
    result = "\n\n".join(sections[index] for index in sorted(selected))
    return result[:max_chars]


def select_history(turns: List[Dict[str, Any]], question: str,
                   max_turns: int = 4) -> List[Dict[str, str]]:
    """Keep the latest exchange and recall relevant older user statements."""
    turns = turns or []
    if len(turns) <= max_turns:
        chosen = turns
    else:
        recent = set(range(len(turns) - 2, len(turns)))
        query = _terms(question)
        older = sorted((i for i in range(len(turns) - 2)
                        if turns[i].get("role") == "lead"),
                       key=lambda i: (-len(query & _terms(str(turns[i].get("text") or ""))), -i))
        chosen = [turns[i] for i in sorted(recent | set(older[:max_turns - 2]))]
    return [{"role": str(turn.get("role") or ""),
             "text": str(turn.get("text") or "")[:300]}
            for turn in chosen]
