"""Internal LosetasChile budget for human review before customer delivery."""
from __future__ import annotations

import re
from typing import Any

from .config import LOSETASCHILE_FLETE_CLP_PER_KM, LOSETASCHILE_FLETE_ORIGIN
from .quotes import compute_losetas_shipping_cost


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
        lines.append(f"Color indicado por cliente: {selected} (confirmar disponibilidad)")
    else:
        lines.append("Tono: pendiente de confirmar")
    lines.append("")
    for item in quote["lines"]:
        lines.append(f"{item['qty']} × {item['name']} · {money(item['unit_price'])} c/u = "
                     f"{money(item['subtotal'])}")
    lines.extend(["", f"*Total productos: {money(quote['total'])}*"])
    shipping = compute_losetas_shipping_cost(quote.get("shipping_route_km"))
    if shipping is None:
        lines.append("Despacho: por cotizar (distancia por ruta pendiente de verificar).")
    else:
        lines.append(f"Despacho: {money(shipping)} "
                     f"({quote['shipping_route_km']} km × {money(LOSETASCHILE_FLETE_CLP_PER_KM)}/km).")
    lines.extend([f"Origen del flete: {LOSETASCHILE_FLETE_ORIGIN}.",
                  f"Tarifa provisional: {money(LOSETASCHILE_FLETE_CLP_PER_KM)}/km.",
                  "Borrador interno. Revisar y enviar manualmente al cliente."])
    if quote.get("delivery_detail"):
        lines.insert(-1, str(quote["delivery_detail"])[:300])
    return "\n".join(lines)
