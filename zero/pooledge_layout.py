"""Estructura operativa de la planilla de pedidos de Pooledge (lógica pura, sin I/O).

Arma el PLAN para crear tres pestañas nuevas (PLATAS 2026, RESUMEN, COBRANZA) y
preparar las columnas nuevas de INFO. Nada se ejecuta aquí: `scripts/pooledge_estructura.py`
muestra el plan (--preview) y lo aplica (--apply) contra la planilla real.

Reglas del plan:
- Ninguna celda con datos existente se modifica. De INFO solo se toca J1 (encabezado
  "ID PEDIDO", vacío hoy), el checkbox de ENTREGADO (G) y el formato CLP de H:I,
  y estos dos últimos únicamente desde la primera fila nueva (`info_last_row + 1`).
- Nunca se sobrescribe: si alguna pestaña destino ya existe, LayoutError.
- Las tasas (IVA, comisión) salen de `zero/config.py` al construir el plan.

IMPORTANTE para quien escriba pedidos en PLATAS 2026: NO usar `values.append`. Los
checkbox de COBRADO (M) con FALSE extienden la "tabla" hasta la fila N y el append
escribiría debajo de todo. El flujo debe escribir A:F en la primera fila con A vacía.
Las columnas G:L son una ARRAYFORMULA por columna en la fila 1: no se escriben a mano.

Techo: el formato, las validaciones y las fórmulas llegan hasta la fila POOLEDGE_FORMAT_ROWS
(1000), es decir 999 pedidos en PLATAS 2026. Pasado ese techo hay que ampliar el plan.
El ID PEDIDO es SIEMPRE texto: formato de texto plano "@" en PLATAS 2026!A y en INFO!J
(desde la primera fila nueva).

Todo se aplica en UN solo batchUpdate: los valores viajan como requests `updateCells`
después de los addSheet, así la estructura se aplica entera o no se aplica.
"""
from __future__ import annotations

import hashlib
import html
import json
from typing import Any, Dict, List

from . import config as C
from .sheets import quote_tab

_FIRST_NEW_SHEET_ID = 2026001
_PLATAS_COLS = 14  # A..N
_TEXT = {"type": "TEXT", "pattern": "@"}
_INFO_COL_J = 9    # índice 0-based de J
_INFO_COL_G = 6
_INFO_COL_H = 7
_INFO_COL_I = 9    # exclusivo (H:I)

_CLP = {"type": "CURRENCY", "pattern": '"$"#,##0'}
_DATE = {"type": "DATE", "pattern": "dd-mm-yyyy"}

_GREEN = {"red": 0.72, "green": 0.88, "blue": 0.76}
_AMBER = {"red": 1.0, "green": 0.88, "blue": 0.55}
_GRAY = {"red": 0.85, "green": 0.85, "blue": 0.85}
_HEADER_BG = {"red": 0.93, "green": 0.87, "blue": 0.73}

_ENTRY_HEADERS = ["ID PEDIDO", "FECHA", "CLIENTE", "DETALLE", "COSTO BASE NETO", "VENTA NETA"]
_TAIL_HEADERS = ["COBRADO", "FECHA COBRO"]


class LayoutError(ValueError):
    """El plan no se puede construir sin riesgo (falta origen o ya existe destino)."""


def _num(x: float) -> str:
    """Número con punto decimal, sin notación científica, para una fórmula."""
    return f"{x:.10f}".rstrip("0").rstrip(".")


def col_letter(index: int) -> str:
    """Índice 0-based de columna -> letra A1 (0 -> A, 26 -> AA)."""
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def _col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch) - 64
    return n - 1


def _rng(sheet_id: int, r1: int, r2: int, c1: int, c2: int) -> Dict[str, int]:
    return {"sheetId": sheet_id, "startRowIndex": r1, "endRowIndex": r2,
            "startColumnIndex": c1, "endColumnIndex": c2}


def _fmt(rng: Dict[str, int], user_format: Dict[str, Any], fields: str) -> Dict[str, Any]:
    return {"repeatCell": {"range": rng, "cell": {"userEnteredFormat": user_format},
                           "fields": f"userEnteredFormat({fields})"}}


def _bold_header(sheet_id: int, row: int, c1: int, c2: int) -> Dict[str, Any]:
    return _fmt(_rng(sheet_id, row, row + 1, c1, c2),
                {"textFormat": {"bold": True}, "backgroundColor": _HEADER_BG},
                "textFormat,backgroundColor")


def _number_fmt(rng: Dict[str, int], nf: Dict[str, str]) -> Dict[str, Any]:
    return {"repeatCell": {"range": rng, "cell": {"userEnteredFormat": {"numberFormat": nf}},
                           "fields": "userEnteredFormat.numberFormat"}}


def _checkbox(rng: Dict[str, int]) -> Dict[str, Any]:
    return {"setDataValidation": {"range": rng, "rule": {
        "condition": {"type": "BOOLEAN"}, "strict": True}}}


def _platas_formulas() -> Dict[str, str]:
    iva = _num(C.IVA_RATE)
    com = _num(C.POOLEDGE_COMMISSION_RATE)
    cobrada, por_cobrar, futura = C.POOLEDGE_COMMISSION_STATES
    info = quote_tab(C.POOLEDGE_TAB_INFO)

    def arr(title: str, expr: str) -> str:
        return '={"%s";ARRAYFORMULA(%s)}' % (title, expr)

    return {
        "G": arr("IVA", f'IF(A2:A="",,F2:F*{iva})'),
        "H": arr("TOTAL", f'IF(A2:A="",,F2:F+F2:F*{iva})'),
        "I": arr("GANANCIA", 'IF(A2:A="",,IF(E2:E="",,F2:F-E2:E))'),
        "J": arr("COMISIÓN DIEGO", f'IF(A2:A="",,F2:F*{com})'),
        "K": arr("ENTREGADO",
                 f'IF(A2:A="",,IFERROR(VLOOKUP(A2:A,{{{info}!J2:J,{info}!G2:G}},2,FALSE),FALSE))'),
        "L": arr("ESTADO COMISIÓN",
                 f'IF(A2:A="","",IF(M2:M=TRUE,"{cobrada}",IF(K2:K=TRUE,"{por_cobrar}","{futura}")))'),
    }


def _resumen_values() -> List[Dict[str, Any]]:
    p = quote_tab(C.POOLEDGE_TAB_PLATAS_NEW)
    tab = quote_tab(C.POOLEDGE_TAB_RESUMEN)
    cobrada, por_cobrar, futura = C.POOLEDGE_COMMISSION_STATES
    src = f'{p}!B2:B,"yyyy-mm"'
    monthly = (
        f'=IFERROR(QUERY(FILTER({{ARRAYFORMULA(TEXT({src})),{p}!A2:A,{p}!F2:F,{p}!I2:I,{p}!J2:J}},'
        f'{p}!A2:A<>""),'
        '"select Col1, count(Col2), sum(Col3), sum(Col4), sum(Col5) group by Col1 order by Col1 '
        "label Col1 'Mes', count(Col2) 'Pedidos', sum(Col3) 'Venta neta', "
        "sum(Col4) 'Ganancia', sum(Col5) 'Comisión'\",0),\"Sin pedidos\")"
    )
    sumifs = lambda state: f'=SUMIFS({p}!J2:J,{p}!L2:L,"{state}")'  # noqa: E731
    return [
        {"range": f"{tab}!A1", "values": [[
            f"Solo pedidos desde {C.POOLEDGE_TAB_PLATAS_NEW}; el histórico queda en {C.POOLEDGE_TAB_PLATAS}."]]},
        {"range": f"{tab}!A3:B3", "values": [["TOTALES", ""]]},
        {"range": f"{tab}!A4:B8", "values": [
            [f"Comisión {cobrada.lower()}", sumifs(cobrada)],
            [f"Comisión {por_cobrar.lower()}", sumifs(por_cobrar)],
            [f"Comisión {futura.lower()}", sumifs(futura)],
            ["Venta neta total", f"=SUM({p}!F2:F)"],
            ["Pedidos", f"=COUNTA({p}!A2:A)"],
        ]},
        {"range": f"{tab}!D3", "values": [[monthly]]},
    ]


def _cobranza_values() -> List[Dict[str, Any]]:
    p = quote_tab(C.POOLEDGE_TAB_PLATAS_NEW)
    tab = quote_tab(C.POOLEDGE_TAB_COBRANZA)
    cobrada = C.POOLEDGE_COMMISSION_STATES[0]

    def block(cond: str, select: str, order: str, labels: str) -> str:
        return (
            f'=IFERROR(QUERY(FILTER({p}!A2:N,{p}!A2:A<>"",{cond}),'
            f'"select {select} order by {order} label {labels}",0),"Sin pedidos")'
        )

    pend = block(f'{p}!L2:L<>"{cobrada}"', "Col1, Col2, Col3, Col10, Col12", "Col2",
                 "Col1 'ID PEDIDO', Col2 'FECHA', Col3 'CLIENTE', Col10 'COMISIÓN', Col12 'ESTADO'")
    paid = block(f'{p}!L2:L="{cobrada}"', "Col1, Col2, Col3, Col10, Col14", "Col14",
                 "Col1 'ID PEDIDO', Col2 'FECHA', Col3 'CLIENTE', Col10 'COMISIÓN', Col14 'FECHA COBRO'")
    return [
        {"range": f"{tab}!A1", "values": [[
            "La pestaña COBRADO Y NO COBRADO queda como archivo histórico."]]},
        {"range": f"{tab}!A3", "values": [["PENDIENTES"]]},
        {"range": f"{tab}!G3", "values": [["COBRADAS"]]},
        {"range": f"{tab}!A4", "values": [[pend]]},
        {"range": f"{tab}!G4", "values": [[paid]]},
    ]


def _values_to_requests(values: List[Dict[str, Any]], ids_by_title: Dict[str, int]) -> List[Dict[str, Any]]:
    """Cada {"range","values"} -> request updateCells (fórmula si empieza con "=", texto si no)."""
    out = []
    for v in values:
        title, cell = v["range"].rsplit("!", 1)
        title = title[1:-1].replace("''", "'")
        letters = "".join(ch for ch in cell.split(":")[0] if ch.isalpha())
        row = int("".join(ch for ch in cell.split(":")[0] if ch.isdigit())) - 1
        rows = []
        for r in v["values"]:
            cells = []
            for c in r:
                key = "formulaValue" if isinstance(c, str) and c.startswith("=") else "stringValue"
                cells.append({"userEnteredValue": {key: c}})
            rows.append({"values": cells})
        out.append({"updateCells": {
            "rows": rows,
            "start": {"sheetId": ids_by_title[title], "rowIndex": row, "columnIndex": _col_index(letters)},
            "fields": "userEnteredValue"}})
    return out


def build_plan(meta: dict, info_last_row: int, info_j_nonempty: int = 0) -> dict:
    """Plan determinista y JSON-serializable: requests de batchUpdate + valores.

    `meta`: resultado de sheets.get_sheet_meta. `info_last_row`: última fila (1-based)
    con CUALQUIER dato en INFO!A:I; las filas posteriores son las "nuevas".
    `info_j_nonempty`: cuántas celdas de INFO!J:J tienen contenido (solo el conteo);
    si hay alguna, LayoutError. Ambos números entran al plan y por tanto a la huella.
    """
    if not isinstance(info_last_row, int) or isinstance(info_last_row, bool) or info_last_row < 1:
        raise LayoutError("info_last_row inválido")
    if not isinstance(info_j_nonempty, int) or isinstance(info_j_nonempty, bool) or info_j_nonempty < 0:
        raise LayoutError("info_j_nonempty inválido")
    if info_j_nonempty:
        raise LayoutError("la columna J de INFO ya tiene contenido: no se sobrescribe")
    props = [s.get("properties", {}) for s in meta.get("sheets", [])]
    titles = {p.get("title") for p in props}
    for needed in (C.POOLEDGE_TAB_INFO, C.POOLEDGE_TAB_PLATAS):
        if needed not in titles:
            raise LayoutError(f"falta la pestaña de origen {needed!r}")
    new_tabs = (C.POOLEDGE_TAB_PLATAS_NEW, C.POOLEDGE_TAB_RESUMEN, C.POOLEDGE_TAB_COBRANZA)
    for t in new_tabs:
        if t in titles:
            raise LayoutError(f"la pestaña destino {t!r} ya existe: no se sobrescribe")

    used = {p.get("sheetId") for p in props}
    ids: Dict[str, int] = {}
    candidate = _FIRST_NEW_SHEET_ID
    for t in new_tabs:
        while candidate in used:
            candidate += 1
        ids[t] = candidate
        used.add(candidate)
    pid, rid, cid = (ids[t] for t in new_tabs)

    info = next(p for p in props if p.get("title") == C.POOLEDGE_TAB_INFO)
    grid = info.get("gridProperties", {})
    if grid.get("columnCount", _INFO_COL_J + 1) < _INFO_COL_J + 1:
        raise LayoutError("INFO no tiene columna J")
    info_sid = info["sheetId"]
    first_new = info_last_row + 1
    n = C.POOLEDGE_FORMAT_ROWS
    info_end = min(n, grid.get("rowCount", n))
    if first_new > info_end:
        raise LayoutError("INFO no tiene filas libres para formato")

    reqs: List[Dict[str, Any]] = []
    for t, sid, cols, frozen in ((new_tabs[0], pid, _PLATAS_COLS, 1),
                                 (new_tabs[1], rid, 8, 0),
                                 (new_tabs[2], cid, 11, 0)):
        gp: Dict[str, Any] = {"rowCount": n, "columnCount": cols}
        if frozen:
            gp["frozenRowCount"] = frozen
        reqs.append({"addSheet": {"properties": {"sheetId": sid, "title": t, "gridProperties": gp}}})

    # PLATAS 2026
    reqs.append(_bold_header(pid, 0, 0, _PLATAS_COLS))
    reqs.append(_number_fmt(_rng(pid, 1, n, 1, 2), _DATE))
    reqs.append(_number_fmt(_rng(pid, 1, n, 13, 14), _DATE))
    reqs.append(_number_fmt(_rng(pid, 1, n, 4, 10), _CLP))
    reqs.append(_number_fmt(_rng(pid, 0, n, 0, 1), _TEXT))
    reqs.append(_checkbox(_rng(pid, 1, n, 12, 13)))
    reqs.append({"addProtectedRange": {"protectedRange": {
        "range": _rng(pid, 0, n, 6, 12), "warningOnly": True,
        "description": "Columnas calculadas (ARRAYFORMULA en la fila 1)"}}})
    for i, (state, color) in enumerate(zip(C.POOLEDGE_COMMISSION_STATES, (_GREEN, _AMBER, _GRAY))):
        reqs.append({"addConditionalFormatRule": {"index": i, "rule": {
            "ranges": [_rng(pid, 1, n, 11, 12)],
            "booleanRule": {"condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": state}]},
                            "format": {"backgroundColor": color}}}}})

    if not C.POOLEDGE_SHOW_IVA:
        # G (IVA) y H (TOTAL) ocultas, no borradas: así ninguna referencia se corre.
        reqs.append({"updateDimensionProperties": {
            "range": {"sheetId": pid, "dimension": "COLUMNS", "startIndex": 6, "endIndex": 8},
            "properties": {"hiddenByUser": True}, "fields": "hiddenByUser"}})

    # RESUMEN
    reqs.append(_bold_header(rid, 2, 0, 2))
    reqs.append(_bold_header(rid, 2, 3, 8))
    reqs.append(_number_fmt(_rng(rid, 3, 7, 1, 2), _CLP))
    reqs.append(_number_fmt(_rng(rid, 3, n, 5, 8), _CLP))

    # COBRANZA
    reqs.append(_bold_header(cid, 2, 0, 5))
    reqs.append(_bold_header(cid, 2, 6, 11))
    reqs.append(_bold_header(cid, 3, 0, 5))
    reqs.append(_bold_header(cid, 3, 6, 11))
    reqs.append(_number_fmt(_rng(cid, 4, n, 1, 2), _DATE))
    reqs.append(_number_fmt(_rng(cid, 4, n, 3, 4), _CLP))
    reqs.append(_number_fmt(_rng(cid, 4, n, 7, 8), _DATE))
    reqs.append(_number_fmt(_rng(cid, 4, n, 9, 10), _CLP))
    reqs.append(_number_fmt(_rng(cid, 4, n, 10, 11), _DATE))

    # INFO: J1 y, desde la primera fila nueva, checkbox en G y CLP en H:I.
    reqs.append(_bold_header(info_sid, 0, _INFO_COL_J, _INFO_COL_J + 1))
    reqs.append(_checkbox(_rng(info_sid, first_new - 1, info_end, _INFO_COL_G, _INFO_COL_G + 1)))
    reqs.append(_number_fmt(_rng(info_sid, first_new - 1, info_end, _INFO_COL_H, _INFO_COL_I), _CLP))
    reqs.append(_number_fmt(_rng(info_sid, first_new - 1, info_end, _INFO_COL_J, _INFO_COL_J + 1), _TEXT))

    p = quote_tab(C.POOLEDGE_TAB_PLATAS_NEW)
    formulas = _platas_formulas()
    values: List[Dict[str, Any]] = [
        {"range": f"{quote_tab(C.POOLEDGE_TAB_INFO)}!J1", "values": [["ID PEDIDO"]]},
        {"range": f"{p}!A1:F1", "values": [list(_ENTRY_HEADERS)]},
    ]
    values += [{"range": f"{p}!{col}1", "values": [[f]]} for col, f in formulas.items()]
    values.append({"range": f"{p}!M1:N1", "values": [list(_TAIL_HEADERS)]})
    values += _resumen_values() + _cobranza_values()

    titles_by_id = {pid: new_tabs[0], rid: new_tabs[1], cid: new_tabs[2], info_sid: C.POOLEDGE_TAB_INFO}
    reqs += _values_to_requests(values, {t: i for i, t in titles_by_id.items()})

    summary = {
        "tabs_to_create": list(new_tabs),
        "sheet_ids": {t: ids[t] for t in new_tabs},
        "sheet_titles": {str(i): t for i, t in titles_by_id.items()},
        "info_last_row": info_last_row,
        "info_j_nonempty": info_j_nonempty,
        "info_end_row": info_end,
        "first_new_row": first_new,
        "format_rows": n,
        "validations": [
            f"{C.POOLEDGE_TAB_PLATAS_NEW}!M2:M{n}: checkbox (COBRADO)",
            f"{C.POOLEDGE_TAB_INFO}!G{first_new}:G{info_end}: checkbox (ENTREGADO), solo filas nuevas",
        ],
        "formats": [
            f"{C.POOLEDGE_TAB_PLATAS_NEW}: encabezados en negrita, fila 1 congelada",
            f"{C.POOLEDGE_TAB_PLATAS_NEW}!B y N: fecha dd-mm-yyyy; E:J: CLP",
            f"{C.POOLEDGE_TAB_PLATAS_NEW}!L: color según estado "
            + ", ".join(C.POOLEDGE_COMMISSION_STATES) + " (verde, ámbar, gris)",
            f"{C.POOLEDGE_TAB_PLATAS_NEW}!G:L: protección de advertencia (calculadas)",
            *([] if C.POOLEDGE_SHOW_IVA else
              [f"{C.POOLEDGE_TAB_PLATAS_NEW}!G:H (IVA y TOTAL): ocultas por ahora"]),
            f"{C.POOLEDGE_TAB_RESUMEN} y {C.POOLEDGE_TAB_COBRANZA}: encabezados, fechas y CLP",
            f"{C.POOLEDGE_TAB_INFO}!H{first_new}:I{info_end}: CLP, solo filas nuevas",
            f"ID PEDIDO es siempre texto (formato '@'): {C.POOLEDGE_TAB_PLATAS_NEW}!A y "
            f"{C.POOLEDGE_TAB_INFO}!J{first_new}:J{info_end}",
            f"Techo: formato y fórmulas hasta la fila {n} ({n - 1} pedidos)",
        ],
        "info_cells": [
            f"{C.POOLEDGE_TAB_INFO}!J1: encabezado 'ID PEDIDO' (hoy vacía) y su negrita",
            f"{C.POOLEDGE_TAB_INFO}!G{first_new}:G{info_end}: validación checkbox",
            f"{C.POOLEDGE_TAB_INFO}!H{first_new}:I{info_end}: formato CLP",
            f"{C.POOLEDGE_TAB_INFO}!J{first_new}:J{info_end}: formato texto",
        ],
        "n_requests": len(reqs),
        "n_value_ranges": len(values),
    }
    return {"requests": reqs, "summary": summary}


def plan_fingerprint(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _example_row() -> List[int]:
    cost, sale = 100_000, 150_000
    iva = round(sale * C.IVA_RATE)
    return [cost, sale, iva, sale + iva, sale - cost, round(sale * C.POOLEDGE_COMMISSION_RATE)]


def render_plan_html(plan: dict) -> str:
    """HTML autocontenido para que una persona revise el plan. Sin datos de la hoja."""
    e = html.escape
    s = plan["summary"]

    def ul(items):
        return "<ul>" + "".join(f"<li>{e(str(i))}</li>" for i in items) + "</ul>"

    titles = s["sheet_titles"]
    cells = []
    for r in plan["requests"]:
        uc = r.get("updateCells")
        if not uc:
            continue
        st = uc["start"]
        for i, row in enumerate(uc["rows"]):
            for j, cell in enumerate(row["values"]):
                ref = f"{titles[str(st['sheetId'])]}!{col_letter(st['columnIndex'] + j)}{st['rowIndex'] + i + 1}"
                val = next(iter(cell["userEnteredValue"].values()))
                cells.append(f"<tr><td><code>{e(ref)}</code></td><td><code>{e(str(val))}</code></td></tr>")
    rows = "".join(cells)
    cost, sale, iva, total, gain, com = _example_row()
    money = lambda x: e(f"${x:,.0f}".replace(",", "."))  # noqa: E731
    example = (
        "<table><tr><th>COSTO BASE NETO</th><th>VENTA NETA</th><th>IVA</th><th>TOTAL</th>"
        "<th>GANANCIA</th><th>COMISIÓN DIEGO</th></tr><tr>"
        + "".join(f"<td>{money(x)}</td>" for x in (cost, sale, iva, total, gain, com))
        + "</tr></table>")
    css = ("body{font-family:sans-serif;max-width:960px;margin:2em auto;padding:0 1em}"
           "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px;text-align:left}"
           "code{font-size:12px;word-break:break-all}")
    return (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        "<title>Estructura Pooledge: plan</title>"
        f"<style>{css}</style></head><body>"
        "<h1>Estructura operativa de Pooledge: plan (sin aplicar)</h1>"
        f"<p>Requests: {s['n_requests']}. Celdas con contenido en {s['n_value_ranges']} rangos. "
        f"Huella: <code>{e(plan_fingerprint(plan))}</code></p>"
        "<h2>Pestañas a crear</h2>" + ul(s["tabs_to_create"])
        + "<h2>Encabezados y fórmulas (valores a escribir)</h2>"
        "<table><tr><th>Rango</th><th>Contenido</th></tr>" + rows + "</table>"
        "<h2>Validaciones</h2>" + ul(s["validations"])
        + "<h2>Formatos</h2>" + ul(s["formats"])
        + "<h2>Celdas de INFO que se tocan</h2>" + ul(s["info_cells"])
        + f"<p>INFO: filas con datos hasta la {e(str(s['info_last_row']))}; "
        f"las filas nuevas empiezan en la {e(str(s['first_new_row']))}. "
        "Ninguna celda existente cambia de valor.</p>"
        "<h2>Ejemplo sintético</h2>" + example
        + "</body></html>")
