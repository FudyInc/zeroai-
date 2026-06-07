"""Kanban rendering for the CRM — presentation only.

Kept apart from `crm.py` on purpose: the CRM owns the data and rules; this module
only decides how to *draw* it. `render()` returns a string, so it's easy to test
and works the same whether printed to a terminal or captured.
"""
from __future__ import annotations

import shutil
from typing import Any, Dict, List

from .config import CRM_STAGES

# Short Spanish labels + a colour per stage (ANSI). Order follows CRM_STAGES.
_LABEL = {
    "new": "NUEVOS", "qualified": "CALIFICADOS", "disqualified": "DESCARTADOS",
    "contacted": "CONTACTADOS", "nurturing": "SEGUIMIENTO", "replied": "RESPONDIERON",
    "meeting": "REUNIÓN", "won": "GANADOS", "lost": "PERDIDOS",
}
_COLOR = {
    "new": "90", "qualified": "96", "disqualified": "91", "contacted": "93",
    "nurturing": "95", "replied": "94", "meeting": "92", "won": "1;92", "lost": "2;90",
}
# Stages that form the forward flow shown in the legend (terminal ones excluded).
_FLOW = ("new", "qualified", "contacted", "nurturing", "replied", "meeting", "won")

_COLW = 24          # visible width of a column
_GAP = 1            # spaces between columns
_RESET = "\033[0m"


def _paint(text: str, color: str, on: bool) -> str:
    return f"\033[{color}m{text}{_RESET}" if on else text


def _fit(text: str, width: int = _COLW) -> str:
    """Truncate with an ellipsis, then pad to exactly `width` visible chars."""
    text = text or ""
    if len(text) > width:
        text = text[: width - 1] + "…"
    return text.ljust(width)


def _column(stage: str, leads: List[Dict[str, Any]], color: str, on: bool, max_cards: int) -> List[str]:
    """Build one column as a list of equal-width lines (header + cards)."""
    head = _paint(_fit(f"{_LABEL.get(stage, stage)}  {len(leads)}"), color, on)
    rule = _paint(_fit("─" * _COLW), color, on)
    lines = [head, rule]

    if not leads:
        lines.append(_paint(_fit("  (vacío)"), "90", on))
    for r in leads[:max_cards]:
        score = r.get("score")
        badge = f"[{score if score is not None else '—'}]"
        lines.append(_fit(f"{badge} {r.get('company') or '—'}"))
        contact = r.get("email") or r.get("phone") or (r.get("role") or "—")
        lines.append(_paint(_fit(f"     {contact}"), "90", on))
        lines.append(_fit(""))   # spacer between cards
    if len(leads) > max_cards:
        lines.append(_paint(_fit(f"  +{len(leads) - max_cards} más…"), "90", on))
    return lines


def render_lead(crm: Any, client: str, key: str, color: bool = True) -> str:
    """One lead's full story: fields + the timeline of everything that happened."""
    rec = crm.get(client, key)
    if rec is None:
        return _paint(f"\n  No encontré el lead '{key}' para {client}.\n", "91", color)
    stage = rec.get("stage")
    out = [
        "",
        _paint(f"  {rec.get('company')} · {rec.get('role') or '—'}", "1;97", color),
        f"  etapa: {_paint(_LABEL.get(stage, stage), _COLOR.get(stage, '97'), color)}"
        f"    score: {rec.get('score') if rec.get('score') is not None else '—'}",
        _paint(f"  {rec.get('email') or rec.get('phone') or '—'}   ·   key: {rec.get('key')}", "90", color),
        "",
        _paint("  Historial:", "90", color),
    ]
    for h in rec.get("history", []):
        ts = (h.get("ts") or "")[11:19]
        detail = f"  {h['detail']}" if h.get("detail") else ""
        out.append(f"    {_paint(ts, '90', color)}  {(h.get('event') or ''):10}{detail}")
    out.append("")
    return "\n".join(out)


def render(crm: Any, client: str, color: bool = True, max_cards: int = 5, width: int = 0) -> str:
    width = width or shutil.get_terminal_size((100, 24)).columns
    per_row = max(1, (width + _GAP) // (_COLW + _GAP))

    total = sum(crm.counts(client).values())
    flow = _paint(" → ", "90", color).join(_paint(_LABEL[s], _COLOR[s], color) for s in _FLOW)
    out = [
        "",
        _paint(f"  ZERO · CRM · {client}", "1;97", color) + _paint(f"   ({total} leads)", "90", color),
        f"  {flow}",
        "",
    ]
    if total == 0:
        out.append(_paint("  (vacío — corré el pipeline primero para poblarlo)", "90", color))
        out.append("")
        return "\n".join(out)

    columns = [_column(s, crm.list(client, s), _COLOR[s], color, max_cards) for s in CRM_STAGES]

    sep = " " * _GAP
    for i in range(0, len(columns), per_row):
        band = columns[i: i + per_row]
        height = max(len(c) for c in band)
        blank = _fit("")
        for c in band:
            c += [blank] * (height - len(c))   # pad columns to equal height
        for row in range(height):
            out.append("  " + sep.join(c[row] for c in band))
        out.append("")
    return "\n".join(out)
