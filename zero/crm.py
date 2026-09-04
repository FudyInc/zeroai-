"""CRM — ZERO's durable system of record for leads.

Where `SessionMemory` holds per-run pipeline state, the CRM is the lead database
that persists across runs: one record per (client, lead) with its pipeline stage
and a full interaction history. PROSPECTOR/QUALIFIER fill it, OUTREACH/TRACKER
move leads along it, and ANALYST can read it. Plain JSON, no external service.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import CRM_STAGES
from .persistence import load_json, save_json

# Qué campos de un lead persiste el CRM. Lo que no esté acá se descarta en
# upsert(), en silencio: el contrato es esta tupla, no `contracts.Lead`.
# `activity` (a qué se dedica el negocio) y `source` (de dónde salió) ya existían
# en contracts.Lead y se perdían al guardar — un lead entraba al CRM sin poder
# decir de qué vive ni cómo llegó. `segment` lo trae el formulario público de la
# landing, que es hoy el único que pregunta.
_FIELDS = ("company", "name", "role", "email", "phone", "domain", "score", "channel",
           "icp_reasons", "activity", "source", "segment", "industry")

# Opt-out permanente — reusa el campo `tags` que ya existe (mismo campo que usa
# import_ad_leads para "Meta Ads"), en vez de inventar uno paralelo. `tags` NO
# está en _FIELDS, así que upsert() nunca lo pisa al refrescar un lead que
# vuelve a aparecer en un discovery futuro — el bloqueo es forward-only por
# construcción, no por una regla aparte que haya que recordar mantener.
BLOCK_TAG = "no-contactar"

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

    # --- opt-out (durable, forward-only) --------------------------------------
    def block(self, client_id: str, key: str, reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Marca un lead como bloqueado (opt-out) para este cliente — no una
        pausa temporal, no se revierte solo porque el contacto vuelve a
        aparecer en un discovery/Meta Ads futuro. Idempotente: llamarlo dos
        veces no duplica el tag ni el evento de historial."""
        self._ensure(client_id)
        rec = self.leads.get(self._rid(client_id, key))
        if rec is None:
            return None
        tags = rec.setdefault("tags", [])
        if BLOCK_TAG not in tags:
            tags.append(BLOCK_TAG)
            rec["updated"] = _now()
            self._event(rec, "blocked", reason or "opt-out")
        return rec

    def is_blocked(self, client_id: str, key: str) -> bool:
        """¿Este lead (ya en el CRM) está bloqueado?"""
        self._ensure(client_id)
        rec = self.leads.get(self._rid(client_id, key))
        return bool(rec and BLOCK_TAG in (rec.get("tags") or []))

    def is_blocked_lead(self, client_id: str, lead: Dict[str, Any]) -> bool:
        """Como is_blocked, pero a partir de un dict de lead crudo (discovery,
        Meta Ads) — para decidir SI conviene registrarlo/contactarlo, no solo
        consultar un registro que ya existe."""
        return self.is_blocked(client_id, lead_key(lead))

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

    def search(self, q: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Cross-client search by company/email/phone substring — for finding a
        lead without already knowing which client account it belongs to (unlike
        `list`/`query`, which always scope to one client). Case-insensitive."""
        needle = (q or "").strip().lower()
        if not needle:
            return []
        out: List[Dict[str, Any]] = []
        for cid in self.client_ids():
            for rec in self.list(cid):
                if (needle in (rec.get("company") or "").lower()
                        or needle in (rec.get("email") or "").lower()
                        or needle in (rec.get("phone") or "").lower()):
                    out.append(rec)
        out.sort(key=lambda r: (-(r.get("score") or 0), r.get("company") or "", r.get("key") or ""))
        return out[:limit]

    def list(self, client_id: Optional[str] = None, stage: Optional[str] = None,
             limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        self._ensure(client_id)
        out = [r for r in self.leads.values()
               if (client_id is None or r["client_id"] == client_id)
               and (stage is None or r["stage"] == stage)]
        out.sort(key=lambda r: (-(r.get("score") or 0), r.get("company") or "", r.get("key") or ""))
        if limit is not None:
            return out[offset:offset + limit]
        return out[offset:] if offset else out

    def query(self, client_id: str, stages: Optional[List[str]] = None,
              limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        """Paginated lookup for the Leads table: one client, an optional set of
        stages (a group filter), sorted by score, sliced by limit/offset."""
        self._ensure(client_id)
        out = [r for r in self.leads.values()
               if r["client_id"] == client_id and (stages is None or r["stage"] in stages)]
        # key as a unique tiebreaker → stable, non-overlapping pages
        out.sort(key=lambda r: (-(r.get("score") or 0), r.get("company") or "", r.get("key") or ""))
        return out[offset:offset + limit] if limit is not None else out[offset:]

    def board(self, client_id: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
        """Leads grouped by stage, in pipeline order."""
        return {stage: self.list(client_id, stage) for stage in CRM_STAGES}

    def counts(self, client_id: Optional[str] = None) -> Dict[str, int]:
        return {stage: len(self.list(client_id, stage)) for stage in CRM_STAGES}

    def all_leads(self) -> List[Dict[str, Any]]:
        """Todos los leads de TODOS los clientes — para exportar la cartera
        completa (ej. sincronización a Google Sheets, ver zero/sheets.py).
        Mismo patrón que pending_outreach_count(): fuerza la carga de cada
        cliente primero, así SupabaseCRM no devuelve solo lo que ya tenía en
        cache de requests anteriores."""
        for cid in self.client_ids():
            self._ensure(cid)
        return list(self.leads.values())

    def pending_outreach_count(self) -> int:
        """Cuántos leads, en TODOS los clientes, tienen un borrador de outreach
        esperando revisión/envío (outreach.status == "draft") — el trabajo
        pendiente central del rol CCO (panel de Equipo). Para SupabaseCRM esto
        recorre todos los client_ids primero (carga perezosa vía _ensure) —
        con el volumen de hoy (un puñado de clientes) es barato; si el CRM
        crece mucho valdría la pena una query server-side en vez de esto."""
        for cid in self.client_ids():
            self._ensure(cid)
        return sum(1 for r in self.leads.values() if (r.get("outreach") or {}).get("status") == "draft")

    def pending_outreach(self, client_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Los leads con un borrador esperando aprobación, de un cliente o de
        todos. Misma definición que pending_outreach_count() (outreach.status
        == "draft") — el contador y la lista no pueden discrepar, así que
        comparten el predicado.

        Ordenados del borrador más viejo al más nuevo: lo que lleva más tiempo
        esperando es lo que más urge revisar. Un lead sin fecha en el borrador
        (registros viejos, antes de que se guardara `at`) va al final en vez de
        romper el orden."""
        for cid in self.client_ids():
            self._ensure(cid)
        rows = [r for r in self.leads.values()
                if (r.get("outreach") or {}).get("status") == "draft"
                and (client_id is None or r.get("client_id") == client_id)]
        return sorted(rows, key=lambda r: (r.get("outreach") or {}).get("at") or "9999")

    def clear(self, client_id: str) -> int:
        """Borra TODOS los leads de un cliente (ej. limpiar datos de prueba antes
        de una corrida real). Irreversible salvo por el `.bak` de save(). Devuelve
        cuántos se borraron, para que quien llama pueda confirmar/loguear."""
        rids = [rid for rid, r in self.leads.items() if r["client_id"] == client_id]
        for rid in rids:
            del self.leads[rid]
        return len(rids)

    # --- persistence ---------------------------------------------------------
    def save(self) -> None:
        """Escritura atómica con backup rotado (`crm.json.bak`) — ver `persistence.py`."""
        if not self.path:
            return
        save_json(self.path, {"leads": self.leads})

    def _load(self) -> None:
        # load_json ya intenta el .bak antes de rendirse; si igual falla, propaga
        # el RuntimeError tal cual (mismo comportamiento de antes: nunca arranca
        # vacío en silencio).
        self.leads = load_json(self.path).get("leads", {})
