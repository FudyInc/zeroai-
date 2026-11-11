"""Internal LosetasChile budget for human review before customer delivery."""
from __future__ import annotations

import math
import re
from datetime import date as Date
from decimal import Decimal, InvalidOperation
from typing import Any

from .config import LOSETASCHILE_PAVER_PIECES_PER_M2
from .losetas_polls import FACTORY_ADDRESS, FACTORY_MAP_URL


def paver_pieces(area_m2: Any, price_id: str | None) -> int | None:
    """Pieces that cover the area, rounded up; None when the size has no known yield."""
    rate = LOSETASCHILE_PAVER_PIECES_PER_M2.get(price_id or "")
    try:
        area = Decimal(str(area_m2).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    if not rate or not area.is_finite() or area <= 0:
        return None
    return math.ceil(area * rate)


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
    lines = ["*PRESUPUESTO POOLEDGE · REVISIÓN INTERNA*"]
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
    lines.append("Fecha de entrega: pendiente de confirmación del equipo.")
    for note in quote.get("review_notes") or ():
        lines.append("Nota: " + " ".join(str(note).split())[:300])
    lines.append("Borrador interno. Revisar y enviar manualmente al cliente.")
    return "\n".join(lines)


def paver_order_to_quote(order: dict[str, Any]) -> dict[str, Any] | None:
    """Quote of a complete paver order, in the shape format_customer_budget takes.

    None when the order lacks model, area, price id or unit price."""
    area, price_id = order.get("area_m2"), order.get("price_id")
    unit, model = order.get("unit_price"), order.get("model")
    if not (area and price_id and unit and model):
        return None
    pieces = paver_pieces(area, price_id)
    if not pieces:
        return None
    subtotal = pieces * unit
    quote: dict[str, Any] = {"currency": "CLP", "lines": [{
        "id": price_id, "name": model, "qty": pieces, "unit_price": unit,
        "subtotal": subtotal}], "subtotal": subtotal, "iva_rate": 0, "iva": 0,
        "total": subtotal, "unmatched": []}
    detail = " ".join(str(order.get("delivery_detail") or "").split())[:300]
    if detail:
        quote["delivery_detail"] = detail
    return quote


_PAVER_LINE = re.compile(r"^(\d+) × (.+?) · \$([\d.]+) c/u = \$([\d.]+)$", re.M)


def paver_quote_from_draft(text: str) -> dict[str, Any] | None:
    """Quote of a paver draft published before drafts carried one.

    Only the one line the code itself wrote, and only when its figures add up."""
    found = _PAVER_LINE.findall(text or "")
    if len(found) != 1:
        return None
    qty, name, unit, subtotal = found[0]
    qty, unit, subtotal = int(qty), int(unit.replace(".", "")), int(subtotal.replace(".", ""))
    if qty <= 0 or unit <= 0 or qty * unit != subtotal:
        return None
    quote: dict[str, Any] = {"currency": "CLP", "lines": [{
        "id": None, "name": name.strip(), "qty": qty, "unit_price": unit,
        "subtotal": subtotal}], "subtotal": subtotal, "iva_rate": 0, "iva": 0,
        "total": subtotal, "unmatched": []}
    pickup = re.search(r"^Retiro en fábrica:.*$", text, re.M)
    if pickup:
        quote["delivery_detail"] = pickup.group(0)[:300]
    return quote


def format_paver_order_draft(order: dict[str, Any], *, profile_name: str | None,
                             phone: str) -> str | None:
    """Paver order for the review group. No price: the team quotes, and says so."""
    digits = re.sub(r"\D", "", phone or "")
    if not 8 <= len(digits) <= 15 or not order.get("model") or not order.get("area_m2"):
        return None
    display = " ".join((profile_name or "").split())[:80]
    if not any(char.isalpha() for char in display):
        display = ""
    lines = ["*PEDIDO PASTELONES POOLEDGE · REVISIÓN INTERNA*"]
    if display:
        lines.append(f"Cliente: {display}")
    lines.extend([f"Número: +{digits}",
                  f"Modelo: {order['model']}",
                  f"Color indicado por cliente: {order.get('color') or 'pendiente de confirmar'}",
                  f"Superficie: {order['area_m2']} m²"])
    unit = order.get("unit_price")
    lines.append(f"Precio unitario: ${round(unit):,}".replace(",", ".") if unit
                 else "Precio pendiente de confirmar (modelo sin precio confirmado).")
    pieces = paver_pieces(order["area_m2"], order.get("price_id"))
    money = lambda amount: "$" + f"{round(amount):,}".replace(",", ".")
    if pieces and unit:
        rate = LOSETASCHILE_PAVER_PIECES_PER_M2[order["price_id"]]
        lines.extend(["", f"{pieces} × {order['model']} · {money(unit)} c/u = "
                          f"{money(pieces * unit)}",
                      f"({order['area_m2']} m² × {rate} piezas por m², redondeado hacia arriba)",
                      f"*Total productos: {money(pieces * unit)}*", ""])
    delivery = " ".join(str(order.get("delivery_detail") or "").split())[:300]
    if delivery:
        lines.append(delivery)
    if delivery.startswith("Retiro en fábrica:"):
        if FACTORY_MAP_URL:
            lines.append(f"Ubicación fábrica: {FACTORY_MAP_URL}")
        lines.append("Costo de envío: no aplica (retiro en fábrica).")
    else:
        lines.append("Costo de envío: pendiente de confirmación del equipo.")
    if not (pieces and unit):
        lines.append("Cantidad de piezas y total: pendientes de calcular por el equipo.")
    lines.append("Borrador interno. Revisar y enviar manualmente al cliente.")
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
    elif len(days) > 2:
        names = [f"{_WEEKDAYS[d.weekday()]} {d.day}" for d in days]
        if days[0].month == days[-1].month:
            text = f"{', '.join(names[:-1])} o {_day(days[-1])}"
        else:
            text = f"{', '.join(_day(d) for d in days[:-1])} o {_day(days[-1])}"
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
                           map_url: str | None = None,
                           pickup: bool = False) -> str | None:
    """The budget the customer receives, after a person reviewed it.

    `pickup` swaps the shipping line for free factory pickup and delivers at the factory."""
    if pickup:
        shipping, address, map_url = 0, FACTORY_ADDRESS, FACTORY_MAP_URL
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
                  "Retiro en fábrica: sin costo" if pickup else
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
