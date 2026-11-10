"""Órdenes de Pooledge: transforma un draft completado en filas para la planilla.

Lógica pura, sin I/O. Se usa desde `zero/losetas_review.py` cuando el dueño responde "ok"
a la vista previa que publica el bot en el grupo de revisión.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from . import config as C
from .sheets import quote_tab


class OrderError(ValueError):
    """Datos insuficientes o inconsistentes para escribir el pedido."""


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _fmt_cl_date(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def next_order_id(phone: str, issued: date) -> str:
    """PE-ddmmyy-XXXX con últimos 4 dígitos del teléfono y fecha en zona WhatsApp."""
    return f"PE-{issued:%d%m%y}-{_digits(phone)[-4:].rjust(4, '0')}"


def _first_delivery(fields: dict[str, Any]) -> date:
    delivery = fields.get("delivery")
    if not delivery:
        raise OrderError("falta fecha de entrega")
    return min(delivery)


def _detail_from_quote(quote: dict[str, Any]) -> str:
    lines = quote.get("lines") or []
    if not lines:
        return ""
    parts = []
    for ln in lines:
        qty = ln.get("qty")
        name = ln.get("name") or ""
        if qty is not None:
            parts.append(f"{qty} x {name}")
        else:
            parts.append(name)
    return "\n".join(parts)


def build_order_rows(
    draft: dict[str, Any], fields: dict[str, Any]
) -> dict[str, list]:
    """
    Arma las dos filas listas para escribir en la planilla.

    Args:
        draft: el draft guardado (claves: quote, name, phone, color, issued, ...).
        fields: el resultado de `read_owner_reply` (address, place, delivery, shipping,
                pool, map_url, pickup, ...). Lo que se guarda en `draft["fields"]` tras
                `final_published`.

    Returns:
        {"info_row": [...], "platas_row": [...], "order_id": "PE-..."}

    Raises:
        OrderError: si faltan datos obligatorios.
    """
    quote = draft.get("quote") or {}
    name = draft.get("name") or ""
    phone = _digits(draft.get("phone") or "")
    color = draft.get("color") or ""
    issued_raw = draft.get("issued")
    if not issued_raw:
        raise OrderError("el draft no tiene fecha de emisión")
    issued = date.fromisoformat(issued_raw) if isinstance(issued_raw, str) else issued_raw

    # Validaciones
    if not phone:
        raise OrderError("el draft no tiene teléfono")
    if not fields.get("pickup"):
        if not fields.get("address"):
            raise OrderError("falta dirección de despacho")
        if fields.get("shipping") is None:
            raise OrderError("falta monto de despacho")

    order_id = next_order_id(phone, issued)
    first_del = _first_delivery(fields)
    fecha_str = _fmt_cl_date(first_del)
    detail = _detail_from_quote(quote)
    venta_neta = quote.get("subtotal", 0)
    shipping = fields.get("shipping") or 0
    pickup = "Sí" if fields.get("pickup") else "No"
    delivery_detail = quote.get("delivery_detail") or ""

    # INFO PEDIDOS POOLEDGE: A..J (10 columnas)
    # A NOMBRE, B TELEFONO, C FECHA DESPACHO, D RETIRO, E DIRECCION,
    # F DETALLES, G ENTREGADO, H PRECIO DESPACHO, I ABONO, J ID PEDIDO
    info_row = [
        name,                           # A NOMBRE
        phone,                          # B TELEFONO
        fecha_str,                      # C FECHA DESPACHO
        pickup,                         # D RETIRO
        fields.get("address") or "",    # E DIRECCION DESPACHO
        delivery_detail,                # F DETALLES CLIENTES
        False,                          # G ENTREGADO
        shipping,                       # H PRECIO DESPACHO
        0,                              # I ABONO CLIENTE
        order_id,                       # J ID PEDIDO
    ]

    # PLATAS 2026: A..F (6 columnas)
    # A ID PEDIDO, B FECHA, C CLIENTE, D DETALLE, E VENTA NETA, F (vacío)
    platas_row = [
        order_id,                       # A ID PEDIDO
        fecha_str,                      # B FECHA
        name,                           # C CLIENTE
        detail,                         # D DETALLE
        venta_neta,                     # E VENTA NETA
        "",                             # F (vacío - antes costo base)
    ]

    return {"info_row": info_row, "platas_row": platas_row, "order_id": order_id}