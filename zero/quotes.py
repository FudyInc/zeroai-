"""Presupuestos deterministas — la aritmética nunca se delega al LLM.

Mismo patrón que `config.project_funnel`: el modelo puede *pedir* o *presentar*
un presupuesto, pero los números salen de aquí, exactos en cualquier backend.

Piezas:
- `normalize_pricing`   — valida la lista de precios que carga el dashboard.
- `extract_request`     — detecta en el mensaje del lead qué ítems del catálogo
                          pide y en qué cantidad (regex, sin LLM).
- `compute_quote`       — calcula líneas, subtotal, IVA y total (puro).
- `format_quote`        — el bloque de texto que se le manda al lead (solo dibuja).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

from .config import IVA_RATE

# La lista de precios de un cliente (la carga el dashboard, vive en memory):
# {"currency": "CLP", "iva_rate": 0.19, "items": [
#     {"id": "sitio-web", "name": "Sitio web", "unit_price": 450000, "unit": "sitio"}]}


def _slug(text: str) -> str:
    text = _fold(text).strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "item"


def _fold(text: str) -> str:
    """Sin acentos, para comparar 'diseño' con 'diseno' sin drama."""
    return "".join(c for c in unicodedata.normalize("NFKD", str(text))
                   if not unicodedata.combining(c))


def normalize_pricing(raw: Any) -> Dict[str, Any]:
    """Acepta lo que mande el dashboard y devuelve una lista de precios sana.
    Ítems sin nombre o sin precio numérico > 0 se descartan (mejor un catálogo
    corto y correcto que uno que cotiza basura)."""
    raw = raw if isinstance(raw, dict) else {}
    items: List[Dict[str, Any]] = []
    seen = set()
    for it in raw.get("items") or []:
        if not isinstance(it, dict):
            continue
        name = str(it.get("name") or "").strip()
        try:
            price = float(it.get("unit_price"))
        except (TypeError, ValueError):
            continue
        if not name or price <= 0:
            continue
        item_id = _slug(str(it.get("id") or name))
        if item_id in seen:
            continue
        seen.add(item_id)
        items.append({"id": item_id, "name": name,
                      "unit_price": round(price, 2),
                      "unit": str(it.get("unit") or "").strip() or None})
    try:
        iva = float(raw.get("iva_rate"))
        if not 0.0 <= iva <= 1.0:
            iva = IVA_RATE
    except (TypeError, ValueError):
        iva = IVA_RATE
    return {"currency": str(raw.get("currency") or "CLP").upper(),
            "iva_rate": iva, "items": items}


# --- extracción del pedido (determinista) --------------------------------------

# "3 sitios web", "sitio web x2", "dos logos" — cantidad pegada al nombre.
_QTY_WORDS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4,
              "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}

# Señales de que el lead está pidiendo precio/cotización (gate para no cotizar
# cada vez que alguien apenas menciona un producto).
_PRICE_INTENT_RE = re.compile(
    r"\b(precio|precios|costo|costos|cuesta|cuestan|cu[aá]nto|valor|vale|valen|"
    r"tarifa|cotiza\w*|cotizaci[oó]n|presupuesto)\b")


def _name_pattern(name: str) -> re.Pattern:
    """Regex del nombre del ítem con plurales simples: 'sitio web' matchea
    'sitios web'. Se compara sobre texto sin acentos y en minúscula."""
    words = [re.escape(w) + r"(?:es|s)?" for w in _fold(name).lower().split()]
    return re.compile(r"\b" + r"\s+".join(words) + r"\b")


def extract_request(message: str, pricing: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Qué ítems del catálogo pide el mensaje y cuántos. Devuelve
    [{"id", "qty"}]. Cotiza solo si hay cantidad explícita para algún ítem o si
    el mensaje trae intención de precio; una mención suelta no dispara nada."""
    msg = _fold(message or "").lower()
    if not msg:
        return []
    found: List[Dict[str, Any]] = []
    explicit_qty = False
    for item in pricing.get("items") or []:
        m = _name_pattern(item["name"]).search(msg)
        if not m:
            continue
        qty, explicit = 1, False
        before = msg[: m.start()].rstrip()
        after = msg[m.end():].lstrip()
        qm = re.search(r"(\d+)\s*$", before) or re.match(r"[x×]\s*(\d+)", after)
        if qm:
            qty, explicit = int(qm.group(1)), True
        else:
            wm = re.search(r"([a-z]+)\s*$", before)
            if wm and wm.group(1) in _QTY_WORDS:
                qty, explicit = _QTY_WORDS[wm.group(1)], True
        if 0 < qty <= 1000:   # una "cantidad" absurda es un número suelto, no un pedido
            found.append({"id": item["id"], "qty": qty})
            explicit_qty = explicit_qty or explicit
    if not found:
        return []
    if not explicit_qty and not _PRICE_INTENT_RE.search(msg):
        return []
    return found


# --- cálculo (puro) -------------------------------------------------------------

def compute_quote(pricing: Dict[str, Any],
                  requested: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Presupuesto exacto para los ítems pedidos. `requested` = [{"id", "qty"}].
    Ítems que no están en el catálogo van a `unmatched` (el agente puede decir
    'esto no lo tenemos'); si ninguno matchea, no hay presupuesto (None)."""
    catalog = {it["id"]: it for it in pricing.get("items") or []}
    lines: List[Dict[str, Any]] = []
    unmatched: List[str] = []
    for req in requested or []:
        item = catalog.get(_slug(str(req.get("id") or "")))
        try:
            qty = int(req.get("qty", 1))
        except (TypeError, ValueError):
            qty = 1
        if item is None or qty <= 0:
            unmatched.append(str(req.get("id") or ""))
            continue
        lines.append({"id": item["id"], "name": item["name"], "qty": qty,
                      "unit_price": item["unit_price"],
                      "subtotal": round(qty * item["unit_price"], 2)})
    if not lines:
        return None
    subtotal = round(sum(l["subtotal"] for l in lines), 2)
    iva_rate = pricing.get("iva_rate", IVA_RATE)
    iva = round(subtotal * iva_rate, 2)
    return {"currency": pricing.get("currency", "CLP"),
            "lines": lines, "subtotal": subtotal,
            "iva_rate": iva_rate, "iva": iva,
            "total": round(subtotal + iva, 2),
            "unmatched": unmatched}


# --- presentación (solo dibuja) --------------------------------------------------

def _money(value: float, currency: str) -> str:
    """$1.450.000 para CLP (sin decimales); 1,450.00 USD para el resto."""
    if currency == "CLP":
        return "$" + f"{round(value):,}".replace(",", ".")
    return f"{value:,.2f} {currency}"


def format_quote(quote: Dict[str, Any]) -> str:
    """El presupuesto como texto listo para WhatsApp. Solo formatea."""
    cur = quote.get("currency", "CLP")
    out = ["📋 *Presupuesto*"]
    for l in quote["lines"]:
        qty = f'{l["qty"]} × ' if l["qty"] != 1 else ""
        out.append(f'• {qty}{l["name"]}: {_money(l["subtotal"], cur)}')
    out.append(f'Subtotal: {_money(quote["subtotal"], cur)}')
    out.append(f'IVA ({round(quote["iva_rate"] * 100)}%): {_money(quote["iva"], cur)}')
    out.append(f'*Total: {_money(quote["total"], cur)}*')
    return "\n".join(out)
