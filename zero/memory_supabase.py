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

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict

from ._env import load_env
from .memory import SessionMemory

load_env()


class CloudStateUnavailable(RuntimeError):
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
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}",
                   "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(f"{self.url}/rest/v1/{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            if e.code in (404, 400) and "app_state" in detail or "PGRST" in detail:
                raise CloudStateUnavailable(f"tabla app_state no disponible: {detail}") from e
            raise CloudStateUnavailable(f"Supabase {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise CloudStateUnavailable(f"no pude contactar a Supabase: {e}") from e

    def _load_cloud(self) -> None:
        rows = self._req("GET", f"{self.TABLE}?id=eq.{self.ROW_ID}&select=data") or []
        if rows:
            d: Dict[str, Any] = rows[0].get("data") or {}
            self.clients = d.get("clients", {})
            self.agent_status = d.get("agent_status", {})
            self.sequences = d.get("sequences", [])
            self.contacted = d.get("contacted", {})
            self.actions = d.get("actions", [])

    def save(self) -> None:
        self._req("POST", f"{self.TABLE}?on_conflict=id",
                  body=[{"id": self.ROW_ID, "data": self.snapshot()}],
                  prefer="resolution=merge-duplicates,return=minimal")
