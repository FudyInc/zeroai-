"""CRM — ZERO's durable system of record for leads.

Where `SessionMemory` holds per-run pipeline state, the CRM is the lead database
that persists across runs: one record per (client, lead) with its pipeline stage
and a full interaction history. PROSPECTOR/QUALIFIER fill it, OUTREACH/TRACKER
move leads along it, and ANALYST can read it. Plain JSON, no external service.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import CRM_STAGES

_FIELDS = ("company", "name", "role", "email", "phone", "domain", "score", "channel", "icp_reasons")

# Funnel progression order, for forward-only automatic transitions. `disqualified`
# sits beside `qualified`; both terminal stages share the highest rank so a re-run
# can't drag a closed lead backwards.
_ORDER = {
    "new": 0, "qualified": 1, "disqualified": 1, "contacted": 2, "nurturing": 3,
    "replied": 4, "meeting": 5, "won": 6, "lost": 6,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def lead_key(lead: Dict[str, Any]) -> str:
    """Stable identity, matching contracts.Lead.key()."""
    k = lead.get("key") or lead.get("email") or lead.get("phone") \
        or f"{lead.get('company')}|{lead.get('role')}"
    return str(k).lower()


class CRM:
    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else None
        self.leads: Dict[str, Dict[str, Any]] = {}   # "client::key" -> record
        if self.path and self.path.exists():
            self._load()

    # --- core ----------------------------------------------------------------
    def _rid(self, client_id: str, key: str) -> str:
        return f"{client_id}::{key}"

    def _ensure(self, client_id: Optional[str]) -> None:
        """Hook for scoped backends to lazily load a client's rows on demand.
        No-op for the in-memory/file CRM — everything is already in `self.leads`."""
        pass

    def client_ids(self) -> List[str]:
        """Distinct client ids — so listing accounts never needs a full scan."""
        return sorted({r["client_id"] for r in self.leads.values()})

    def upsert(self, client_id: str, lead: Dict[str, Any], stage: Optional[str] = None) -> Dict[str, Any]:
        """Create or update a lead record; optionally move it to `stage`."""
        self._ensure(client_id)
        key = lead_key(lead)
        rid = self._rid(client_id, key)
        rec = self.leads.get(rid)
        if rec is None:
            rec = {
                "client_id": client_id, "key": key,
                **{f: lead.get(f) for f in _FIELDS},
                "stage": "new", "tags": [],
                "created": _now(), "updated": _now(), "history": [],
            }
            self.leads[rid] = rec
            self._event(rec, "created", lead.get("source") or "pipeline")
        else:
            for f in _FIELDS:                       # fill/refresh known fields
                if lead.get(f) is not None:
                    rec[f] = lead.get(f)
            rec["updated"] = _now()
        if stage:
            self.advance(client_id, key, stage)     # forward-only (won't regress a closed lead)
        return rec

    def advance(self, client_id: str, key: str, stage: str, detail: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Move a lead to `stage` only if it's a forward step in the funnel.

        Used for automatic pipeline transitions so re-running never drags a lead
        backwards. Manual moves should call `set_stage`, which is unconditional.
        """
        self._ensure(client_id)
        rec = self.leads.get(self._rid(client_id, key))
        if rec is None:
            return None
        if _ORDER.get(stage, 0) >= _ORDER.get(rec["stage"], 0):
            return self.set_stage(client_id, key, stage, detail)
        return rec

    def set_stage(self, client_id: str, key: str, stage: str, detail: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if stage not in CRM_STAGES:
            raise ValueError(f"etapa inválida: {stage!r}. Válidas: {list(CRM_STAGES)}")
        self._ensure(client_id)
        rec = self.leads.get(self._rid(client_id, key))
        if rec is None:
            return None
        if rec["stage"] != stage:
            self._event(rec, "stage", f"{rec['stage']} → {stage}" + (f" ({detail})" if detail else ""))
            rec["stage"] = stage
            rec["updated"] = _now()
        return rec

    def log(self, client_id: str, key: str, event: str, detail: Optional[str] = None) -> None:
        self._ensure(client_id)
        rec = self.leads.get(self._rid(client_id, key))
        if rec is not None:
            self._event(rec, event, detail)

    def set_outreach(self, client_id: str, key: str, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Store the first-touch message on the lead (the 'ready to contact' part)."""
        self._ensure(client_id)
        rec = self.leads.get(self._rid(client_id, key))
        if rec is None:
            return None
        rec["outreach"] = message
        rec["updated"] = _now()
        self._event(rec, "outreach", "primer toque listo (" + (message.get("channel") or "—") + ")")
        return rec

    def _event(self, rec: Dict[str, Any], event: str, detail: Optional[str]) -> None:
        rec.setdefault("history", []).append({"ts": _now(), "event": event, "detail": detail})

    # --- queries -------------------------------------------------------------
    def get(self, client_id: str, key: str) -> Optional[Dict[str, Any]]:
        self._ensure(client_id)
        return self.leads.get(self._rid(client_id, key))

    def find_by_contact(self, phone: Optional[str] = None,
                        email: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Locate a lead by phone or email — how an inbound message (WhatsApp reply,
        email reply) is matched back to its lead. Phones compare by digits only."""
        pd = "".join(c for c in str(phone or "") if c.isdigit())
        em = (email or "").strip().lower()
        for rec in self.leads.values():
            rp = "".join(c for c in str(rec.get("phone") or "") if c.isdigit())
            if pd and rp and rp == pd:
                return rec
            if em and (rec.get("email") or "").lower() == em:
                return rec
        return None

    def list(self, client_id: Optional[str] = None, stage: Optional[str] = None,
             limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        self._ensure(client_id)
        out = [r for r in self.leads.values()
               if (client_id is None or r["client_id"] == client_id)
               and (stage is None or r["stage"] == stage)]
        out.sort(key=lambda r: (-(r.get("score") or 0), r.get("company") or ""))
        if limit is not None:
            return out[offset:offset + limit]
        return out[offset:] if offset else out

    def board(self, client_id: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Leads grouped by stage, in pipeline order."""
        return {stage: self.list(client_id, stage) for stage in CRM_STAGES}

    def counts(self, client_id: Optional[str] = None) -> Dict[str, int]:
        return {stage: len(self.list(client_id, stage)) for stage in CRM_STAGES}

    # --- persistence ---------------------------------------------------------
    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"leads": self.leads}, ensure_ascii=False, indent=2), "utf-8")

    def _load(self) -> None:
        try:
            self.leads = json.loads(self.path.read_text("utf-8")).get("leads", {})
        except (ValueError, OSError) as e:
            raise RuntimeError(
                f"CRM corrupto o ilegible en {self.path}: {e}. "
                f"Revisá o restaurá el archivo (no lo sobrescribo para no perder datos)."
            ) from e
