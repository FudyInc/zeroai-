"""Pick the CRM backend — Supabase if configured, else the local JSON file.

This is the single switch between "local dev / mock" and "cloud / team": set
SUPABASE_URL + SUPABASE_KEY and the whole app starts persisting to Postgres
instead of crm.json, with no other code change.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone

from ._env import load_env
from ._supabase import SupabaseError, sb_request
from .config import CRM_BREAKER_DOWN_S, CRM_BREAKER_OK_S, CRM_PROBE_TIMEOUT_S
from .crm import CRM
from .memory import SessionMemory

load_env()


def _supabase_on() -> bool:
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


class CRMRespaldoSoloLectura(CRM):
    """CRM local servido mientras Supabase está caído: SOLO LECTURA. `crm.json` quedó
    congelado en el último respaldo; escribirle mostraría un pipeline viejo como real,
    se perdería en silencio al volver la nube y rotaría el `.bak` bueno. Toda escritura
    falla con SupabaseError, que api.py ya convierte en 503 con el motivo."""

    def _rechazar(self, *args, **kwargs):
        raise SupabaseError(
            "CRM en respaldo local de solo lectura: Supabase no responde, "
            "no se aceptan escrituras", code=503)

    upsert = advance = set_stage = log = set_outreach = block = clear = save = _rechazar


# Breaker en memoria (por proceso): evita sondear Supabase en cada request.
_breaker = {"up": True, "until": 0.0}


def _supabase_up() -> bool:
    now = time.monotonic()
    if _breaker["until"] > now:
        return _breaker["up"]
    url = os.environ["SUPABASE_URL"].rstrip("/")
    try:
        sb_request(url, os.environ["SUPABASE_KEY"], "GET", "crm_leads?select=client_id&limit=1",
                   timeout=CRM_PROBE_TIMEOUT_S)
        up = True
    except (SupabaseError, OSError, ValueError) as e:   # 402 / red / timeout / JSON roto
        print(f"[zero] CRM en la nube no disponible ({e}); respaldo local de solo lectura",
              file=sys.stderr)
        up = False
    _breaker["up"] = up
    _breaker["until"] = now + (CRM_BREAKER_OK_S if up else CRM_BREAKER_DOWN_S)
    return up


def make_crm(file_path: str = "crm.json"):
    """CRM en la nube si Supabase está configurado Y responde; si no, el archivo local
    en solo lectura. `SupabaseCRM` carga perezoso (el fallo real llegaría en la primera
    operación, ya dentro del endpoint), así que se sondea acá, con un breaker para no
    sondear en cada request. Lo local no se sincroniza con la nube."""
    if _supabase_on():
        if _supabase_up():
            from .crm_supabase import SupabaseCRM
            return SupabaseCRM()
        return CRMRespaldoSoloLectura(file_path)
    return CRM(file_path)


def crm_status(file_path: str = "crm.json") -> dict:
    """Estado del CRM para /api/health: "local", "nube" o "respaldo_local_solo_lectura"
    (este último con la fecha de modificación de `file_path`, para avisar que es viejo)."""
    if not _supabase_on():
        return {"crm": "local"}
    if _supabase_up():
        return {"crm": "nube"}
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(file_path), timezone.utc).isoformat()
    except OSError:
        mtime = None
    return {"crm": "respaldo_local_solo_lectura", "crm_json_modificado": mtime}


def make_memory(file_path: str = "state.json") -> SessionMemory:
    """Cloud state (ICP, secuencias) if Supabase está configurado — si la tabla
    app_state aún no existe, cae al archivo local sin romper nada."""
    if _supabase_on():
        try:
            from .memory_supabase import SupabaseMemory
            return SupabaseMemory()
        except Exception as e:   # tabla ausente / red — degradar a local con aviso
            print(f"[zero] estado en la nube no disponible ({e}); uso {file_path} local",
                  file=sys.stderr)
    return SessionMemory(file_path)
