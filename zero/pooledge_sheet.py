"""Consulta local no destructiva de los registros históricos de Pooledge."""
from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date
from typing import Any, List, Optional

from . import config as C

INFO_HEADER_OLD = ["NOMBRE", "TELEFONO", "FECHA DESPACHO", "RETIRO", "DIRECCION DESPACHO",
                   "DETALLES CLIENTES", "ENTREGADO", "PRECIO DESPACHO", "ABONO CLIENTE"]
PLATAS_HEADER_OLD = ["NOMBRE CLIENTE", "COSTO BASE", "VENTA", "GANANCIA", "IVA 19%",
                     "COBRADO", "COMISION DIEGO"]


class MigrationError(ValueError):
    """El origen no corresponde al formato histórico conocido."""


def _blank(value: Any) -> bool:
    return value is None or value is False or (isinstance(value, str) and not value.strip())


def validate_source(info_values: List[List[Any]], platas_values: List[List[Any]]) -> None:
    for tab, rows, expected in ((C.POOLEDGE_TAB_INFO, info_values, INFO_HEADER_OLD),
                                (C.POOLEDGE_TAB_PLATAS, platas_values, PLATAS_HEADER_OLD)):
        header = list(rows[0]) if rows else []
        while header and _blank(header[-1]):
            header.pop()
        if header != expected:
            raise MigrationError(f"{tab}: encabezado histórico no reconocido")


@dataclass
class HistoricalView:
    today: date
    info_rows: List[dict]
    platas_rows: List[dict]
    stats: dict


def historical_view_from_grid(info_values: List[List[Any]], platas_values: List[List[Any]],
                              info_grid_data: dict, platas_grid_data: dict,
                              today: date) -> HistoricalView:
    """Adapta ambas respuestas GridData, respetando pestaña y origen A1."""
    info_sheet = _grid_sheet(info_grid_data, C.POOLEDGE_TAB_INFO)
    _grid_sheet(platas_grid_data, C.POOLEDGE_TAB_PLATAS)
    colors = {}
    for grid in info_sheet.get("data", []):
        start_row = int(grid.get("startRow", 0))
        start_column = int(grid.get("startColumn", 0))
        for row_index, row in enumerate(grid.get("rowData", [])):
            for column_index, cell in enumerate(row.get("values", [])):
                color = cell.get("userEnteredFormat", {}).get("backgroundColor")
                normalized = normalize_grid_color(color)
                if normalized is not None:
                    colors[(start_row + row_index + 1, start_column + column_index)] = normalized
    return historical_view(info_values, platas_values, today, info_colors=colors)


def _grid_sheet(grid_data: dict, expected_title: str) -> dict:
    matches = [sheet for sheet in grid_data.get("sheets", [])
               if sheet.get("properties", {}).get("title") == expected_title]
    if len(matches) != 1:
        raise MigrationError(f"GridData no corresponde a la pestaña {expected_title}")
    return matches[0]


def normalize_grid_color(color: Any) -> Optional[str]:
    """Mapea colores RGB de Sheets a nombres canónicos; solo rojo puro es red."""
    if color == "red":
        return "red"
    if not isinstance(color, dict):
        return None
    try:
        rgb = tuple(float(color.get(channel, 0)) for channel in ("red", "green", "blue"))
    except (TypeError, ValueError):
        return None
    if rgb == (1.0, 0.0, 0.0):
        return "red"
    return "#{:02x}{:02x}{:02x}".format(*(round(max(0, min(1, value)) * 255) for value in rgb))


def historical_view(info_values: List[List[Any]], platas_values: List[List[Any]], today: date,
                    *, info_colors: Optional[dict] = None) -> HistoricalView:
    """Conserva filas/fuentes; el color rojo solo cuenta si fue provisto explícitamente."""
    validate_source(info_values, platas_values)
    colors = info_colors or {}
    info = []
    for source_row, values in enumerate(info_values[1:], 2):
        cells = list(values[:len(INFO_HEADER_OLD)])
        if all(_blank(v) for v in cells):
            continue
        explicit_red = colors.get((source_row, 0)) == "red"
        info.append({"source_row": source_row, "values": cells,
                     "status": "presupuesto abandonado/no respondió" if explicit_red else "pendiente/no disponible",
                     "status_signal": "color rojo explícito" if explicit_red else "sin señal de color disponible"})
    platas = []
    for source_row, values in enumerate(platas_values[1:], 2):
        cells = list(values[:len(PLATAS_HEADER_OLD)])
        if not all(_blank(v) for v in cells):
            platas.append({"source_row": source_row, "values": cells})
    return HistoricalView(today, info, platas, {"filas_info": len(info), "filas_platas": len(platas),
                                                   "datos_operativos": False})


def render_preview_html(view: HistoricalView) -> str:
    esc = lambda value: html.escape("" if value is None else str(value))
    out = ["<!doctype html><html lang='es'><meta charset='utf-8'><title>Consulta histórica Pooledge</title>",
           "<h1>Consulta histórica — Pooledge</h1>",
           "<p>Sin datos operativos: no crea clientes, pedidos, ventas, comisiones ni entregas.</p>",
           "<p>Estados no inferidos. Una fecha antigua no significa entregado. Rojo solo si existe señal explícita.</p>",
           "<h2>INFO histórico</h2><table><tr><th>Fila fuente</th><th>Datos originales</th><th>Estado</th><th>Señal</th></tr>"]
    for row in view.info_rows:
        vals = " | ".join(esc(v) for v in row["values"])
        out.append(f"<tr><td>{row['source_row']}</td><td>{vals}</td><td>{esc(row['status'])}</td><td>{esc(row['status_signal'])}</td></tr>")
    out.append("</table><h2>PLATAS histórico</h2><table><tr><th>Fila fuente</th><th>Datos originales</th></tr>")
    for row in view.platas_rows:
        out.append(f"<tr><td>{row['source_row']}</td><td>{' | '.join(esc(v) for v in row['values'])}</td></tr>")
    return "".join(out) + "</table></html>"
