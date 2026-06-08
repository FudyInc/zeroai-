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
import urllib.parse
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
        self.leads: Dict[str, Dict[str, Any]] = {}   # cache of the clients touched this request
        self._loaded: set = set()                    # client_ids already pulled
        self.path = None
        # No eager load: each request pulls only the client(s) it touches.

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

    def _ensure(self, client_id: Optional[str]) -> None:
        """Pull just this client's rows on first touch (instead of the whole table)."""
        if client_id is None or client_id in self._loaded:
            return
        c = urllib.parse.quote(str(client_id), safe="")
        rows = self._req("GET", f"{self.TABLE}?client_id=eq.{c}&select=*") or []
        for row in rows:
            rec = self._row_to_rec(row)
            self.leads[f"{rec['client_id']}::{rec['key']}"] = rec
        self._loaded.add(client_id)

    def client_ids(self) -> List[str]:
        """Distinct client ids via a tiny projection — never pulls full rows."""
        rows = self._req("GET", f"{self.TABLE}?select=client_id") or []
        return sorted({r["client_id"] for r in rows if r.get("client_id")})

    def find_by_contact(self, phone: Optional[str] = None,
                        email: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Match an inbound (WhatsApp/email reply) to its lead without a full scan.
        Email matches server-side; phone scans a bounded window of recent leads
        (the one that replies was contacted recently) and compares by digits."""
        em = (email or "").strip().lower()
        if em and "@" in em:
            q = urllib.parse.quote(em, safe="")
            rows = self._req("GET", f"{self.TABLE}?email=ilike.{q}&limit=1") or []
            if rows:
                return self._row_to_rec(rows[0])
        pd = "".join(c for c in str(phone or "") if c.isdigit())
        if pd:
            rows = self._req("GET", f"{self.TABLE}?select=*&order=updated.desc&limit=500") or []
            for row in rows:
                rp = "".join(c for c in str(row.get("phone") or "") if c.isdigit())
                if rp and rp == pd:
                    return self._row_to_rec(row)
        return None

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
