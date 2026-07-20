"""Google Sheets — sincroniza Finanzas y la cartera de Leads a un Sheet real,
en vivo, sin que nadie tenga que descargar ni pegar nada a mano (pedido por
Diego, 2026-07-20), con formato y un gráfico de tendencia listos (pedido el
mismo día, en la misma conversación). Pensado para correr desde
`scripts/sync_sheets.py` vía systemd timer — ver ese archivo.

Cuenta de servicio de Google Cloud (server-to-server), no OAuth de usuario:
sin login humano en cada corrida. Necesita en el entorno:
  GOOGLE_SHEETS_KEY_PATH  : ruta al JSON de la cuenta de servicio
  GOOGLE_SHEETS_ID        : ID del spreadsheet (compartido con esa cuenta,
                            rol Editor — si no, la API responde 403)

Firma el JWT de autenticación con RSA (RS256) usando `cryptography` — MISMA
excepción ya documentada en zero/auth.py (verificación ES256 de Supabase):
el stdlib no tiene primitivas de firma asimétrica, y hand-rollear eso es un
riesgo real, no un lugar para ahorrar una dependencia. Nada más en este
módulo necesita nada fuera del stdlib.
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ._env import load_env

load_env()

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"
_SCOPE = "https://www.googleapis.com/auth/spreadsheets"

# Token de acceso cacheado en memoria del proceso — dura ~1h, se pide de
# nuevo con margen antes de vencer. `scripts/sync_sheets.py` corre como
# proceso corto (systemd timer), así que en la práctica esto solo evita
# pedir un token nuevo si se llama a sync_all() más de una vez por corrida.
_TOKEN_CACHE: Dict[str, Any] = {"token": None, "expires_at": 0.0}

# Paleta aproximada de marca (slate/champagne gold) para encabezados — un
# Sheet no necesita calzar pixel a pixel con el dashboard, solo verse
# cuidado y no genérico.
_SLATE = {"red": 0.20, "green": 0.24, "blue": 0.31}
_CHAMPAGNE = {"red": 0.93, "green": 0.87, "blue": 0.73}
_WHITE = {"red": 1, "green": 1, "blue": 1}


class SheetsError(RuntimeError):
    """Cualquier fallo de red/HTTP hablando con la Sheets API real."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _load_key(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    path = path or os.environ.get("GOOGLE_SHEETS_KEY_PATH")
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("private_key") or not data.get("client_email"):
        return None
    return data


def _sign_jwt(key: Dict[str, Any]) -> str:
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {
        "iss": key["client_email"],
        "scope": _SCOPE,
        "aud": _TOKEN_URL,
        "iat": now,
        "exp": now + 3600,
    }
    h = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = _b64url(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h}.{p}".encode("ascii")
    private_key = serialization.load_pem_private_key(
        key["private_key"].encode("utf-8"), password=None,
    )
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{h}.{p}.{_b64url(signature)}"


def get_access_token(key_path: Optional[str] = None, force_refresh: bool = False) -> Optional[str]:
    """Token de acceso OAuth2 para la cuenta de servicio. Nunca lanza: sin
    llave, llave con forma rara, o red caída -> None, y el caller decide qué
    hacer (nunca tumbar el resto de una sincronización por esto)."""
    now = time.time()
    if not force_refresh and _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expires_at"] - 60:
        return _TOKEN_CACHE["token"]
    key = _load_key(key_path)
    if key is None:
        return None
    try:
        assertion = _sign_jwt(key)
    except Exception:
        return None
    body = f"grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion={assertion}".encode("ascii")
    req = urllib.request.Request(
        _TOKEN_URL, data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return None
    token = data.get("access_token")
    if not token:
        return None
    _TOKEN_CACHE["token"] = token
    _TOKEN_CACHE["expires_at"] = now + float(data.get("expires_in", 3600))
    return token


def _request(method: str, path: str, token: str, body: Any = None) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{_SHEETS_API}/{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        raise SheetsError(f"Sheets API {e.code}: {e.read().decode('utf-8', 'replace')}") from e
    except urllib.error.URLError as e:
        raise SheetsError(f"no se pudo contactar la Sheets API: {e}") from e


def _get_meta(spreadsheet_id: str, token: str) -> Dict[str, Any]:
    return _request("GET", f"{spreadsheet_id}?fields=sheets(properties,charts)", token) or {}


def _ensure_tab(spreadsheet_id: str, title: str, token: str,
                meta: Optional[Dict[str, Any]] = None) -> Tuple[int, Dict[str, Any]]:
    """Crea la pestaña si no existe todavía — así el Sheet se arma solo la
    primera vez, sin que Diego tenga que crear "Finanzas"/"Leads" a mano.
    Devuelve (sheetId, metadata-ya-fresca) — el sheetId numérico interno
    hace falta para las requests de formato/gráficos (distinto del título)."""
    meta = meta if meta is not None else _get_meta(spreadsheet_id, token)
    for s in meta.get("sheets", []):
        props = s.get("properties", {})
        if props.get("title") == title:
            return props.get("sheetId"), meta
    _request("POST", f"{spreadsheet_id}:batchUpdate", token,
             {"requests": [{"addSheet": {"properties": {"title": title}}}]})
    meta = _get_meta(spreadsheet_id, token)
    for s in meta.get("sheets", []):
        props = s.get("properties", {})
        if props.get("title") == title:
            return props.get("sheetId"), meta
    raise SheetsError(f"no se pudo crear/encontrar la pestaña {title!r}")


def _write_values(spreadsheet_id: str, title: str, rows: List[List[Any]], token: str) -> None:
    """Limpia la pestaña y la reescribe entera desde A1 — idempotente: cada
    sincronización deja el Sheet como el estado ACTUAL, nunca acumula filas
    de corridas anteriores."""
    _request("POST", f"{spreadsheet_id}/values/{title}:clear", token, {})
    if not rows:
        return
    _request(
        "PUT", f"{spreadsheet_id}/values/{title}!A1?valueInputOption=RAW", token,
        {"values": rows},
    )


def _batch_update(spreadsheet_id: str, requests: List[Dict[str, Any]], token: str) -> None:
    if requests:
        _request("POST", f"{spreadsheet_id}:batchUpdate", token, {"requests": requests})


def _cell(v: Any) -> Any:
    """None -> celda vacía en vez de la palabra "None" pegada en el Sheet."""
    return "" if v is None else v


# --- Finanzas: filas + layout (para poder formatear/graficar con precisión) ---

def build_finance_rows(data: Dict[str, Any]) -> Tuple[List[List[Any]], Dict[str, int]]:
    """Mismo dato que ya muestra Finanzas.jsx, aplanado a filas — más un
    "layout" con los índices de fila (0-based) de cada sección, para que el
    formato y el gráfico se apliquen a las celdas correctas sin adivinar,
    sin importar cuántas categorías de costo o meses de histórico haya."""
    rows: List[List[Any]] = [["ZeroAI — Finanzas de la agencia"]]
    rows.append([f"Mes: {data.get('month')}", f"Fuente: {data.get('source')}"])
    rows.append([])
    resumen_header_row = len(rows)
    rows.append(["Resumen"])
    resumen_start_row = len(rows)
    rows.append(["Ingresos (MRR, CLP)", _cell(data.get("mrr_clp"))])
    rows.append(["Costos totales (CLP)", _cell(data.get("costs_clp"))])
    rows.append(["Margen (CLP)", _cell(data.get("margin_clp"))])
    margin_pct_row = len(rows)
    rows.append(["Margen (%)", _cell(data.get("margin_pct"))])
    resumen_end_row = len(rows)   # exclusivo
    rows.append([])
    costs_header_row = len(rows)
    rows.append(["Costos por categoría"])
    costs_columns_row = len(rows)
    rows.append(["Categoría", "Monto (CLP)", "Nota"])
    costs_start_row = len(rows)
    for c in data.get("costs") or []:
        rows.append([_cell(c.get("category")), _cell(c.get("amount_clp")), _cell(c.get("note"))])
    costs_end_row = len(rows)   # exclusivo
    rows.append([])
    historico_header_row = len(rows)
    rows.append(["Histórico mensual"])
    historico_columns_row = len(rows)
    rows.append(["Mes", "MRR (CLP)", "Costos (CLP)", "Margen (CLP)"])
    historico_start_row = len(rows)
    for h in data.get("history") or []:
        rows.append([_cell(h.get("month")), _cell(h.get("mrr_clp")),
                    _cell(h.get("costs_clp")), _cell(h.get("margin_clp"))])
    historico_end_row = len(rows)   # exclusivo

    layout = {
        "resumen_header_row": resumen_header_row,
        "resumen_start_row": resumen_start_row,
        "resumen_end_row": resumen_end_row,
        "margin_pct_row": margin_pct_row,
        "costs_header_row": costs_header_row,
        "costs_columns_row": costs_columns_row,
        "costs_start_row": costs_start_row,
        "costs_end_row": costs_end_row,
        "historico_header_row": historico_header_row,
        "historico_columns_row": historico_columns_row,
        "historico_start_row": historico_start_row,
        "historico_end_row": historico_end_row,
    }
    return rows, layout


def _section_title_fmt(sheet_id: int, row: int) -> List[Dict[str, Any]]:
    """Banner de sección: fondo slate + texto blanco, y las 4 celdas
    fusionadas en una sola — así se ve como un título real, no una fila de
    color con el texto pegado solo en la primera celda."""
    return [
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": row, "endRowIndex": row + 1,
                      "startColumnIndex": 0, "endColumnIndex": 4},
            "cell": {"userEnteredFormat": {
                "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": _WHITE},
                "backgroundColor": _SLATE,
            }},
            "fields": "userEnteredFormat(textFormat,backgroundColor)",
        }},
        {"mergeCells": {
            "range": {"sheetId": sheet_id, "startRowIndex": row, "endRowIndex": row + 1,
                      "startColumnIndex": 0, "endColumnIndex": 4},
            "mergeType": "MERGE_ALL",
        }},
    ]


def _column_header_fmt(sheet_id: int, row: int, n_cols: int) -> Dict[str, Any]:
    return {"repeatCell": {
        "range": {"sheetId": sheet_id, "startRowIndex": row, "endRowIndex": row + 1,
                  "startColumnIndex": 0, "endColumnIndex": n_cols},
        "cell": {"userEnteredFormat": {
            "textFormat": {"bold": True}, "backgroundColor": _CHAMPAGNE,
        }},
        "fields": "userEnteredFormat(textFormat,backgroundColor)",
    }}


def _currency_fmt(sheet_id: int, r1: int, r2: int, c1: int, c2: int) -> Dict[str, Any]:
    return {"repeatCell": {
        "range": {"sheetId": sheet_id, "startRowIndex": r1, "endRowIndex": r2,
                  "startColumnIndex": c1, "endColumnIndex": c2},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "CURRENCY", "pattern": '"$"#,##0'}}},
        "fields": "userEnteredFormat.numberFormat",
    }}


def _percent_fmt(sheet_id: int, row: int) -> Dict[str, Any]:
    # margin_pct ya viene en unidades de porcentaje (94.8, no 0.948) — se
    # formatea como número con un "%" pegado, sin dividir el valor.
    return {"repeatCell": {
        "range": {"sheetId": sheet_id, "startRowIndex": row, "endRowIndex": row + 1,
                  "startColumnIndex": 1, "endColumnIndex": 2},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": '0.0"%"'}}},
        "fields": "userEnteredFormat.numberFormat",
    }}


def _auto_resize_columns(sheet_id: int, n_cols: int) -> Dict[str, Any]:
    """Ancho de columna ajustado al contenido REAL recién escrito, en vez de
    un número de píxeles adivinado a mano — la forma correcta de asegurar
    que toda la información quepa (emails largos, nombres de empresa, notas,
    etc.) sin importar qué tan largo sea el dato real. Tiene que correr
    DESPUÉS de escribir los valores, nunca antes (si no, mide celdas vacías)."""
    return {"autoResizeDimensions": {
        "dimensions": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": 0, "endIndex": n_cols},
    }}


def _finance_format_requests(sheet_id: int, layout: Dict[str, int]) -> List[Dict[str, Any]]:
    reqs: List[Dict[str, Any]] = [
        # título grande arriba, fusionado en una sola celda ancha
        {"repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": 4},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True, "fontSize": 14}}},
            "fields": "userEnteredFormat.textFormat",
        }},
        {"mergeCells": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": 4},
            "mergeType": "MERGE_ALL",
        }},
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }},
        *_section_title_fmt(sheet_id, layout["resumen_header_row"]),
        *_section_title_fmt(sheet_id, layout["costs_header_row"]),
        *_section_title_fmt(sheet_id, layout["historico_header_row"]),
        _column_header_fmt(sheet_id, layout["costs_columns_row"], 3),
        _column_header_fmt(sheet_id, layout["historico_columns_row"], 4),
        _currency_fmt(sheet_id, layout["resumen_start_row"], layout["margin_pct_row"], 1, 2),
        _percent_fmt(sheet_id, layout["margin_pct_row"]),
    ]
    if layout["costs_end_row"] > layout["costs_start_row"]:
        reqs.append(_currency_fmt(sheet_id, layout["costs_start_row"], layout["costs_end_row"], 1, 2))
    if layout["historico_end_row"] > layout["historico_start_row"]:
        reqs.append(_currency_fmt(sheet_id, layout["historico_start_row"], layout["historico_end_row"], 1, 4))
    # el auto-resize de columnas va AL FINAL: tiene que correr después de
    # fusionar celdas y fijar los formatos, para medir el contenido ya en
    # su forma definitiva (si no, puede medir mal el ancho de una celda que
    # después queda fusionada).
    reqs.append(_auto_resize_columns(sheet_id, 4))
    return reqs


_FINANCE_CHART_TITLE = "MRR / Costos / Margen por mes"


def _finance_chart_request(sheet_id: int, layout: Dict[str, int]) -> Optional[Dict[str, Any]]:
    """Un gráfico de línea con la tendencia mensual — solo si hay al menos 2
    meses de histórico (un punto solo no dice nada). Se posiciona flotando
    a la derecha de la tabla de histórico."""
    r1, r2 = layout["historico_columns_row"], layout["historico_end_row"]
    if r2 - r1 < 3:   # header + al menos 2 meses
        return None
    domain = {"sheetId": sheet_id, "startRowIndex": r1, "endRowIndex": r2,
             "startColumnIndex": 0, "endColumnIndex": 1}
    series = []
    for col, name in ((1, "MRR"), (2, "Costos"), (3, "Margen")):
        series.append({
            "series": {"sourceRange": {"sources": [{
                "sheetId": sheet_id, "startRowIndex": r1, "endRowIndex": r2,
                "startColumnIndex": col, "endColumnIndex": col + 1,
            }]}},
            "targetAxis": "LEFT_AXIS",
        })
    return {"addChart": {"chart": {
        "spec": {
            "title": _FINANCE_CHART_TITLE,
            "basicChart": {
                "chartType": "LINE",
                "legendPosition": "BOTTOM_LEGEND",
                "axis": [{"position": "BOTTOM_AXIS", "title": "Mes"},
                        {"position": "LEFT_AXIS", "title": "CLP"}],
                "domains": [{"domain": {"sourceRange": {"sources": [domain]}}}],
                "series": series,
                "headerCount": 1,
            },
        },
        "position": {"overlayPosition": {
            "anchorCell": {"sheetId": sheet_id, "rowIndex": layout["historico_header_row"], "columnIndex": 5},
            "widthPixels": 560, "heightPixels": 320,
        }},
    }}}


def _leads_format_requests(sheet_id: int, n_rows: int) -> List[Dict[str, Any]]:
    reqs = [
        _column_header_fmt(sheet_id, 0, len(_LEADS_HEADER)),
        {"updateSheetProperties": {
            "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }},
    ]
    reqs.append(_auto_resize_columns(sheet_id, len(_LEADS_HEADER)))
    if n_rows > 1:
        reqs.append({"setBasicFilter": {"filter": {"range": {
            "sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": n_rows,
            "startColumnIndex": 0, "endColumnIndex": len(_LEADS_HEADER),
        }}}})
    return reqs


_LEADS_HEADER = ["Cliente", "Empresa", "Contacto", "Cargo", "Email", "Teléfono",
                 "Canal", "Score", "Etapa", "Actualizado"]


def build_leads_rows(leads: List[Dict[str, Any]]) -> List[List[Any]]:
    rows: List[List[Any]] = [_LEADS_HEADER]
    ordered = sorted(leads, key=lambda r: (-(r.get("score") or 0), r.get("company") or ""))
    for r in ordered:
        rows.append([
            _cell(r.get("client_id")), _cell(r.get("company")), _cell(r.get("name")),
            _cell(r.get("role")), _cell(r.get("email")), _cell(r.get("phone")),
            _cell(r.get("channel")), _cell(r.get("score")), _cell(r.get("stage")),
            _cell(r.get("updated")),
        ])
    return rows


def sync_finance(spreadsheet_id: str, data: Dict[str, Any], token: Optional[str] = None) -> bool:
    token = token or get_access_token()
    if not token:
        return False
    try:
        sheet_id, meta = _ensure_tab(spreadsheet_id, "Finanzas", token)
        rows, layout = build_finance_rows(data)
        _write_values(spreadsheet_id, "Finanzas", rows, token)
        requests = _finance_format_requests(sheet_id, layout)
        # El gráfico solo se agrega si esta pestaña todavía no tiene uno con
        # este título — evita duplicarlo en cada corrida del timer.
        existing_charts = next(
            (s.get("charts", []) for s in meta.get("sheets", [])
             if s.get("properties", {}).get("sheetId") == sheet_id), [])
        has_chart = any(c.get("spec", {}).get("title") == _FINANCE_CHART_TITLE for c in existing_charts)
        if not has_chart:
            chart_req = _finance_chart_request(sheet_id, layout)
            if chart_req:
                requests.append(chart_req)
        _batch_update(spreadsheet_id, requests, token)
        return True
    except SheetsError:
        return False


def sync_leads(spreadsheet_id: str, leads: List[Dict[str, Any]], token: Optional[str] = None) -> bool:
    token = token or get_access_token()
    if not token:
        return False
    try:
        sheet_id, _ = _ensure_tab(spreadsheet_id, "Leads", token)
        rows = build_leads_rows(leads)
        _write_values(spreadsheet_id, "Leads", rows, token)
        _batch_update(spreadsheet_id, _leads_format_requests(sheet_id, len(rows)), token)
        return True
    except SheetsError:
        return False


def sync_all(spreadsheet_id: str, finance_data: Dict[str, Any],
            leads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Un solo token para las dos pestañas — evita pedirlo dos veces por
    corrida. Nunca lanza: cada sincronización reporta su propio ok/False."""
    token = get_access_token()
    if not token:
        return {"finance": False, "leads": False,
                "error": "sin token (falta GOOGLE_SHEETS_KEY_PATH o la llave no sirve)"}
    return {
        "finance": sync_finance(spreadsheet_id, finance_data, token),
        "leads": sync_leads(spreadsheet_id, leads, token),
    }
