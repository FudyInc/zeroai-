"""Config del dashboard persistida en la nube — sobrevive a redeploys.

En Render el disco es efímero: los secretos escritos por el dashboard (a `.env`)
se borran en cada redeploy. Esto los guarda en Supabase (fila `app_state` id='env')
y los carga al entorno al arrancar. Los env vars reales (Render) mandan por sobre estos.

Mismo límite de confianza que `.env`: el backend ya tiene acceso total a Supabase
(service_role), y es la DB de la propia agencia.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

from ._supabase import sb_request

_TABLE = "app_state"
_ROW = "env"


def _creds() -> Tuple[Optional[str], Optional[str]]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    return (url.rstrip("/") if url else None), key


def _read() -> dict:
    url, key = _creds()
    if not url:
        return {}
    try:
        rows = sb_request(url, key, "GET", f"{_TABLE}?id=eq.{_ROW}&select=data") or []
    except Exception:
        return {}
    return (rows[0].get("data") if rows else {}) or {}


def load_into_environ() -> None:
    """Carga los secretos de la nube al entorno — sin pisar los que ya están
    (los de Render env tienen prioridad)."""
    for k, v in _read().items():
        if v and k not in os.environ:
            os.environ[k] = str(v)


def save_secret(key_name: str, value: str) -> None:
    """Persiste un secreto en la nube para que sobreviva al próximo redeploy."""
    url, key = _creds()
    if not url:
        return
    try:
        data = _read()
        data[key_name] = value
        sb_request(url, key, "POST", f"{_TABLE}?on_conflict=id",
                   body=[{"id": _ROW, "data": data}],
                   prefer="resolution=merge-duplicates,return=minimal")
    except Exception:
        pass
