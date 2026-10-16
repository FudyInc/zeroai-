"""Internal LosetasChile budget for human review before customer delivery."""
from __future__ import annotations

import re
from typing import Any

from .losetas_polls import FACTORY_MAP_URL


def format_internal_budget(quote: dict[str, Any], *, profile_name: str | None,
                           phone: str, tone: str | None) -> str | None:
    """Include the customer's number, and their WhatsApp display name if present."""
    digits = re.sub(r"\D", "", phone or "")
    if not 8 <= len(digits) <= 15 or quote.get("currency") != "CLP":
        return None
    if quote.get("unmatched") or not quote.get("lines"):
        return None
    display = " ".join((profile_name or "").split())[:80]
    if not any(char.isalpha() for char in display):
        display = ""
    money = lambda amount: "$" + f"{round(amount):,}".replace(",", ".")
    lines = ["*PRESUPUESTO LOSETAS CHILE · REVISIÓN INTERNA*"]
    if display:
        lines.append(f"Cliente: {display}")
    lines.append(f"Número: +{digits}")
    if tone:
        selected = " ".join(str(tone).split())[:80]
        lines.append(f"Color indicado por cliente: {selected}")
    else:
        lines.append("Tono: pendiente de confirmar")
    lines.append("")
    for item in quote["lines"]:
        lines.append(f"{item['qty']} × {item['name']} · {money(item['unit_price'])} c/u = "
                     f"{money(item['subtotal'])}")
    lines.extend(["", f"*Total productos: {money(quote['total'])}*"])
    delivery = " ".join(str(quote.get("delivery_detail") or "").split())[:300]
    if delivery:
        lines.append(delivery)
    if delivery.startswith("Retiro en fábrica:"):
        if FACTORY_MAP_URL:
            lines.append(f"Ubicación fábrica: {FACTORY_MAP_URL}")
        lines.append("Costo de envío: no aplica (retiro en fábrica).")
    else:
        lines.append("Costo de envío: pendiente de confirmación del equipo.")
    lines.extend(["Fecha de entrega: pendiente de confirmación del equipo.",
                  "Borrador interno. Revisar y enviar manualmente al cliente."])
    return "\n".join(lines)
