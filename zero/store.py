"""Pick the CRM backend — Supabase if configured, else the local JSON file.

This is the single switch between "local dev / mock" and "cloud / team": set
SUPABASE_URL + SUPABASE_KEY and the whole app starts persisting to Postgres
instead of crm.json, with no other code change.
"""
from __future__ import annotations

import os
import sys

from ._env import load_env
from .crm import CRM
from .memory import SessionMemory

load_env()


def _supabase_on() -> bool:
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))


def make_crm(file_path: str = "crm.json"):
    if _supabase_on():
        from .crm_supabase import SupabaseCRM
        return SupabaseCRM()
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
