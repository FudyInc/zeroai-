"""Google Sheets — sincroniza Finanzas y la cartera de Leads a un Sheet real,
en vivo, sin que nadie tenga que descargar ni pegar nada a mano (pedido por
Diego, 2026-07-20). Pensado para correr desde `scripts/sync_sheets.py` vía
systemd timer — ver ese archivo.

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
from typing import Any, Dict, List, Optional

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


def _ensure_tab(spreadsheet_id: str, title: str, token: str) -> None:
    """Crea la pestaña si no existe todavía — así el Sheet se arma solo la
    primera vez, sin que Diego tenga que crear "Finanzas"/"Leads" a mano."""
    meta = _request("GET", spreadsheet_id, token) or {}
    titles = {s.get("properties", {}).get("title") for s in meta.get("sheets", [])}
    if title in titles:
        return
    _request("POST", f"{spreadsheet_id}:batchUpdate", token,
             {"requests": [{"addSheet": {"properties": {"title": title}}}]})


def _write_tab(spreadsheet_id: str, title: str, rows: List[List[Any]], token: str) -> None:
    """Limpia la pestaña y la reescribe entera desde A1 — idempotente: cada
    sincronización deja el Sheet como el estado ACTUAL, nunca acumula filas
    de corridas anteriores."""
    _ensure_tab(spreadsheet_id, title, token)
    _request("POST", f"{spreadsheet_id}/values/{title}:clear", token, {})
    if not rows:
        return
    _request(
        "PUT", f"{spreadsheet_id}/values/{title}!A1?valueInputOption=RAW", token,
        {"values": rows},
    )


def _cell(v: Any) -> Any:
    """None -> celda vacía en vez de la palabra "None" pegada en el Sheet."""
    return "" if v is None else v


def build_finance_rows(data: Dict[str, Any]) -> List[List[Any]]:
    """Mismo dato que ya muestra Finanzas.jsx — solo aplanado a filas."""
    rows: List[List[Any]] = [
        ["ZeroAI — Finanzas de la agencia"],
        [f"Mes: {data.get('month')}", f"Fuente: {data.get('source')}"],
        [],
        ["Resumen"],
        ["Ingresos (MRR, CLP)", _cell(data.get("mrr_clp"))],
        ["Costos totales (CLP)", _cell(data.get("costs_clp"))],
        ["Margen (CLP)", _cell(data.get("margin_clp"))],
        ["Margen (%)", _cell(data.get("margin_pct"))],
        [],
        ["Costos por categoría"],
        ["Categoría", "Monto (CLP)", "Nota"],
    ]
    for c in data.get("costs") or []:
        rows.append([_cell(c.get("category")), _cell(c.get("amount_clp")), _cell(c.get("note"))])
    rows.append([])
    rows.append(["Histórico mensual"])
    rows.append(["Mes", "MRR (CLP)", "Costos (CLP)", "Margen (CLP)"])
    for h in data.get("history") or []:
        rows.append([_cell(h.get("month")), _cell(h.get("mrr_clp")),
                    _cell(h.get("costs_clp")), _cell(h.get("margin_clp"))])
    return rows


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
        _write_tab(spreadsheet_id, "Finanzas", build_finance_rows(data), token)
        return True
    except SheetsError:
        return False


def sync_leads(spreadsheet_id: str, leads: List[Dict[str, Any]], token: Optional[str] = None) -> bool:
    token = token or get_access_token()
    if not token:
        return False
    try:
        _write_tab(spreadsheet_id, "Leads", build_leads_rows(leads), token)
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
