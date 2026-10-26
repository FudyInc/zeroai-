"""Internal LosetasChile budget for human review before customer delivery."""
from __future__ import annotations

import re
from datetime import date as Date
from typing import Any

from .losetas_polls import FACTORY_ADDRESS, FACTORY_MAP_URL


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


# The customer budget is the one fixed template, the same for every customer:
# greeting and payment messages around it may vary, this never does. It uses
# no monospace block: WhatsApp draws those in a smaller font than the rest.
_RULE = "━" * 16
_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre")


def _money(amount: float) -> str:
    return "$" + f"{round(amount):,}".replace(",", ".")


def _day(day: Date) -> str:
    return f"{_WEEKDAYS[day.weekday()]} {day.day} de {_MONTHS[day.month - 1]}"


def _delivery_text(days: list[Date]) -> str:
    """Weekday names come from the date itself, so they can never disagree."""
    if len(days) == 1:
        text = _day(days[0])
    elif days[0].month == days[-1].month:
        text = (f"{_WEEKDAYS[days[0].weekday()]} {days[0].day} o "
                f"{_day(days[-1])}")
    else:
        text = f"{_day(days[0])} o {_day(days[-1])}"
    return text[0].upper() + text[1:]


def _coherent(quote: dict[str, Any], shipping: float | None, deposit: float | None,
              issued: Date, delivery: list[Date]) -> bool:
    """Every figure the customer reads must add up; otherwise nothing is sent."""
    for item in quote["lines"]:
        qty, unit, subtotal = item.get("qty"), item.get("unit_price"), item.get("subtotal")
        if not (isinstance(qty, int) and qty > 0 and unit and unit > 0 and
                subtotal == qty * unit and str(item.get("name") or "").strip()):
            return False
    if quote.get("total") != sum(item["subtotal"] for item in quote["lines"]):
        return False
    if shipping is not None and shipping < 0:
        return False
    total = quote["total"] + (shipping or 0)
    if deposit is not None and not 0 < deposit < total:
        return False
    return delivery == sorted(delivery) and all(day >= issued for day in delivery)


def format_customer_budget(quote: dict[str, Any], *, number: str, issued: Date,
                           customer: str, phone: str, address: str | None,
                           color: str | None, pool: str | None,
                           shipping: float | None, shipping_label: str,
                           delivery: list[Date], deposit: float | None,
                           map_url: str | None = None) -> str | None:
    """The budget the customer receives, after a person reviewed it."""
    digits = re.sub(r"\D", "", phone or "")
    if (quote.get("currency") != "CLP" or not quote.get("lines") or
            quote.get("unmatched") or not 8 <= len(digits) <= 15 or
            not customer.strip() or
            not _coherent(quote, shipping, deposit, issued, delivery)):
        return None
    pretty_phone = (f"+{digits[:2]} {digits[2]} {digits[3:7]} {digits[7:]}"
                    if len(digits) == 11 else f"+{digits}")
    total = quote["total"] + (shipping or 0)
    pieces = sum(item["qty"] for item in quote["lines"])
    lines = ["*POOLEDGE*", "Bordes de piscina y pastelones", FACTORY_ADDRESS, _RULE,
             f"*PRESUPUESTO N° {number}*",
             f"Emitido el {issued.day} de {_MONTHS[issued.month - 1]} de {issued.year}", "",
             "*Cliente*", " ".join(customer.split()).title(), pretty_phone, _RULE, "*Detalle*"]
    if color:
        lines.append(f"Color: {color.strip().capitalize()}")
    if pool:
        lines.append(f"Piscina: {pool}")
    for n, item in enumerate(quote["lines"], 1):
        lines.extend(["", f"*{n}. {item['name']}*",
                      f"{item['qty']} un. × {_money(item['unit_price'])} = *{_money(item['subtotal'])}*"])
    lines.extend(["", f"Total piezas: {pieces}", _RULE,
                  f"Subtotal productos: {_money(quote['total'])}",
                  f"{shipping_label}: {_money(shipping)}" if shipping is not None
                  else f"{shipping_label}: por cotizar",
                  f"*TOTAL: {_money(total)}*"])
    if deposit:
        lines.extend(["", f"Abono para confirmar: {_money(deposit)}",
                      f"Saldo contra entrega: {_money(total - deposit)}"])
    lines.extend([_RULE, "*Entrega*",
                  _delivery_text(delivery) if delivery else "Fecha por confirmar"])
    if address:
        lines.append(address)
    if map_url:
        lines.append(f"Ubicación: {map_url.strip()}")
    lines.extend(["", "_Precios finales por unidad._"])
    return "\n".join(lines)
