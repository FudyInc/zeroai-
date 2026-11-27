"""Pick the CRM backend — Supabase if configured, else the local JSON file.

This is the single switch between "local dev / mock" and "cloud / team": set
SUPABASE_URL + SUPABASE_KEY and the whole app starts persisting to Postgres
instead of crm.json, with no other code change.
"""
from __future__ import annotations

import os
import sys

from ._env import load_env
from ._supabase import SupabaseError
from .crm import CRM
from .memory import SessionMemory

load_env()


def _supabase_on() -> bool:
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


def make_crm(file_path: str = "crm.json"):
    """CRM en la nube si Supabase está configurado Y responde; si no, el archivo local.
    `SupabaseCRM` carga perezoso (el fallo real llegaría en la primera operación,
    ya dentro del endpoint), así que acá se hace una sonda mínima al construirlo:
    es el único punto donde aún se puede elegir otro backend. Mientras dure la caída
    lo que se escriba queda en `file_path`; no se sincroniza de vuelta a Supabase."""
    if _supabase_on():
        from .crm_supabase import SupabaseCRM
        try:
            crm = SupabaseCRM()
            crm._req("GET", f"{crm.TABLE}?select=client_id&limit=1")
            return crm
        except SupabaseError as e:   # cuota (402) / red / tabla — degradar a local con aviso
            print(f"[zero] CRM en la nube no disponible ({e}); uso {file_path} local",
                  file=sys.stderr)
    return CRM(file_path)


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
