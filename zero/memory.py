"""Session memory & pipeline state.

ZERO never loses pipeline state to a context reset: everything client-facing or
state-changing is logged here and persisted to JSON. `handoff()` emits the compact
snapshot the system prompt calls a "state handoff block".
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import followup_step


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


class SessionMemory:
    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else None
        self.clients: Dict[str, Dict[str, Any]] = {}      # client_id -> {tier, stage}
        self.agent_status: Dict[str, str] = {}            # agent -> last status
        self.sequences: List[Dict[str, Any]] = []         # open follow-ups
        self.contacted: Dict[str, str] = {}               # lead key -> iso timestamp
        self.actions: List[Dict[str, Any]] = []           # audit log
        if self.path and self.path.exists():
            self._load()

    # --- mutations -----------------------------------------------------------
    def register_client(self, client_id: str, tier: str) -> None:
        self.clients.setdefault(client_id, {})
        self.clients[client_id]["tier"] = tier
        self.clients[client_id].setdefault("stage", "registered")

    def set_stage(self, client_id: str, stage: str) -> None:
        self.clients.setdefault(client_id, {})["stage"] = stage

    def set_client_icp(self, client_id: str, icp: Dict[str, Any]) -> None:
        """Persist the client's ICP so later runs reuse it without re-sending."""
        self.clients.setdefault(client_id, {})["icp"] = icp

    def get_client_icp(self, client_id: str) -> Dict[str, Any]:
        return self.clients.get(client_id, {}).get("icp") or {}

    def set_client_meta(self, client_id: str, meta: Dict[str, Any]) -> None:
        """Per-client marketing config (Meta ad account, presupuesto, zonas)."""
        self.clients.setdefault(client_id, {})["meta"] = meta

    def get_client_meta(self, client_id: str) -> Dict[str, Any]:
        return self.clients.get(client_id, {}).get("meta") or {}

    def set_agent_status(self, agent: str, status: str) -> None:
        self.agent_status[agent] = status

    def mark_contacted(self, lead_key: str) -> None:
        self.contacted[lead_key] = _now()

    # --- follow-up sequences (TRACKER) ---------------------------------------
    def open_sequence(self, client_id: str, lead: Dict[str, Any], started: Optional[str] = None) -> Dict[str, Any]:
        """Open a follow-up sequence for a lead, due at the first cadence step.

        Idempotent per (client, lead): re-opening an existing open sequence is a
        no-op so a re-run of the pipeline never duplicates follow-ups.
        """
        key = lead.get("key") or lead.get("email") or lead.get("phone") or f"{lead.get('company')}|{lead.get('role')}"
        key = str(key).lower()
        for s in self.sequences:
            if s["client_id"] == client_id and s["lead_key"] == key and s["status"] == "open":
                return s
        started = started or _now()
        seq = {
            "client_id": client_id,
            "lead_key": key,
            "company": lead.get("company"),
            "name": lead.get("name"),
            "role": lead.get("role"),
            "channel": lead.get("channel"),
            "step": 0,                       # index of the next follow-up to send
            "started": started,
            "next_due": self._due_at(started, 0),
            "status": "open",
        }
        self.sequences.append(seq)
        return seq

    def due_sequences(self, client_id: Optional[str] = None, as_of: Optional[str] = None) -> List[Dict[str, Any]]:
        """Open sequences whose next follow-up is due at/before `as_of` (now)."""
        cutoff = _parse(as_of) if as_of else datetime.now(timezone.utc)
        out = []
        for s in self.sequences:
            if s["status"] != "open":
                continue
            if client_id and s["client_id"] != client_id:
                continue
            if s.get("next_due") and _parse(s["next_due"]) <= cutoff:
                out.append(s)
        return out

    def advance_sequence(self, seq: Dict[str, Any]) -> Dict[str, Any]:
        """Mark the current step sent and schedule the next, or close the sequence."""
        seq["step"] += 1
        if followup_step(seq["step"]) is None:
            seq["status"] = "closed"
            seq["next_due"] = None
        else:
            seq["next_due"] = self._due_at(seq["started"], seq["step"])
        return seq

    def close_sequence_for_lead(self, client_id: str, lead_key: str,
                                reason: str = "replied") -> Optional[Dict[str, Any]]:
        """Stop chasing a lead: close its open follow-up sequence (e.g. it replied).

        Returns the closed sequence, or None if there was no open one (the lead
        may have replied to the first touch before any follow-up opened).
        """
        lead_key = str(lead_key).lower()
        for s in self.sequences:
            if s["client_id"] == client_id and s["lead_key"] == lead_key and s["status"] == "open":
                s["status"] = "closed"
                s["next_due"] = None
                s["closed_reason"] = reason
                return s
        return None

    @staticmethod
    def _due_at(started: str, step: int) -> Optional[str]:
        cadence = followup_step(step)
        if cadence is None:
            return None
        return (_parse(started) + timedelta(days=cadence["day"])).isoformat()

    def log(self, action: str, **fields: Any) -> None:
        """Record any client-facing or state-changing action."""
        self.actions.append({"ts": _now(), "action": action, **fields})

    # --- persistence ---------------------------------------------------------
    def save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.snapshot(), ensure_ascii=False, indent=2), "utf-8")

    def _load(self) -> None:
        try:
            d = json.loads(self.path.read_text("utf-8"))
        except (ValueError, OSError) as e:
            raise RuntimeError(
                f"Estado corrupto o ilegible en {self.path}: {e}. "
                f"Revisá o restaurá el archivo (no lo sobrescribo para no perder datos)."
            ) from e
        self.clients = d.get("clients", {})
        self.agent_status = d.get("agent_status", {})
        self.sequences = d.get("sequences", [])
        self.contacted = d.get("contacted", {})
        self.actions = d.get("actions", [])

    # --- snapshots -----------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        return {
            "clients": self.clients,
            "agent_status": self.agent_status,
            "sequences": self.sequences,
            "contacted": self.contacted,
            "actions": self.actions,
        }

    def handoff(self) -> Dict[str, Any]:
        """Compact state handoff block for context continuation."""
        return {
            "handoff": _now(),
            "clients": self.clients,
            "agent_status": self.agent_status,
            "open_sequences": len(self.sequences),
            "actions_logged": len(self.actions),
        }
