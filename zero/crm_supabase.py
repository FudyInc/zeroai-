"""Supabase-backed CRM — same interface as crm.CRM, stored in Postgres.

It subclasses CRM and only overrides *storage* (`_load` / `save`), so every bit of
funnel logic (upsert, advance, stages, history, outreach) is reused untouched.
Talks to Supabase's PostgREST API over stdlib urllib (no extra dependency).

Needs in the environment / .env:
  SUPABASE_URL  ·  SUPABASE_KEY  (service_role key — backend side)
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Any, Dict, List, Optional

from ._env import load_env
from ._supabase import sb_request
from .config import CRM_STAGES
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
        return sb_request(self.url, self.key, method, path, body=body, prefer=prefer)

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

    def query(self, client_id: str, stages: Optional[List[str]] = None,
              limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        """Paginate server-side: PostgREST does the filter, sort and slice — we never
        pull more than one page of one client's leads."""
        c = urllib.parse.quote(str(client_id), safe="")
        # lead_key as a unique tiebreaker → a total order, so pages never overlap.
        path = f"{self.TABLE}?client_id=eq.{c}&order=score.desc.nullslast,company.asc,lead_key.asc"
        if stages:
            path += f"&stage=in.({','.join(stages)})"
        if limit is not None:
            path += f"&limit={int(limit)}&offset={int(offset)}"
        rows = self._req("GET", path) or []
        return [self._row_to_rec(r) for r in rows]

    def counts(self, client_id: Optional[str] = None) -> Dict[str, int]:
        """Stage counts via a `stage`-only projection — for KPIs we don't pull full
        rows. `client_id=None` aggregates across accounts (agency overview)."""
        path = f"{self.TABLE}?select=stage"
        if client_id is not None:
            path += f"&client_id=eq.{urllib.parse.quote(str(client_id), safe='')}"
        rows = self._req("GET", path) or []
        out = {s: 0 for s in CRM_STAGES}
        for r in rows:
            st = r.get("stage")
            if st in out:
                out[st] += 1
        return out

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

    def search(self, q: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Cross-client search, server-side — the one query that intentionally
        spans every account (no client_id filter), same sort as query()."""
        needle = (q or "").strip()
        if not needle:
            return []
        v = urllib.parse.quote(needle, safe="")
        path = (f"{self.TABLE}?or=(company.ilike.*{v}*,email.ilike.*{v}*,phone.ilike.*{v}*)"
                f"&order=score.desc.nullslast,company.asc&limit={int(limit)}")
        rows = self._req("GET", path) or []
        return [self._row_to_rec(r) for r in rows]

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
