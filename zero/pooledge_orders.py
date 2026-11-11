"""Órdenes de Pooledge: transforma un draft completado en filas para la planilla.

Lógica pura, sin I/O. Se usa desde `zero/losetas_review.py` cuando el dueño responde "ok"
a la vista previa que publica el bot en el grupo de revisión.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from .config import POOLEDGE_ORDER_ID_DIGITS, POOLEDGE_ORDER_ID_PREFIX

_ORDER_ID = re.compile(re.escape(POOLEDGE_ORDER_ID_PREFIX) + r"(\d+)")
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


class OrderError(ValueError):
    """Datos insuficientes o inconsistentes para escribir el pedido."""


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def _safe_text(text: Any) -> str:
    """Texto de WhatsApp para una celda USER_ENTERED: nunca se interpreta como fórmula."""
    text = str(text or "")
    return "'" + text if text.startswith(_FORMULA_START) else text


def next_order_id(existing_ids: list[Any]) -> str:
    """PE-0001, PE-0002...: el máximo número existente (patrón PE-<dígitos>) + 1."""
    numbers = []
    for raw in existing_ids:
        found = _ORDER_ID.fullmatch(str(raw or "").strip())
        if found:
            numbers.append(int(found.group(1)))
    number = max(numbers) + 1 if numbers else 1
    return f"{POOLEDGE_ORDER_ID_PREFIX}{number:0{POOLEDGE_ORDER_ID_DIGITS}d}"


INFO_DATA_COLUMNS = (0, 1, 2, 3, 4, 5, 7, 8, 9)   # A:F y H:J; G es casilla (FALSE/vacía)
PLATAS_DATA_COLUMNS = (0, 1, 3, 4)                  # A, B, D, E; C es fórmula


def first_free_row(rows: list[list[Any]], columns: tuple[int, ...]) -> int:
    """Primera fila (número de hoja, >= 2) con todas las `columns` vacías.

    `rows` es la lectura de la pestaña desde la fila 1: el índice i es la fila i+1.
    Las filas faltantes al final cuentan como vacías.
    """
    for index in range(1, len(rows)):
        row = rows[index]
        if not any(i < len(row) and str(row[i]).strip() for i in columns):
            return index + 1
    return max(len(rows), 1) + 1


def find_order_row(rows: list[list[Any]], order_id: str, column: int = 9) -> int | None:
    """Número de fila de hoja (lectura desde la fila 1) donde `column` trae `order_id`."""
    for index in range(1, len(rows)):
        row = rows[index]
        if len(row) > column and str(row[column]).strip() == order_id:
            return index + 1
    return None


def existing_order_ids(rows: list[list[Any]], column: int = 9) -> list[str]:
    return [str(row[column]).strip() for row in rows[1:] if len(row) > column and row[column]]


def _first_delivery(fields: dict[str, Any]) -> date:
    delivery = fields.get("delivery")
    if not delivery:
        raise OrderError("falta fecha de entrega")
    try:
        return min(d if isinstance(d, date) else date.fromisoformat(d) for d in delivery)
    except (TypeError, ValueError) as exc:
        raise OrderError("fecha de entrega inválida") from exc


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
    draft: dict[str, Any], fields: dict[str, Any], order_id: str
) -> dict[str, list]:
    """
    Arma las dos filas listas para escribir en la planilla.

    Args:
        draft: el draft guardado (claves: quote, name, phone, color, issued, ...).
        fields: lo que se guarda en `draft["fields"]` tras `final_published` (address,
                place, delivery, shipping, pickup, ...). `delivery` acepta fechas ISO o date.
        order_id: ID ya calculado con `next_order_id`.

    Returns:
        {"info_row": A:J, "platas_row": A:E, "order_id": ...}. De `platas_row` el bot
        escribe solo A:B y D:E: la columna C es una fórmula de columna completa.

    Raises:
        OrderError: si faltan datos obligatorios.
    """
    quote = draft.get("quote") or {}
    name = _safe_text(draft.get("name"))
    phone = _digits(draft.get("phone") or "")
    # Validaciones
    if not phone:
        raise OrderError("el draft no tiene teléfono")
    if not fields.get("pickup"):
        if not fields.get("address"):
            raise OrderError("falta dirección de despacho")
        if fields.get("shipping") is None:
            raise OrderError("falta monto de despacho")

    first_del = _first_delivery(fields)
    fecha_str = first_del.isoformat()
    detail = _safe_text(_detail_from_quote(quote))
    venta_neta = quote.get("subtotal", 0)
    shipping = fields.get("shipping") or 0
    pickup = "Sí" if fields.get("pickup") else "No"
    delivery_detail = _safe_text(quote.get("delivery_detail"))

    # INFO PEDIDOS POOLEDGE: A..J (10 columnas)
    # A NOMBRE, B TELEFONO, C FECHA DESPACHO, D RETIRO, E DIRECCION,
    # F DETALLES, G ENTREGADO, H PRECIO DESPACHO, I ABONO, J ID PEDIDO
    info_row = [
        name,                           # A NOMBRE
        "'" + phone,                    # B TELEFONO (texto, no número)
        fecha_str,                      # C FECHA DESPACHO
        pickup,                         # D RETIRO
        _safe_text(fields.get("address")),  # E DIRECCION DESPACHO
        delivery_detail,                # F DETALLES CLIENTES
        False,                          # G ENTREGADO (casilla)
        shipping,                       # H PRECIO DESPACHO
        0,                              # I ABONO CLIENTE
        order_id,                       # J ID PEDIDO
    ]

    # PLATAS 2026: A ID PEDIDO, B FECHA, C CLIENTE (fórmula, no se escribe),
    # D DETALLE, E VENTA NETA (productos sin IVA ni despacho)
    platas_row = [order_id, fecha_str, name, detail, venta_neta]

    return {"info_row": info_row, "platas_row": platas_row, "order_id": order_id}
