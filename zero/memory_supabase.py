"""Supabase-backed session memory — ICP, follow-up sequences and state in the cloud.

Same interface as SessionMemory; only persistence changes (a single JSON snapshot
row in `app_state`, keyed by the agency). So the ICP a client defines survives
restarts and multiple instances, instead of living in a local `state.json`.

Needs a table (run once in Supabase SQL editor):

    create table if not exists app_state (
      id text primary key,
      data jsonb not null default '{}'::jsonb,
      updated timestamptz default now()
    );

If the table is missing, `make_memory` falls back to the local file (nothing breaks).
"""
from __future__ import annotations

import os
from typing import Any, Dict

from ._env import load_env
from ._supabase import SupabaseError, sb_request
from .memory import SessionMemory

load_env()


class CloudStateUnavailable(SupabaseError):
    """Raised when Supabase is configured but the app_state table isn't reachable."""


class SupabaseMemory(SessionMemory):
    TABLE = "app_state"
    ROW_ID = "agency"

    def __init__(self) -> None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not (url and key):
            raise CloudStateUnavailable("faltan SUPABASE_URL / SUPABASE_KEY")
        self.url = url.rstrip("/")
        self.key = key
        super().__init__(path=None)     # empty in-memory fields, no file
        self._load_cloud()              # may raise CloudStateUnavailable

    def _req(self, method: str, path: str, body=None, prefer=None):
        # SupabaseError (incl. table-missing) propagates → make_memory falls back to local.
        return sb_request(self.url, self.key, method, path, body=body, prefer=prefer)

    def _load_cloud(self) -> None:
        rows = self._req("GET", f"{self.TABLE}?id=eq.{self.ROW_ID}&select=data") or []
        if rows:
            d: Dict[str, Any] = rows[0].get("data") or {}
            self.clients = d.get("clients", {})
            self.agent_status = d.get("agent_status", {})
            self.sequences = d.get("sequences", [])
            self.contacted = d.get("contacted", {})
            self.actions = d.get("actions", [])
            self.used_emails = d.get("used_emails", [])

    def save(self) -> None:
        self._req("POST", f"{self.TABLE}?on_conflict=id",
                  body=[{"id": self.ROW_ID, "data": self.snapshot()}],
                  prefer="resolution=merge-duplicates,return=minimal")
