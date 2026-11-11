"""Estructura operativa de la planilla de pedidos de Pooledge (lógica pura, sin I/O).

Arma el PLAN para crear tres pestañas nuevas (PLATAS 2026, RESUMEN, COBRANZA), dejar
INFO PEDIDOS lista para los ID y darle estilo a INFO y PRECIOS PRODUCTOS, según la ficha
técnica de diseño. Nada se ejecuta aquí: `scripts/pooledge_estructura.py` muestra el
plan (--preview) y lo aplica (--apply) contra la planilla real.

Reglas del plan:
- Ningún valor de celda de datos existente se modifica. De INFO solo se escribe J1
  ("ID PEDIDO", vacío hoy); de ahí en más son validaciones y estilos. PRECIOS: solo estilo.
- Nunca se sobrescribe: si alguna pestaña destino ya existe, LayoutError.
- La tasa de comisión y los estados salen de `zero/config.py` al construir el plan.
- IVA y TOTAL no existen. COSTO BASE NETO y GANANCIA existen solo con
  `config.POOLEDGE_TRACK_COST` y siempre AL FINAL (K, L).

FÓRMULAS: se escriben por la API Sheets v4 con USER_ENTERED, que usa sintaxis INGLESA
(coma como separador de argumentos y punto decimal). La ficha trae `;` y `0,1` porque
está pensada para teclear a mano con la configuración regional de Chile: NO copiarla tal
cual aquí.

Las letras de PLATAS 2026 salen de UNA sola definición (`platas_columns`); ninguna
fórmula, rango o formato de PLATAS, RESUMEN o COBRANZA lleva una letra escrita a mano.

IMPORTANTE para quien escriba pedidos en PLATAS 2026: NO usar `values.append` (la casilla
de COBRADO extiende la "tabla" hasta el final y el append escribiría debajo de todo).
Escribir solo las columnas manuales (A, B, D, E, I, J) en la primera fila con A vacía.
Las columnas calculadas (C, F:H) son una fórmula en la fila 2 que llena toda la columna:
no se escriben a mano.

Techo: el formato, las validaciones y las fórmulas llegan hasta la fila POOLEDGE_FORMAT_ROWS
(1000), es decir 999 pedidos en PLATAS 2026. Pasado ese techo hay que ampliar el plan.

Todo se aplica en UN solo batchUpdate: los valores viajan como requests `updateCells`
después de los addSheet, así la estructura se aplica entera o no se aplica.
"""
from __future__ import annotations

import hashlib
import html
import json
from typing import Any, Dict, List, Tuple

from . import config as C
from .sheets import quote_tab

_FIRST_NEW_SHEET_ID = 2026001
_TEXT = {"type": "TEXT", "pattern": "@"}
_INFO_COL_J = 9    # índice 0-based de J
_INFO_COL_G = 6
_INFO_COL_H = 7
_INFO_COL_I = 8
_INFO_COL_D = 3
_INFO_COL_E = 4

_CLP = {"type": "CURRENCY", "pattern": '"$"#,##0;-"$"#,##0;"—"'}
_DATE = {"type": "DATE", "pattern": "dd-mm-yyyy"}
_COUNT = {"type": "NUMBER", "pattern": '0;-0;"—"'}
_DAYS = {"type": "NUMBER", "pattern": "0"}

# Paleta de la ficha técnica.
def _rgb(hexa: str) -> Dict[str, float]:
    return {k: int(hexa[i:i + 2], 16) / 255 for k, i in (("red", 0), ("green", 2), ("blue", 4))}


_TINTA = _rgb("1F2A2E")
_PAPEL = _rgb("FAF8F4")
_ARENA = _rgb("ECE7DD")
_BRONCE = _rgb("8A6A3B")
_PINO = _rgb("3E5C50")
_PLEX = "IBM Plex Sans"
_PLAYFAIR = "Playfair Display"

_MONTHS = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto",
           "Septiembre", "Octubre", "Noviembre", "Diciembre")

# PLATAS 2026: (clave, encabezado, ancho px). El ORDEN define las letras.
_PLATAS_BASE = (
    ("id", "ID PEDIDO", 80), ("fecha", "FECHA", 96), ("cliente", "CLIENTE", 170),
    ("detalle", "DETALLE", 240), ("venta", "VENTA NETA", 120), ("comision", "COMISIÓN", 110),
    ("entregado", "ENTREGADO", 96), ("estado", "ESTADO", 104), ("cobrado", "COBRADO", 84),
    ("fcobro", "FECHA COBRO", 104),
)
_PLATAS_COST = (("costo", "COSTO BASE NETO", 120), ("ganancia", "GANANCIA", 110))
_CALC_KEYS = frozenset({"cliente", "comision", "entregado", "estado", "ganancia"})


class LayoutError(ValueError):
    """El plan no se puede construir sin riesgo (falta origen o ya existe destino)."""


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


def platas_columns() -> List[Tuple[str, str, int]]:
    """Columnas de PLATAS 2026 en orden: (clave, encabezado, ancho). Única fuente de letras."""
    return list(_PLATAS_BASE) + (list(_PLATAS_COST) if C.POOLEDGE_TRACK_COST else [])


def platas_letters() -> Dict[str, str]:
    """clave -> letra de columna en PLATAS 2026."""
    return {key: col_letter(i) for i, (key, _, _) in enumerate(platas_columns())}


def _resumen_keys() -> List[str]:
    """Columnas de la tabla mensual de RESUMEN, desde B."""
    return ["mes", "pedidos", "venta"] + (["ganancia"] if C.POOLEDGE_TRACK_COST else []) + ["comision"]


def resumen_letters() -> Dict[str, str]:
    return {key: col_letter(1 + i) for i, key in enumerate(_resumen_keys())}


def _rng(sheet_id: int, r1: int, r2: int, c1: int, c2: int) -> Dict[str, int]:
    return {"sheetId": sheet_id, "startRowIndex": r1, "endRowIndex": r2,
            "startColumnIndex": c1, "endColumnIndex": c2}


def _fmt(rng: Dict[str, int], user_format: Dict[str, Any], *paths: str) -> Dict[str, Any]:
    """repeatCell que solo toca los subcampos de userEnteredFormat indicados."""
    return {"repeatCell": {"range": rng, "cell": {"userEnteredFormat": user_format},
                           "fields": ",".join(f"userEnteredFormat.{p}" for p in paths)}}


def _text(size: int, bold: bool = False, color: Dict[str, float] = _TINTA, font: str = _PLEX,
          italic: bool = False, underline: bool = False) -> Dict[str, Any]:
    return {"fontFamily": font, "fontSize": size, "bold": bold, "italic": italic,
            "underline": underline, "foregroundColor": color}


def _base(rng: Dict[str, int]) -> Dict[str, Any]:
    """Fondo Papel, Plex 10 Tinta, centrado vertical."""
    return _fmt(rng, {"backgroundColor": _PAPEL, "textFormat": _text(10), "verticalAlignment": "MIDDLE"},
                "backgroundColor", "textFormat", "verticalAlignment")


def _header(rng: Dict[str, int]) -> Dict[str, Any]:
    """Encabezado de tabla: Plex 9 negrita, Papel sobre Tinta, centrado vertical, con ajuste."""
    return _fmt(rng, {"backgroundColor": _TINTA, "textFormat": _text(9, True, _PAPEL),
                      "verticalAlignment": "MIDDLE", "wrapStrategy": "WRAP"},
                "backgroundColor", "textFormat", "verticalAlignment", "wrapStrategy")


def _number_fmt(rng: Dict[str, int], nf: Dict[str, str], align: str = "") -> Dict[str, Any]:
    if align:
        return _fmt(rng, {"numberFormat": nf, "horizontalAlignment": align},
                    "numberFormat", "horizontalAlignment")
    return _fmt(rng, {"numberFormat": nf}, "numberFormat")


def _align(rng: Dict[str, int], align: str, clip: bool = False) -> Dict[str, Any]:
    if clip:
        return _fmt(rng, {"horizontalAlignment": align, "wrapStrategy": "CLIP"},
                    "horizontalAlignment", "wrapStrategy")
    return _fmt(rng, {"horizontalAlignment": align}, "horizontalAlignment")


def _bold(rng: Dict[str, int]) -> Dict[str, Any]:
    return _fmt(rng, {"textFormat": {"bold": True}}, "textFormat.bold")


def _bg(rng: Dict[str, int], color: Dict[str, float]) -> Dict[str, Any]:
    return _fmt(rng, {"backgroundColor": color}, "backgroundColor")


def _checkbox(rng: Dict[str, int]) -> Dict[str, Any]:
    return {"setDataValidation": {"range": rng, "rule": {
        "condition": {"type": "BOOLEAN"}, "strict": True}}}


def _validation(rng: Dict[str, int], cond_type: str, values: Tuple[str, ...] = (),
                custom_ui: bool = False) -> Dict[str, Any]:
    condition: Dict[str, Any] = {"type": cond_type}
    if values:
        condition["values"] = [{"userEnteredValue": v} for v in values]
    return {"setDataValidation": {"range": rng, "rule": {
        "condition": condition, "strict": True, "showCustomUi": custom_ui}}}


def _border(rng: Dict[str, int], side: str, style: str, color: Dict[str, float]) -> Dict[str, Any]:
    return {"updateBorders": {"range": rng, side: {"style": style, "color": color}}}


def _dim(sheet_id: int, dimension: str, start: int, end: int, pixels: int) -> Dict[str, Any]:
    return {"updateDimensionProperties": {
        "range": {"sheetId": sheet_id, "dimension": dimension, "startIndex": start, "endIndex": end},
        "properties": {"pixelSize": pixels}, "fields": "pixelSize"}}


def _freeze(sheet_id: int, rows: int) -> Dict[str, Any]:
    return {"updateSheetProperties": {
        "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": rows}},
        "fields": "gridProperties.frozenRowCount"}}


class _Rules:
    """Reglas de formato condicional con índice correlativo por pestaña (el orden manda)."""

    def __init__(self) -> None:
        self.count: Dict[int, int] = {}
        self.out: List[Dict[str, Any]] = []

    def add(self, sheet_id: int, ranges: List[Dict[str, int]], cond: Dict[str, Any],
            fmt: Dict[str, Any]) -> None:
        i = self.count.get(sheet_id, 0)
        self.count[sheet_id] = i + 1
        self.out.append({"addConditionalFormatRule": {"index": i, "rule": {
            "ranges": ranges, "booleanRule": {"condition": cond, "format": fmt}}}})


def _eq(v: str) -> Dict[str, Any]:
    return {"type": "TEXT_EQ", "values": [{"userEnteredValue": v}]}


def _custom(formula: str) -> Dict[str, Any]:
    return {"type": "CUSTOM_FORMULA", "values": [{"userEnteredValue": formula}]}


def _gt(v: int) -> Dict[str, Any]:
    return {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": str(v)}]}


def _lt(v: int) -> Dict[str, Any]:
    return {"type": "NUMBER_LESS", "values": [{"userEnteredValue": str(v)}]}


def _platas_formulas() -> Dict[str, str]:
    """letra -> fórmula de la fila 2 (sintaxis inglesa). Solo columnas calculadas."""
    L = platas_letters()
    com = f"{C.POOLEDGE_COMMISSION_RATE:.10f}".rstrip("0").rstrip(".")
    cobrada, por_cobrar, futura = C.POOLEDGE_COMMISSION_STATES
    info = quote_tab(C.POOLEDGE_TAB_INFO)
    a, e, i, g = (f"{L[k]}2:{L[k]}" for k in ("id", "venta", "cobrado", "entregado"))
    out = {
        L["cliente"]: f'=MAP({a}, LAMBDA(id, IF(id="","", XLOOKUP(id, {info}!J:J, {info}!A:A, "ID no existe"))))',
        L["comision"]: f'=ARRAYFORMULA(IF({a}="",,ROUND({e}*{com})))',
        L["entregado"]: (f'=MAP({a}, LAMBDA(id, IF(id="","", IF(XLOOKUP(id, {info}!J:J, {info}!G:G, FALSE)=TRUE,'
                         '"Sí","No"))))'),
        L["estado"]: (f'=ARRAYFORMULA(IF({a}="",,IF({i}=TRUE,"{cobrada}",'
                      f'IF({g}="Sí","{por_cobrar}","{futura}"))))'),
    }
    if C.POOLEDGE_TRACK_COST:
        out[L["ganancia"]] = f'=ARRAYFORMULA(IF({a}="",,{e}-{L["costo"]}2:{L["costo"]}))'
    return out


def _month_bounds(p: str, date_col: str, month: int) -> str:
    d = f"{p}!{date_col}2:{date_col}"
    return (f'{d},">="&DATE(YEAR(TODAY()),{month},1),'
            f'{d},"<"&DATE(YEAR(TODAY()),{month + 1},1)')


def _resumen_values() -> List[Dict[str, Any]]:
    P = platas_letters()
    R = resumen_letters()
    p = quote_tab(C.POOLEDGE_TAB_PLATAS_NEW)
    tab = quote_tab(C.POOLEDGE_TAB_RESUMEN)
    states = C.POOLEDGE_COMMISSION_STATES
    est, com, ven, ped, fec = (f"{p}!{P[k]}2:{P[k]}" for k in ("estado", "comision", "venta", "id", "fecha"))
    headers = {"mes": "Mes", "pedidos": "Pedidos", "venta": "Venta neta",
               "ganancia": "Ganancia", "comision": "Comisión"}
    keys = _resumen_keys()
    src = {"pedidos": None, "venta": ven, "comision": com}
    if C.POOLEDGE_TRACK_COST:
        src["ganancia"] = f"{p}!{P['ganancia']}2:{P['ganancia']}"
    values = [
        {"range": f"{tab}!B1", "values": [['="Resumen "&YEAR(TODAY())']]},
        {"range": f"{tab}!B2", "values": [[
            "Indicadores: todos los pedidos de PLATAS 2026. Tabla y gráfico mensual: año en curso."]]},
        {"range": f"{tab}!B4:F4", "values": [[f"COMISIÓN {s.upper()}" for s in states]
                                             + ["VENTA NETA TOTAL", "N° DE PEDIDOS"]]},
        {"range": f"{tab}!B5:F5", "values": [[f'=SUMIF({est},"{s}",{com})' for s in states]
                                             + [f"=SUM({ven})", f"=COUNTA({ped})"]]},
        {"range": f"{tab}!B8:{R[keys[-1]]}8", "values": [[headers[k] for k in keys]]},
    ]
    rows = []
    for m, name in enumerate(_MONTHS, start=1):
        bounds = _month_bounds(p, P["fecha"], m)
        row: List[Any] = [name]
        for k in keys[1:]:
            row.append(f"=COUNTIFS({bounds})" if k == "pedidos" else f"=SUMIFS({src[k]},{bounds})")
        rows.append(row)
    values.append({"range": f"{tab}!B9:{R[keys[-1]]}20", "values": rows})
    total = ["Total"] + [f"=SUM({R[k]}9:{R[k]}20)" for k in keys[1:]]
    values.append({"range": f"{tab}!B21:{R[keys[-1]]}21", "values": [total]})
    return values


def _cobranza_values() -> List[Dict[str, Any]]:
    P = platas_letters()
    keys = [k for k, _, _ in platas_columns()]
    p = quote_tab(C.POOLEDGE_TAB_PLATAS_NEW)
    tab = quote_tab(C.POOLEDGE_TAB_COBRANZA)
    cobrada, por_cobrar, futura = C.POOLEDGE_COMMISSION_STATES
    est, com = (f"{p}!{P[k]}2:{P[k]}" for k in ("estado", "comision"))
    src = f"{p}!A2:{P['fcobro']}"
    ix = lambda k: keys.index(k) + 1  # noqa: E731  posición 1-based para CHOOSECOLS

    def table(state: str, cols: Tuple[str, ...], sort_pos: int, asc: bool) -> str:
        picks = ", ".join(str(ix(k)) for k in cols)
        return (f'=IFERROR(SORT(CHOOSECOLS(FILTER({src}, {est}="{state}"), {picks}), '
                f'{sort_pos}, {"TRUE" if asc else "FALSE"}), "")')

    # sort_pos es la posición dentro de CHOOSECOLS: fecha (3ª) en pendientes, fecha de cobro (4ª) en cobradas.
    return [
        {"range": f"{tab}!B1", "values": [["Cobranza"]]},
        {"range": f"{tab}!B2", "values": [["Tres listas automáticas desde PLATAS 2026; no se copia nada a mano."]]},
        {"range": f"{tab}!B3", "values": [["Por cobrar"]]},
        {"range": f"{tab}!H3", "values": [["Futuras"]]},
        {"range": f"{tab}!M3", "values": [["Cobradas"]]},
        {"range": f"{tab}!F3", "values": [[f'=SUMIF({est},"{por_cobrar}",{com})']]},
        {"range": f"{tab}!K3", "values": [[f'=SUMIF({est},"{futura}",{com})']]},
        {"range": f"{tab}!P3", "values": [[f'=SUMIF({est},"{cobrada}",{com})']]},
        {"range": f"{tab}!B4", "values": [["Lo más antiguo primero."]]},
        {"range": f"{tab}!H4", "values": [["Aún sin entregar."]]},
        {"range": f"{tab}!M4", "values": [["El último cobro primero."]]},
        {"range": f"{tab}!B5:F5", "values": [["ID PEDIDO", "CLIENTE", "FECHA", "DÍAS", "COMISIÓN"]]},
        {"range": f"{tab}!H5:K5", "values": [["ID PEDIDO", "CLIENTE", "FECHA", "COMISIÓN"]]},
        {"range": f"{tab}!M5:P5", "values": [["ID PEDIDO", "CLIENTE", "COMISIÓN", "FECHA COBRO"]]},
        {"range": f"{tab}!B6", "values": [[table(por_cobrar, ("id", "cliente", "fecha"), 3, True)]]},
        {"range": f"{tab}!E6", "values": [['=ARRAYFORMULA(IF(B6:B="",,TODAY()-D6:D))']]},
        {"range": f"{tab}!F6", "values": [[
            f'=MAP(B6:B, LAMBDA(id, IF(id="",, XLOOKUP(id, {p}!{P["id"]}:{P["id"]}, {p}!{P["comision"]}:{P["comision"]}))))']]},
        {"range": f"{tab}!H6", "values": [[table(futura, ("id", "cliente", "fecha", "comision"), 3, True)]]},
        {"range": f"{tab}!M6", "values": [[table(cobrada, ("id", "cliente", "comision", "fcobro"), 4, False)]]},
    ]


def _values_to_requests(values: List[Dict[str, Any]], ids_by_title: Dict[str, int]) -> List[Dict[str, Any]]:
    """Cada {"range","values"} -> request updateCells (fórmula si empieza con "=", texto si no)."""
    out = []
    for v in values:
        title, cell = v["range"].rsplit("!", 1)
        title = title[1:-1].replace("''", "'") if title.startswith("'") else title
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


def _platas_requests(pid: int, n: int, rules: _Rules) -> List[Dict[str, Any]]:
    cols = platas_columns()
    L = platas_letters()
    ncol = len(cols)
    idx = {k: i for i, (k, _, _) in enumerate(cols)}
    col = lambda k: _rng(pid, 1, n, idx[k], idx[k] + 1)  # noqa: E731
    reqs: List[Dict[str, Any]] = [_base(_rng(pid, 0, n, 0, ncol)), _header(_rng(pid, 0, 1, 0, ncol))]
    reqs.append(_dim(pid, "ROWS", 0, 1, 36))
    reqs.append(_dim(pid, "ROWS", 1, n, 28))
    for i, (_, _, width) in enumerate(cols):
        reqs.append(_dim(pid, "COLUMNS", i, i + 1, width))

    # Fondos y bordes: Arena en lo calculado (borde Papel), Papel en lo manual (borde Arena).
    groups: List[Tuple[int, int, bool]] = []
    for i, (k, _, _) in enumerate(cols):
        calc = k in _CALC_KEYS
        if groups and groups[-1][2] == calc and groups[-1][1] == i:
            groups[-1] = (groups[-1][0], i + 1, calc)
        else:
            groups.append((i, i + 1, calc))
    for c1, c2, calc in groups:
        body = _rng(pid, 1, n, c1, c2)
        if calc:
            reqs.append(_bg(body, _ARENA))
            reqs.append(_border(_rng(pid, 0, 1, c1, c2), "bottom", "SOLID_MEDIUM", _BRONCE))
        line = _PAPEL if calc else _ARENA
        reqs.append({"updateBorders": {"range": body, "bottom": {"style": "SOLID", "color": line},
                                       "innerHorizontal": {"style": "SOLID", "color": line}}})

    # Formato por columna.
    right_clp = ("venta", "comision", "costo", "ganancia")
    for k in right_clp:
        if k in idx:
            reqs.append(_number_fmt(col(k), _CLP, "RIGHT"))
    for k in ("fecha", "fcobro"):
        reqs.append(_number_fmt(col(k), _DATE, "LEFT"))
    for k in ("cliente", "detalle"):
        reqs.append(_align(col(k), "LEFT", clip=True))
    for k in ("entregado", "estado", "cobrado"):
        reqs.append(_align(col(k), "CENTER"))
    reqs.append(_fmt(col("id"), {"numberFormat": _TEXT, "horizontalAlignment": "LEFT"},
                     "numberFormat", "horizontalAlignment"))
    reqs.append(_bold(col("id")))
    reqs.append(_bold(col("comision")))
    reqs.append(_fmt(col("cobrado"), {"textFormat": {"foregroundColor": _PINO}}, "textFormat.foregroundColor"))
    reqs.append(_freeze(pid, 1))

    # Validaciones.
    info = quote_tab(C.POOLEDGE_TAB_INFO)
    reqs.append(_validation(col("id"), "ONE_OF_RANGE", (f"={info}!J2:J",), custom_ui=True))
    reqs.append(_validation(col("fecha"), "DATE_IS_VALID", custom_ui=True))
    reqs.append(_validation(col("fcobro"), "DATE_IS_VALID", custom_ui=True))
    reqs.append(_checkbox(col("cobrado")))

    # Protección de advertencia: bloque calculado.
    for c1, c2, calc in groups:
        if calc:
            reqs.append({"addProtectedRange": {"protectedRange": {
                "range": _rng(pid, 0, n, c1, c2), "warningOnly": True,
                "description": "Columnas calculadas (una fórmula en la fila 2): no escribir a mano"}}})

    # Formato condicional.
    cobrada, por_cobrar, futura = C.POOLEDGE_COMMISSION_STATES
    est = [col("estado")]
    rules.add(pid, est, _eq(cobrada), {"textFormat": {"foregroundColor": _PINO, "bold": True}})
    rules.add(pid, est, _eq(por_cobrar), {"backgroundColor": _BRONCE,
                                          "textFormat": {"foregroundColor": _PAPEL, "bold": True}})
    rules.add(pid, est, _eq(futura), {"textFormat": {"italic": True, "foregroundColor": _TINTA}})
    if C.POOLEDGE_TRACK_COST:
        rules.add(pid, [col("ganancia")], _lt(0), {"textFormat": {"foregroundColor": _BRONCE, "bold": True}})
    rules.add(pid, [col("fcobro")], _custom(f'=AND(${L["cobrado"]}2=TRUE,${L["fcobro"]}2="")'),
              {"backgroundColor": _BRONCE})
    return reqs


def _resumen_requests(rid: int, rules: _Rules) -> List[Dict[str, Any]]:
    R = resumen_letters()
    keys = _resumen_keys()
    last = 1 + len(keys)       # exclusivo
    reqs: List[Dict[str, Any]] = [_base(_rng(rid, 0, 30, 0, 12))]
    widths = {0: 24, 6: 24}
    widths.update({c: 150 for c in range(1, 6)})
    widths.update({c: 104 for c in range(7, 12)})
    for c, w in sorted(widths.items()):
        reqs.append(_dim(rid, "COLUMNS", c, c + 1, w))
    heights = {0: 48, 1: 24, 2: 20, 3: 26, 4: 44, 5: 28, 6: 32, 7: 32, 20: 32}
    heights.update({r: 26 for r in range(8, 20)})
    for r, h in sorted(heights.items()):
        reqs.append(_dim(rid, "ROWS", r, r + 1, h))
    reqs.append(_fmt(_rng(rid, 0, 1, 1, 2), {"textFormat": _text(22, font=_PLAYFAIR)}, "textFormat"))
    reqs.append(_fmt(_rng(rid, 1, 2, 1, 2), {"textFormat": _text(10, italic=True)}, "textFormat"))
    reqs.append(_fmt(_rng(rid, 3, 4, 1, 6), {"textFormat": _text(8, True, _BRONCE)}, "textFormat"))
    reqs.append(_border(_rng(rid, 3, 4, 1, 6), "top", "SOLID_MEDIUM", _TINTA))
    for c, color in enumerate((_PINO, _BRONCE, _TINTA, _TINTA, _TINTA), start=1):
        reqs.append(_fmt(_rng(rid, 4, 5, c, c + 1), {"textFormat": _text(18, color=color, font=_PLAYFAIR)},
                         "textFormat"))
    reqs.append(_border(_rng(rid, 4, 5, 1, 6), "bottom", "SOLID", _ARENA))
    reqs.append(_number_fmt(_rng(rid, 4, 5, 1, 5), _CLP, "LEFT"))
    reqs.append(_number_fmt(_rng(rid, 4, 5, 5, 6), _COUNT, "LEFT"))
    reqs.append(_header(_rng(rid, 7, 8, 1, last)))
    for k in keys[1:]:
        c = _col_index(R[k])
        reqs.append(_number_fmt(_rng(rid, 8, 21, c, c + 1), _COUNT if k == "pedidos" else _CLP, "RIGHT"))
    reqs.append(_bold(_rng(rid, 20, 21, 1, last)))
    reqs.append(_border(_rng(rid, 20, 21, 1, last), "top", "SOLID_MEDIUM", _TINTA))
    rules.add(rid, [_rng(rid, 8, 20, 1, last)], _custom("=ISEVEN(ROW())"), {"backgroundColor": _ARENA})

    axis_fmt = {"fontFamily": _PLEX, "fontSize": 9, "foregroundColor": _TINTA}
    src = lambda c: {"sourceRange": {"sources": [_rng(rid, 7, 20, c, c + 1)]}}  # noqa: E731
    reqs.append({"addChart": {"chart": {
        "spec": {
            "title": "Comisión por mes",
            "titleTextFormat": {"fontFamily": _PLAYFAIR, "fontSize": 12, "foregroundColor": _TINTA},
            "backgroundColor": _PAPEL,
            "basicChart": {
                "chartType": "COLUMN", "legendPosition": "NO_LEGEND", "headerCount": 1,
                "axis": [{"position": "BOTTOM_AXIS", "format": axis_fmt},
                         {"position": "LEFT_AXIS", "format": axis_fmt}],
                "domains": [{"domain": src(1)}],
                "series": [{"series": src(_col_index(R["comision"])), "targetAxis": "LEFT_AXIS",
                            "color": _PINO}],
            }},
        "position": {"overlayPosition": {
            "anchorCell": {"sheetId": rid, "rowIndex": 6, "columnIndex": 7},
            "widthPixels": 520, "heightPixels": 408}}}}})
    return reqs


def _cobranza_requests(cid: int, n: int, rules: _Rules) -> List[Dict[str, Any]]:
    reqs: List[Dict[str, Any]] = [_base(_rng(cid, 0, n, 0, 16))]
    widths = [24, 80, 180, 100, 64, 110, 32, 80, 160, 100, 110, 32, 80, 160, 110, 104]
    for c, w in enumerate(widths):
        reqs.append(_dim(cid, "COLUMNS", c, c + 1, w))
    for r, h in ((0, 48), (1, 20), (2, 40), (3, 24), (4, 32)):
        reqs.append(_dim(cid, "ROWS", r, r + 1, h))
    reqs.append(_dim(cid, "ROWS", 5, n, 28))
    reqs.append(_freeze(cid, 5))
    reqs.append(_fmt(_rng(cid, 0, 1, 1, 2), {"textFormat": _text(22, font=_PLAYFAIR)}, "textFormat"))
    reqs.append(_fmt(_rng(cid, 1, 2, 1, 2), {"textFormat": _text(10, italic=True)}, "textFormat"))
    tables = ((1, 6, "B", _BRONCE, 5), (7, 11, "H", _TINTA, 10), (12, 16, "M", _PINO, 15))
    for c1, c2, _, color, total_col in tables:
        reqs.append(_fmt(_rng(cid, 2, 3, c1, c2), {"textFormat": _text(14, font=_PLAYFAIR)}, "textFormat"))
        reqs.append(_border(_rng(cid, 2, 3, c1, c2), "top", "SOLID_MEDIUM", color))
        reqs.append(_number_fmt(_rng(cid, 2, 3, total_col, total_col + 1), _CLP, "RIGHT"))
        reqs.append(_fmt(_rng(cid, 2, 3, total_col, total_col + 1), {"textFormat": _text(14, font=_PLAYFAIR)},
                         "textFormat"))
        reqs.append(_fmt(_rng(cid, 3, 4, c1, c2), {"textFormat": _text(9, italic=True)}, "textFormat"))
        reqs.append(_header(_rng(cid, 4, 5, c1, c2)))
    # Datos: fechas, CLP y días.
    for c, nf, align in ((3, _DATE, "LEFT"), (4, _DAYS, "RIGHT"), (5, _CLP, "RIGHT"),
                         (9, _DATE, "LEFT"), (10, _CLP, "RIGHT"),
                         (14, _CLP, "RIGHT"), (15, _DATE, "LEFT")):
        reqs.append(_number_fmt(_rng(cid, 5, n, c, c + 1), nf, align))
    # Condicional: días >60 primero, luego >30, luego filas alternas.
    days = [_rng(cid, 5, n, 4, 5)]
    rules.add(cid, days, _gt(60), {"backgroundColor": _BRONCE,
                                   "textFormat": {"foregroundColor": _PAPEL, "bold": True}})
    rules.add(cid, days, _gt(30), {"textFormat": {"foregroundColor": _BRONCE, "bold": True}})
    for c1, c2, letter, _, _ in tables:
        rules.add(cid, [_rng(cid, 5, n, c1, c2)], _custom(f'=AND(${letter}6<>"",ISEVEN(ROW()))'),
                  {"backgroundColor": _ARENA})
    return reqs


def _info_requests(sid: int, end: int) -> List[Dict[str, Any]]:
    reqs: List[Dict[str, Any]] = [
        _checkbox(_rng(sid, 1, end, _INFO_COL_G, _INFO_COL_G + 1)),
        _validation(_rng(sid, 1, end, _INFO_COL_J, _INFO_COL_J + 1), "CUSTOM_FORMULA", ("=COUNTIF(J:J,J2)=1",)),
        _dim(sid, "COLUMNS", _INFO_COL_J, _INFO_COL_J + 1, 96),
        _dim(sid, "ROWS", 0, 1, 36),
        _freeze(sid, 1),
        _header(_rng(sid, 0, 1, 0, _INFO_COL_J + 1)),
        _align(_rng(sid, 0, 1, _INFO_COL_H, _INFO_COL_I + 1), "RIGHT"),
        _border(_rng(sid, 0, 1, _INFO_COL_J, _INFO_COL_J + 1), "bottom", "SOLID_MEDIUM", _BRONCE),
        _bold(_rng(sid, 1, end, _INFO_COL_J, _INFO_COL_J + 1)),
        _number_fmt(_rng(sid, 1, end, _INFO_COL_H, _INFO_COL_I + 1), _CLP, "RIGHT"),
        _fmt(_rng(sid, 1, end, _INFO_COL_D, _INFO_COL_E + 1),
             {"textFormat": {"foregroundColor": _PINO, "underline": True}},
             "textFormat.foregroundColor", "textFormat.underline"),
    ]
    return reqs


def _precios_requests(sid: int, end: int, with_banding: bool = True) -> List[Dict[str, Any]]:
    reqs: List[Dict[str, Any]] = [
        _header(_rng(sid, 0, 1, 0, 11)),
        _dim(sid, "ROWS", 0, 1, 36),
        _freeze(sid, 1),
    ]
    for c in (1, 2, 8, 9):
        reqs.append(_number_fmt(_rng(sid, 1, end, c, c + 1), _CLP, "RIGHT"))
    reqs.append(_bold(_rng(sid, 1, end, 2, 3)))
    reqs.append(_align(_rng(sid, 1, end, 10, 11), "RIGHT"))
    if with_banding:
        reqs.append({"addBanding": {"bandedRange": {
            "range": _rng(sid, 1, end, 0, 11),
            "rowProperties": {"firstBandColor": _PAPEL, "secondBandColor": _ARENA}}}})
    return reqs


_J1_HEADER = "ID PEDIDO"


def _overlaps(rng: Dict[str, int], other: Dict[str, int]) -> bool:
    """¿Se solapan dos rangos de la API? Los índices ausentes significan «desde 0 / hasta el final»."""
    inf = float("inf")
    for lo, hi in (("startRowIndex", "endRowIndex"), ("startColumnIndex", "endColumnIndex")):
        if rng[hi] <= other.get(lo, 0) or other.get(hi, inf) <= rng[lo]:
            return False
    return True


def build_plan(meta: dict, info_last_row: int, info_j1: str = "", info_g_invalid: int = 0) -> dict:
    """Plan determinista y JSON-serializable: requests de batchUpdate + valores.

    `meta`: resultado de sheets.get_sheet_meta. `info_last_row`: última fila (1-based)
    con CUALQUIER dato en INFO!A:I (solo informativo). `info_j1`: contenido de INFO!J1; debe
    estar vacío (se escribe el encabezado) o ser exactamente "ID PEDIDO" (no se reescribe);
    cualquier otra cosa es LayoutError. J2:J puede traer datos (los ID de la migración).
    `info_g_invalid`: cuántas celdas de INFO!G2:G tienen algo que no es TRUE/FALSE (solo el
    conteo): la casilla las marcaría inválidas, se avisa en la vista previa.
    Todos los datos de entrada entran al plan y por tanto a la huella.
    """
    for name, val, minimum in (("info_last_row", info_last_row, 1), ("info_g_invalid", info_g_invalid, 0)):
        if not isinstance(val, int) or isinstance(val, bool) or val < minimum:
            raise LayoutError(f"{name} inválido")
    if not isinstance(info_j1, str):
        raise LayoutError("info_j1 inválido")
    info_j1 = info_j1.strip()
    if info_j1 not in ("", _J1_HEADER):
        raise LayoutError("INFO!J1 ya tiene otro contenido: no se sobrescribe")
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
    n = C.POOLEDGE_FORMAT_ROWS
    info_end = grid.get("rowCount", n)
    if info_end < 2:
        raise LayoutError("INFO no tiene filas de datos")
    precios = next((p for p in props if p.get("title") == C.POOLEDGE_TAB_PRECIOS), None)
    precios_sheet = next((x for x in meta.get("sheets", [])
                          if x.get("properties", {}).get("title") == C.POOLEDGE_TAB_PRECIOS), {})

    reqs: List[Dict[str, Any]] = []
    ncol = len(platas_columns())
    for t, sid, cols, frozen, rows in ((new_tabs[0], pid, ncol, 1, n), (new_tabs[1], rid, 12, 0, 30),
                                       (new_tabs[2], cid, 16, 5, n)):
        gp: Dict[str, Any] = {"rowCount": rows, "columnCount": cols, "hideGridlines": True}
        if frozen:
            gp["frozenRowCount"] = frozen
        reqs.append({"addSheet": {"properties": {"sheetId": sid, "title": t, "gridProperties": gp}}})

    rules = _Rules()
    reqs += _platas_requests(pid, n, rules)
    reqs += _resumen_requests(rid, rules)
    reqs += _cobranza_requests(cid, n, rules)
    reqs += rules.out
    reqs += _info_requests(info_sid, info_end)
    banding_skipped = False
    if precios:
        p_end = precios.get("gridProperties", {}).get("rowCount", n)
        banding_skipped = any(_overlaps(_rng(precios["sheetId"], 1, p_end, 0, 11), b.get("range", {}))
                              for b in precios_sheet.get("bandedRanges", []))
        reqs += _precios_requests(precios["sheetId"], p_end, with_banding=not banding_skipped)

    p = quote_tab(C.POOLEDGE_TAB_PLATAS_NEW)
    L = platas_letters()
    values: List[Dict[str, Any]] = []
    if not info_j1:
        values.append({"range": f"{quote_tab(C.POOLEDGE_TAB_INFO)}!J1", "values": [[_J1_HEADER]]})
    values.append({"range": f"{p}!A1:{col_letter(ncol - 1)}1", "values": [[h for _, h, _ in platas_columns()]]})
    values += [{"range": f"{p}!{letter}2", "values": [[f]]} for letter, f in _platas_formulas().items()]
    values += _resumen_values() + _cobranza_values()

    titles_by_id = {pid: new_tabs[0], rid: new_tabs[1], cid: new_tabs[2], info_sid: C.POOLEDGE_TAB_INFO}
    reqs += _values_to_requests(values, {t: i for i, t in titles_by_id.items()})

    info_t = C.POOLEDGE_TAB_INFO
    platas_t = C.POOLEDGE_TAB_PLATAS_NEW
    warnings = []
    if info_g_invalid:
        warnings.append(
            f"{info_t}!G2:G tiene {info_g_invalid} celda(s) con algo distinto de TRUE/FALSE: la casilla "
            "las marcará como inválidas (no cambia su valor). Revisarlas antes de aplicar.")
    if banding_skipped:
        warnings.append(f"{C.POOLEDGE_TAB_PRECIOS} ya tiene colores alternos; se dejan los existentes.")
    summary = {
        "tabs_to_create": list(new_tabs),
        "sheet_ids": {t: ids[t] for t in new_tabs},
        "sheet_titles": {str(i): t for i, t in titles_by_id.items()},
        "platas_columns": {L[k]: h for k, h, _ in platas_columns()},
        "track_cost": bool(C.POOLEDGE_TRACK_COST),
        "info_last_row": info_last_row,
        "info_j1_has_header": bool(info_j1),
        "info_g_invalid": info_g_invalid,
        "info_end_row": info_end,
        "format_rows": n,
        "warnings": warnings,
        "validations": [
            f"{platas_t}!{L['id']}2:{L['id']}{n}: desplegable desde {info_t}!J2:J (rechaza otros)",
            f"{platas_t}!{L['fecha']}2:{L['fecha']}{n} y {L['fcobro']}2:{L['fcobro']}{n}: fecha válida",
            f"{platas_t}!{L['cobrado']}2:{L['cobrado']}{n}: casilla (COBRADO)",
            f"{info_t}!G2:G{info_end}: casilla (ENTREGADO)",
            f"{info_t}!J2:J{info_end}: ID sin repetir, COUNTIF(J:J,J2)=1 (rechaza)",
        ],
        "formats": [
            f"{platas_t}: {ncol} columnas, fila 1 congelada, cuadrícula oculta, Arena en lo calculado, "
            "bloque calculado protegido con advertencia",
            f"{C.POOLEDGE_TAB_RESUMEN} y {C.POOLEDGE_TAB_COBRANZA}: cuadrícula oculta, formato de la ficha; "
            "gráfico de columnas «Comisión por mes» en RESUMEN!H7 (520x408)",
            f"{platas_t}!{L['estado']}: Cobrada Pino, Por cobrar Bronce, Futura cursiva; "
            f"{L['fcobro']} Bronce si cobrado sin fecha",
            f"{info_t}: fila 1 Tinta/Papel congelada, J negrita, H:I CLP, D:E Pino subrayado",
            *([f"{C.POOLEDGE_TAB_PRECIOS}: fila 1, CLP en B,C,I,J, C negrita, colores alternos A2:K. "
               "Columnas D:H NO se ocultan (no se verificó que estén vacías)"] if precios else
              [f"{C.POOLEDGE_TAB_PRECIOS}: no existe en la planilla, se omite"]),
            f"Techo: formato y fórmulas hasta la fila {n} ({n - 1} pedidos)",
        ],
        "info_cells": [
            (f"{info_t}!J1: ya dice 'ID PEDIDO', no se reescribe" if info_j1 else
             f"{info_t}!J1: encabezado 'ID PEDIDO' (hoy vacía)") + ". Ninguna otra celda de datos cambia de valor",
            f"{info_t}!G2:G{info_end}, J2:J{info_end}: validaciones",
            f"{info_t}: solo estilos en fila 1, D:E, H:I, J",
        ],
        "n_requests": len(reqs),
        "n_value_ranges": len(values),
    }
    return {"requests": reqs, "summary": summary}


def plan_fingerprint(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _example_row() -> List[int]:
    sale = 150_000
    return [sale, round(sale * C.POOLEDGE_COMMISSION_RATE)]


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
    sale, com = _example_row()
    money = lambda x: e(f"${x:,.0f}".replace(",", "."))  # noqa: E731
    example = (
        "<table><tr><th>VENTA NETA</th><th>COMISIÓN</th></tr><tr>"
        + "".join(f"<td>{money(x)}</td>" for x in (sale, com))
        + "</tr></table>")
    colmap = ("<table><tr><th>Letra</th><th>Encabezado</th></tr>"
              + "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in s["platas_columns"].items())
              + "</table>")
    warn = ("<h2 style=\"color:#8A6A3B\">Avisos</h2>" + ul(s["warnings"])) if s["warnings"] else ""
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
        + warn
        + "<h2>Pestañas a crear</h2>" + ul(s["tabs_to_create"])
        + f"<h2>Columnas de {e(C.POOLEDGE_TAB_PLATAS_NEW)}</h2>" + colmap
        + "<h2>Encabezados y fórmulas (valores a escribir)</h2>"
        "<table><tr><th>Rango</th><th>Contenido</th></tr>" + rows + "</table>"
        "<h2>Validaciones</h2>" + ul(s["validations"])
        + "<h2>Formatos</h2>" + ul(s["formats"])
        + "<h2>Celdas de INFO que se tocan</h2>" + ul(s["info_cells"])
        + f"<p>INFO: filas con datos hasta la {e(str(s['info_last_row']))}. "
        "Ninguna celda existente cambia de valor.</p>"
        "<h2>Ejemplo sintético</h2>" + example
        + "</body></html>")
