"""Pick the CRM backend — Supabase if configured, else the local JSON file.

This is the single switch between "local dev / mock" and "cloud / team": set
SUPABASE_URL + SUPABASE_KEY and the whole app starts persisting to Postgres
instead of crm.json, with no other code change.
"""
from __future__ import annotations

import os

from ._env import load_env
from .crm import CRM

load_env()


def make_crm(file_path: str = "crm.json"):
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        from .crm_supabase import SupabaseCRM
        return SupabaseCRM()
    return CRM(file_path)
