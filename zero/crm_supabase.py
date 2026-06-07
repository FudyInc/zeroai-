"""Supabase-backed CRM — same interface as crm.CRM, stored in Postgres.

It subclasses CRM and only overrides *storage* (`_load` / `save`), so every bit of
funnel logic (upsert, advance, stages, history, outreach) is reused untouched.
Talks to Supabase's PostgREST API over stdlib urllib (no extra dependency).

Needs in the environment / .env:
  SUPABASE_URL  ·  SUPABASE_KEY  (service_role key — backend side)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ._env import load_env
from .crm import CRM

load_env()

# columns that map 1:1 between record and row (lead_key/key handled separately)
_PLAIN = ("client_id", "company", "name", "role", "email", "phone", "domain",
          "score", "channel", "stage", "created", "updated")
_JSONB = ("icp_reasons", "outreach", "tags", "history")


class SupabaseCRM(CRM):
    TABLE = "crm_leads"

    def __init__(self):
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not (url and key):
            raise RuntimeError("Faltan SUPABASE_URL y/o SUPABASE_KEY")
        self.url = url.rstrip("/")
        self.key = key
        self.leads: Dict[str, Dict[str, Any]] = {}
        self.path = None
        self._load()

    # --- storage (the only thing that differs from the file CRM) -------------
    def _req(self, method: str, path: str, body=None, prefer: Optional[str] = None):
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(f"{self.url}/rest/v1/{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Supabase {e.code}: {e.read().decode('utf-8', 'replace')}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"No pude contactar a Supabase: {e}") from e

    def _load(self) -> None:
        rows = self._req("GET", f"{self.TABLE}?select=*") or []
        self.leads = {}
        for row in rows:
            rec = self._row_to_rec(row)
            self.leads[f"{rec['client_id']}::{rec['key']}"] = rec

    def save(self) -> None:
        if not self.leads:
            return
        payload = [self._rec_to_row(r) for r in self.leads.values()]
        self._req("POST", f"{self.TABLE}?on_conflict=client_id,lead_key",
                  body=payload, prefer="resolution=merge-duplicates,return=minimal")

    # --- record <-> row mapping ---------------------------------------------
    @staticmethod
    def _rec_to_row(rec: Dict[str, Any]) -> Dict[str, Any]:
        row = {k: rec.get(k) for k in _PLAIN}
        row["lead_key"] = rec.get("key")
        for k in _JSONB:
            row[k] = rec.get(k) if rec.get(k) is not None else ([] if k != "outreach" else None)
        return row

    @staticmethod
    def _row_to_rec(row: Dict[str, Any]) -> Dict[str, Any]:
        rec = {k: row.get(k) for k in _PLAIN}
        rec["key"] = row.get("lead_key")
        for k in _JSONB:
            rec[k] = row.get(k) if row.get(k) is not None else ([] if k != "outreach" else None)
        return rec
