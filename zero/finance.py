"""Finanzas de la AGENCIA — entra (MRR) / sale (costos) / margen mensual.

Plata de ZeroAI, no del cliente (docs/finanzas-plan.md separa los dos planos:
pipeline proyectado, gasto de ads y cotizaciones son del cliente y NO entran acá).

Reparto de responsabilidades:
- Las CATEGORÍAS de costo son política → `config.FINANCE_COST_CATEGORIES`.
- Las CIFRAS reales viven solo en `finance.json` (local, gitignorado, mismo trato
  que `crm.json`: escritura ajena a este módulo — se edita a mano —, y si está
  corrupto se avisa, jamás se sobrescribe).
- El MRR no se copia a mano: llega ya calculado (el caller lo saca de las cuentas
  activas del CRM, igual que `GET /api/accounts`).
- Mock-first: sin `finance.json`, el resumen usa costos de ejemplo con la misma
  forma que los reales y `source: "mock"` para que nadie los confunda.

Forma de `finance.json` (todo en CLP, convertir USD al anotar):

    {"months": {"2026-07": {
        "costs": [{"category": "vapi", "amount_clp": 45000, "note": "310 min"}],
        "mrr_clp": 250000    # opcional: foto del MRR al cerrar el mes
    }}}

`mrr_clp` por mes es opcional: el mes en curso usa el MRR vivo; los meses
cerrados solo tienen tendencia si se anotó la foto.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import FINANCE_COST_CATEGORIES
from .persistence import load_json

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# Cifras de EJEMPLO para el modo mock — misma forma que las reales, valores
# deliberadamente redondos para que se noten de lejos.
_MOCK_COSTS = [
    {"category": "vapi", "amount_clp": 40_000, "note": "cifra de ejemplo"},
    {"category": "elevenlabs", "amount_clp": 10_000, "note": "cifra de ejemplo"},
    {"category": "dominio", "amount_clp": 2_000, "note": "cifra de ejemplo"},
]


def valid_month(month: str) -> bool:
    """'2026-07' sí; '2026-7', '07-2026' o 'julio' no."""
    return bool(_MONTH_RE.match(str(month or "")))


def current_month() -> str:
    return date.today().strftime("%Y-%m")


def normalize_costs(raw: Any) -> List[Dict[str, Any]]:
    """Acepta lo que haya en el JSON y devuelve costos sanos: monto numérico > 0
    obligatorio; rubro desconocido cae en "otros" (conservando el nombre original
    en la nota) en vez de perderse — mejor un resumen completo que uno que calla
    costos porque alguien escribió "Vapi " con mayúscula."""
    out: List[Dict[str, Any]] = []
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict):
            continue
        try:
            amount = round(float(it.get("amount_clp")))
        except (TypeError, ValueError):
            continue
        if amount <= 0:
            continue
        category = str(it.get("category") or "").strip().lower()
        note = str(it.get("note") or "").strip()
        if category not in FINANCE_COST_CATEGORIES:
            note = f"{category or 'sin rubro'}{' — ' + note if note else ''}"
            category = "otros"
        out.append({"category": category, "amount_clp": amount, "note": note or None})
    return out


def _month_summary(month: str, costs: List[Dict[str, Any]],
                   mrr_clp: Optional[int], source: str) -> Dict[str, Any]:
    """Aritmética del resumen — pura, nunca delegada al LLM (patrón quotes.py).
    Sin MRR conocido (mes cerrado sin foto) el margen queda en None, no en un
    número inventado."""
    costs_clp = sum(c["amount_clp"] for c in costs)
    margin_clp = (mrr_clp - costs_clp) if mrr_clp is not None else None
    margin_pct = (round(margin_clp * 100 / mrr_clp, 1)
                  if margin_clp is not None and mrr_clp else None)
    return {"month": month, "source": source, "mrr_clp": mrr_clp,
            "costs": costs, "costs_clp": costs_clp,
            "margin_clp": margin_clp, "margin_pct": margin_pct}


def summary(data: Optional[Dict[str, Any]], mrr_clp: int,
            month: Optional[str] = None) -> Dict[str, Any]:
    """Resumen del mes pedido (default: el actual) + historial para tendencia.

    `data` es el contenido de finance.json (None = no existe → mock). El MRR del
    mes en curso es siempre el vivo; para meses cerrados manda la foto anotada
    en el archivo, si la hay.
    """
    today = current_month()
    month = month or today
    months = (data or {}).get("months")
    months = months if isinstance(months, dict) else {}

    if data is None:
        summ = _month_summary(month, list(_MOCK_COSTS),
                              mrr_clp if month == today else None, "mock")
        return {**summ, "history": []}

    def _mrr_for(m: str) -> Optional[int]:
        entry = months.get(m) or {}
        try:
            return round(float(entry["mrr_clp"]))
        except (KeyError, TypeError, ValueError):
            return mrr_clp if m == today else None

    entry = months.get(month) or {}
    summ = _month_summary(month, normalize_costs(entry.get("costs")),
                          _mrr_for(month), "real")
    history = []
    for m in sorted(m for m in months if valid_month(m)):
        h = _month_summary(m, normalize_costs((months[m] or {}).get("costs")),
                           _mrr_for(m), "real")
        history.append({k: h[k] for k in ("month", "mrr_clp", "costs_clp", "margin_clp")})
    return {**summ, "history": history}


def load_finance(path: str | Path) -> Optional[Dict[str, Any]]:
    """Lee finance.json. No existe → None (modo mock). Corrupto → deja subir el
    RuntimeError de persistence (que ya intentó el .bak y avisó por stderr): la
    regla de la casa es avisar, nunca sobrescribir ni arrancar vacío en silencio."""
    path = Path(path)
    if not path.exists():
        return None
    data = load_json(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"{path} no tiene la forma esperada (dict con 'months')")
    return data


def finance_summary(path: str | Path, mrr_clp: int,
                    month: Optional[str] = None) -> Dict[str, Any]:
    """Punto de entrada para la API: archivo → resumen, mock si no hay archivo."""
    return summary(load_finance(path), mrr_clp, month)
