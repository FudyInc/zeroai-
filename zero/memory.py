"""Session memory & pipeline state.

ZERO never loses pipeline state to a context reset: everything client-facing or
state-changing is logged here and persisted to JSON. `handoff()` emits the compact
snapshot the system prompt calls a "state handoff block".
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import DEFAULT_VENDOR_ID, followup_step
from .persistence import load_json, save_json
from .vendors import seed_vendors


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
        self.used_emails: List[str] = []                  # correos ya contactados (autocompletar)
        self.pending_offers: Dict[str, Dict[str, Any]] = {}  # "client|lead" -> oferta hecha y aún no cumplida
        self.vendors: Dict[str, Dict[str, Any]] = {}      # vendor_id -> Vendor (catálogo)
        self.functions: Dict[str, Dict[str, Any]] = {}    # function_id -> función programada (fase 2 sandbox)
        if self.path and self.path.exists():
            self._load()

    def add_used_email(self, email: str) -> None:
        """Recuerda un correo ya usado, para sugerirlo al escribir después."""
        e = (email or "").strip().lower()
        if e and "@" in e and e not in self.used_emails:
            self.used_emails.append(e)

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

    # --- knowledge base (la "ficha de la empresa" que carga el dashboard) -----
    def set_client_knowledge(self, client_id: str, knowledge: str) -> None:
        """Texto libre sobre el negocio del cliente (qué vende, precios, horarios,
        tono, políticas...). Es el contexto que hace personal al agente."""
        self.clients.setdefault(client_id, {})["knowledge"] = (knowledge or "").strip()

    def get_client_knowledge(self, client_id: str) -> str:
        return self.clients.get(client_id, {}).get("knowledge") or ""

    # --- pricing (lista de precios estructurada, para presupuestos) -----------
    def set_client_pricing(self, client_id: str, pricing: Dict[str, Any]) -> None:
        """Lista de precios del cliente (ya normalizada por quotes.normalize_pricing).
        Estructurada aparte del knowledge: los presupuestos se calculan en código
        y necesitan números, no texto libre."""
        self.clients.setdefault(client_id, {})["pricing"] = pricing

    def get_client_pricing(self, client_id: str) -> Dict[str, Any]:
        return self.clients.get(client_id, {}).get("pricing") or {}

    # --- conversation history (memoria del diálogo con cada lead) -------------
    # Vive dentro de la ficha del cliente (junto a icp/meta/knowledge), así el
    # snapshot no cambia de forma y snapshots viejos siguen restaurando bien.
    MAX_TURNS_STORED = 200   # por lead; el diálogo útil nunca es infinito

    def add_turn(self, client_id: str, lead_key: str, role: str, text: str) -> None:
        """Registra un turno del diálogo ('lead' o 'agent') para ese lead."""
        text = (text or "").strip()
        if not text:
            return
        convs = self.clients.setdefault(client_id, {}).setdefault("conversations", {})
        turns = convs.setdefault(str(lead_key).lower(), [])
        turns.append({"role": role, "text": text[:2000], "at": _now()})
        if len(turns) > self.MAX_TURNS_STORED:
            del turns[: len(turns) - self.MAX_TURNS_STORED]

    def get_conversation(self, client_id: str, lead_key: str,
                         limit: Optional[int] = None) -> List[Dict[str, Any]]:
        convs = self.clients.get(client_id, {}).get("conversations") or {}
        turns = convs.get(str(lead_key).lower(), [])
        return turns[-limit:] if limit else list(turns)

    # --- vendor catalog (Fernanda, Stéfano, ... each with their own WhatsApp) --
    def _ensure_vendors_seeded(self) -> None:
        if not self.vendors:
            for v in seed_vendors():
                self.vendors[v["id"]] = v

    def list_vendors(self) -> List[Dict[str, Any]]:
        self._ensure_vendors_seeded()
        return list(self.vendors.values())

    def get_vendor(self, vendor_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_vendors_seeded()
        return self.vendors.get(vendor_id)

    def upsert_vendor(self, vendor: Dict[str, Any]) -> None:
        self._ensure_vendors_seeded()
        self.vendors[vendor["id"]] = vendor

    # --- funciones programadas (fase 2: registro + ejecución manual sobre
    # zero/sandbox.py — el disparo automático por horario es una decisión
    # aparte, todavía no existe) -----------------------------------------------
    def list_functions(self) -> List[Dict[str, Any]]:
        return list(self.functions.values())

    def get_function(self, function_id: str) -> Optional[Dict[str, Any]]:
        return self.functions.get(function_id)

    def upsert_function(self, function: Dict[str, Any]) -> None:
        self.functions[function["id"]] = function

    def delete_function(self, function_id: str) -> bool:
        """True si existía y se borró; False si no había ninguna con ese id."""
        return self.functions.pop(function_id, None) is not None

    # --- client -> vendor assignment ------------------------------------------
    def set_client_vendor(self, client_id: str, vendor_id: str) -> None:
        self.clients.setdefault(client_id, {})["vendor_id"] = vendor_id

    def get_client_vendor(self, client_id: str) -> str:
        """Vendor id assigned to this client, or DEFAULT_VENDOR_ID if none."""
        return self.clients.get(client_id, {}).get("vendor_id") or DEFAULT_VENDOR_ID

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

    def find_open_sequence(self, client_id: str, lead_key: str) -> Optional[Dict[str, Any]]:
        """La secuencia abierta de este lead, sin importar si está due todavía —
        a diferencia de due_sequences(), que solo trae las vencidas. Usado para
        distinguir un envío de PRIMER contacto (sin secuencia abierta todavía)
        de un envío de SEGUIMIENTO (ya tiene una), al mandar un borrador
        aprobado a mano desde el dashboard."""
        for s in self.sequences:
            if s["client_id"] == client_id and s["lead_key"] == lead_key and s["status"] == "open":
                return s
        return None

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

    # --- pending offers (CONCIERGE promises, ZERO fulfills) -------------------
    @staticmethod
    def _offer_key(client_id: str, lead_key: str) -> str:
        return f"{client_id}|{str(lead_key).lower()}"

    def set_pending_offer(self, client_id: str, lead_key: str, kind: str) -> None:
        """El CONCIERGE ofreció algo (resumen/ejemplos); queda pendiente de cumplir."""
        self.pending_offers[self._offer_key(client_id, lead_key)] = {"kind": kind, "ts": _now()}

    def get_pending_offer(self, client_id: str, lead_key: str) -> Optional[Dict[str, Any]]:
        return self.pending_offers.get(self._offer_key(client_id, lead_key))

    def clear_pending_offer(self, client_id: str, lead_key: str) -> None:
        self.pending_offers.pop(self._offer_key(client_id, lead_key), None)

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
        """Escritura atómica con backup rotado (`state.json.bak`) — ver `persistence.py`."""
        if not self.path:
            return
        save_json(self.path, self.snapshot())

    def _load(self) -> None:
        # load_json ya intenta el .bak antes de rendirse; si igual falla, propaga
        # el RuntimeError tal cual (mismo comportamiento de antes: nunca arranca
        # vacío en silencio).
        self._restore(load_json(self.path))

    def _restore(self, d: Dict[str, Any]) -> None:
        """Rehydrate from a snapshot dict — the single place that knows the field
        list, shared by every persistence backend (file, Supabase)."""
        self.clients = d.get("clients", {})
        self.agent_status = d.get("agent_status", {})
        self.sequences = d.get("sequences", [])
        self.contacted = d.get("contacted", {})
        self.actions = d.get("actions", [])
        self.used_emails = d.get("used_emails", [])
        self.pending_offers = d.get("pending_offers", {})
        self.vendors = d.get("vendors", {})
        self.functions = d.get("functions", {})

    # --- snapshots -----------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        return {
            "clients": self.clients,
            "agent_status": self.agent_status,
            "sequences": self.sequences,
            "contacted": self.contacted,
            "actions": self.actions,
            "used_emails": self.used_emails,
            "pending_offers": self.pending_offers,
            "vendors": self.vendors,
            "functions": self.functions,
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
