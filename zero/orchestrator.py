"""ZERO — the orchestrator brain.

ZERO owns strategy and every deliverable. It composes JSON tasks, dispatches them
to sub-agents, validates returned output against the qualified-lead bar, logs every
state change, and assembles the client deliverable.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    AVG_DEAL_VALUE_CLP,
    DEFAULT_VENDOR_ID,
    FORECAST_RATES,
    MIN_ICP_SCORE,
    RECONTACT_BLACKOUT_DAYS,
    REQUIRED_FIELDS,
    followup_step,
    project_funnel,
    tier_config,
)
from .channels import Outbox
from .contracts import AgentResponse, Constraints, Lead, TaskPayload
from .icp import describe_icp, is_empty, normalize_icp
from .inbox import Inbox, MockInbox
from .memory import SessionMemory

# --- pending offers (the CONCIERGE promises, ZERO fulfills) -------------------
# When the agent replies "te mando un resumen" / "¿te dejo 3 ejemplos?", that's a
# promise. ZERO remembers it (memory.pending_offers) and, when the lead's next
# message accepts, sends the actual summary. The helpers live here — not in the
# agent — because keeping promises is orchestration, not drafting.

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def _word(text: str, *words: str) -> bool:
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def accepts_offer(text: str) -> bool:
    """¿El lead aceptó lo ofrecido (resumen / 3 ejemplos)? Afirmación ("sí",
    "dale", "ok"), elección de canal ("por acá", "al correo") o un correo donde
    mandarlo. Un rechazo explícito nunca acepta, aunque mencione un canal."""
    t = (text or "").lower().strip()
    if _has(t, "no me interesa", "no gracias", "no, gracias", "no quiero",
            "dejen de", "deja de", "stop",
            # objeción, no aceptación — que el "ya" de "ya tenemos proveedor"
            # no cuente como un "ya" afirmativo
            "ya tenemos", "ya trabajamos", "ya contamos", "proveedor"):
        return False
    if _EMAIL_RE.search(t):
        return True
    if _has(t, "por acá", "por aca", "por aquí", "por aqui", "al correo",
            "por correo", "por email", "por mail", "de acuerdo", "me sirve"):
        return True
    return (_word(t, "sí", "si", "dale", "ok", "okey", "okay", "ya", "vale", "bueno",
                  "claro", "perfecto", "listo", "obvio", "correo", "email", "mail")
            and not _word(t, "no"))


def pick_channel(text: str, lead: Dict[str, Any],
                 default_channel: str = "whatsapp") -> Tuple[str, Optional[str]]:
    """(canal, destinatario) para cumplir la oferta: si el lead dio un correo o
    pidió email, va por email; si no, por el canal en que escribió."""
    m = _EMAIL_RE.search(text or "")
    if m:
        return "email", m.group(0)
    if _word((text or "").lower(), "correo", "email", "mail") and lead.get("email"):
        return "email", lead["email"]
    return default_channel, lead.get("phone") or lead.get("email")


def build_info_summary(icp: Dict[str, Any], lead: Optional[Dict[str, Any]] = None) -> str:
    """El resumen corto prometido ("cómo funciona y 3 ejemplos"). Determinista y
    fiel al ICP: solo afirma lo que está en el contexto del cliente; los ejemplos
    salen de icp["examples"] si existen."""
    sells = (icp or {}).get("sells")
    que = (f"ayudamos a empresas como la tuya con {sells}" if sells
           else "te entregamos leads B2B ya calificados, listos para contactar")
    name = (lead or {}).get("name")
    hi = f"Hola {name}" if name else "Hola"
    examples = list((icp or {}).get("examples") or (
        "Gerente de operaciones, empresa industrial mediana — pidió cotización esta semana",
        "Jefe de adquisiciones, retail regional — está comparando proveedores",
        "Dueño de pyme en crecimiento — busca volumen mensual estable",
    ))[:3]
    lines = [f"{hi}, aquí va el resumen prometido 👇",
             f"• Qué hacemos: {que}.",
             "• Cómo funciona: definimos tu cliente ideal, descubrimos y calificamos "
             "leads contra ese perfil, y te llegan listos para contactar.",
             "• 3 ejemplos del tipo de lead que entregamos:"]
    lines += [f"   {i}. {e}" for i, e in enumerate(examples, 1)]
    lines.append("Si te hace sentido, lo vemos en una llamada corta de 10 min. "
                 "¿Te acomoda esta semana?")
    return "\n".join(lines)


class Zero:
    def __init__(self, agents: Dict[str, Any], memory: Optional[SessionMemory] = None,
                 crm: Any = None, outbox: Optional[Outbox] = None,
                 inbox: Optional[Inbox] = None):
        self.agents = agents
        self.memory = memory or SessionMemory()
        self.crm = crm   # optional system of record; pipeline updates it when present
        self.outbox = outbox or Outbox()   # mock by default; sends what gets drafted
        self.inbox = inbox or MockInbox()  # mock by default; where replies get detected

    # --- vendors (Fernanda, Stéfano, ... each with their own WhatsApp) -------
    def vendor_for(self, client_id: str) -> Dict[str, Any]:
        """The sales-agent record assigned to this client (or the default one).

        Does not (yet) change how `run_pipeline`/`handle_inbound` send — that's
        the next phase. For now this just resolves *who* is assigned."""
        vendor_id = self.memory.get_client_vendor(client_id)
        return self.memory.get_vendor(vendor_id) or self.memory.get_vendor(DEFAULT_VENDOR_ID) or {}

    # --- sending (OUTREACH/TRACKER draft; the outbox delivers) ---------------
    def _deliver(self, client_id: str, lead_key: str, to: Optional[str],
                 msg: Dict[str, Any]) -> Dict[str, Any]:
        """Send one drafted message and record the outcome on the CRM record."""
        res = self.outbox.send({**msg, "to": to})
        if self.crm:
            detail = f"{res['channel']} → {to or '—'} [{res['status']}/{res['via']}]"
            if res.get("error"):
                detail += f" · {res['error']}"
            self.crm.log(client_id, lead_key, "send", detail)
        return res

    # --- dispatch protocol ---------------------------------------------------
    def dispatch(self, agent_name: str, task: TaskPayload) -> AgentResponse:
        """Identify → dispatch → record. Validation happens in the caller."""
        agent = self.agents.get(agent_name)
        if agent is None:
            resp = AgentResponse(task.task_id, agent_name, "error", {}, "no such agent")
        else:
            resp = agent.run(task)
        self.memory.set_agent_status(agent_name, resp.status)
        self.memory.log(
            "dispatch", agent=agent_name, task_id=task.task_id, status=resp.status, notes=resp.notes
        )
        return resp

    # --- qualified-lead gate -------------------------------------------------
    def validate_lead(self, lead: Lead, exclusions: List[str]) -> Tuple[bool, List[str]]:
        """A lead is deliverable only if it passes EVERY check."""
        fails: List[str] = []

        if not (lead.email or lead.phone):
            fails.append("sin contacto verificado")
        for f in REQUIRED_FIELDS:
            if not getattr(lead, f, None):
                fails.append(f"falta campo: {f}")
        if lead.score is None or lead.score < MIN_ICP_SCORE:
            fails.append(f"score {lead.score} < {MIN_ICP_SCORE}")

        dom = (lead.domain or (lead.email.split("@")[-1] if lead.email else "") or "").lower()
        if dom and dom in {e.lower() for e in exclusions}:
            fails.append("en lista de exclusión")

        last = self.memory.contacted.get(lead.key())
        if last and self._days_since(last) < RECONTACT_BLACKOUT_DAYS:
            fails.append(f"contactado hace <{RECONTACT_BLACKOUT_DAYS}d")

        return (not fails), fails

    @staticmethod
    def _days_since(iso: str) -> float:
        try:
            dt = datetime.fromisoformat(iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        except Exception:
            return float("inf")

    # --- pipeline steps (helpers for run_pipeline) ---------------------------
    def _validate_and_record(
        self, client_id: str, scored: List[Lead], exclusions: List[str]
    ) -> Tuple[List[Lead], List[Dict[str, Any]]]:
        """Run the qualified-lead gate over scored leads, updating CRM + memory log."""
        self.memory.set_stage(client_id, "validate")
        qualified: List[Lead] = []
        rejected: List[Dict[str, Any]] = []
        for lead in scored:
            ok, fails = self.validate_lead(lead, exclusions)
            if ok:
                qualified.append(lead)
            else:
                rejected.append({"company": lead.company, "score": lead.score, "reasons": fails})
            if self.crm:
                rec = self.crm.upsert(client_id, {**lead.to_dict(), "key": lead.key()},
                                      stage="qualified" if ok else "disqualified")
                # Only note the reasons if the lead actually landed in disqualified
                # (a lead already further along isn't dragged back by a re-run).
                if not ok and rec["stage"] == "disqualified":
                    self.crm.log(client_id, lead.key(), "disqualified", ", ".join(fails))
        self.memory.log(
            "validation", client=client_id,
            qualified=len(qualified), rejected=len(rejected),
        )
        return qualified, rejected

    def _send_first_touch(
        self, client_id: str, qualified: List[Lead], messages: List[Dict[str, Any]]
    ) -> Tuple[int, int]:
        """Deliver the first-touch message to each qualified lead and open its
        follow-up sequence. Returns (sequences_opened, sent)."""
        sequences_opened = 0
        sent = 0
        by_company = {m.get("company"): m for m in messages}
        for lead in qualified:
            self.memory.mark_contacted(lead.key())
            msg = by_company.get(lead.company)
            if self.crm:
                self.crm.advance(client_id, lead.key(), "contacted")
                if msg:
                    self.crm.set_outreach(client_id, lead.key(), {
                        "channel": msg.get("channel"),
                        "subject": msg.get("subject"),
                        "body": msg.get("body"),
                    })
            if msg:
                res = self._deliver(client_id, lead.key(), lead.email or lead.phone, msg)
                if res["status"] == "sent":
                    sent += 1
            seq = self.memory.open_sequence(client_id, {**lead.to_dict(), "key": lead.key()})
            if seq["step"] == 0:
                sequences_opened += 1
                if self.crm:
                    self.crm.advance(client_id, lead.key(), "nurturing")
        return sequences_opened, sent

    # --- the pipeline --------------------------------------------------------
    def run_pipeline(
        self,
        client_id: str,
        tier: str,
        query: str,
        count: int = 8,
        icp: Optional[Dict[str, Any]] = None,
        exclusions: Optional[List[str]] = None,
        write_outreach: bool = True,
    ) -> Dict[str, Any]:
        """discover → enrich → qualify → (validate) → outreach → report."""
        cfg = tier_config(tier)
        channels = cfg["channels"]
        exclusions = exclusions or []
        # ICP: usa el provisto o el guardado del cliente; normaliza y persiste,
        # así cada corrida se adapta al negocio del cliente sin re-enviarlo.
        icp = normalize_icp(icp or self.memory.get_client_icp(client_id))

        self.memory.register_client(client_id, tier)
        if not is_empty(icp):
            self.memory.set_client_icp(client_id, icp)

        # Respect the monthly tier cap on a single run.
        cap = cfg["leads_per_mo"]
        max_items = count if cap is None else min(count, cap)

        # 1) DISCOVER + ENRICH ------------------------------------------------
        self.memory.set_stage(client_id, "discover")
        disc = self.dispatch("PROSPECTOR", TaskPayload(
            agent="PROSPECTOR", client_id=client_id, client_tier=tier,
            instructions=f"Descubre y enriquece leads B2B para: {query}",
            data={"query": query, "icp": icp},
            constraints=Constraints(max_items=max_items, channels=channels),
        ))
        if disc.status == "error":
            return self._fail(client_id, "discover", disc)
        raw_leads = [Lead.from_dict(d) for d in disc.result.get("leads", [])]

        # 2) QUALIFY ----------------------------------------------------------
        self.memory.set_stage(client_id, "qualify")
        qual = self.dispatch("QUALIFIER", TaskPayload(
            agent="QUALIFIER", client_id=client_id, client_tier=tier,
            instructions="Califica e identifica fit ICP (0-100) para estos leads.",
            data={
                "leads": [l.to_dict() for l in raw_leads],
                "icp": icp,
                "scoring": cfg["scoring"],
            },
            constraints=Constraints(max_items=max_items, channels=channels),
        ))
        if qual.status == "error":
            return self._fail(client_id, "qualify", qual)
        scored = [Lead.from_dict(d) for d in qual.result.get("leads", [])]

        # 3) VALIDATE against the qualified-lead definition -------------------
        qualified, rejected = self._validate_and_record(client_id, scored, exclusions)

        # 4) OUTREACH (first touch) ------------------------------------------
        messages: List[Dict[str, Any]] = []
        if write_outreach and qualified:
            self.memory.set_stage(client_id, "outreach")
            out = self.dispatch("OUTREACH", TaskPayload(
                agent="OUTREACH", client_id=client_id, client_tier=tier,
                instructions="Redacta el primer mensaje para cada lead calificado.",
                data={"leads": [l.to_dict() for l in qualified], "icp": icp},
                constraints=Constraints(channels=channels),
            ))
            if out.status != "error":
                messages = out.result.get("messages", [])

        # 4b) SEND first touch + OPEN FOLLOW-UP SEQUENCES --------------------
        sequences_opened, sent = (0, 0)
        if write_outreach and messages:
            sequences_opened, sent = self._send_first_touch(client_id, qualified, messages)

        # 5) REPORT -----------------------------------------------------------
        self.memory.set_stage(client_id, "delivered")
        deliverable = {
            "client_id": client_id,
            "tier": tier,
            "query": query,
            "summary": {
                "discovered": len(raw_leads),
                "scored": len(scored),
                "qualified": len(qualified),
                "rejected": len(rejected),
                "sequences_opened": sequences_opened,
                "sent": sent,
                "delivery": "live" if self.outbox.live else "mock",
                "channels": channels,
                "scoring_model": cfg["scoring"],
                "icp": describe_icp(icp),
            },
            "qualified_leads": [l.to_dict() for l in qualified],
            "rejected": rejected,
            "outreach": messages,
        }
        self.memory.log("delivered", client=client_id, qualified=len(qualified))
        self.memory.save()
        if self.crm:
            self.crm.save()
        return deliverable

    # --- follow-ups (TRACKER) -----------------------------------------------
    def run_followups(self, client_id: str, as_of: Optional[str] = None) -> Dict[str, Any]:
        """Advance every due follow-up: draft the next step, then reschedule/close."""
        cfg = tier_config(self.memory.clients.get(client_id, {}).get("tier", "STARTER"))
        # First, sweep the inbox: whoever already replied gets its sequence closed
        # here and is never nudged below.
        replies = self.check_replies()
        due = self.memory.due_sequences(client_id, as_of=as_of)
        if not due:
            return {"client_id": client_id, "followups": [], "advanced": 0,
                    "replies_detected": replies["matched"],
                    "notes": "no hay seguimientos pendientes"}

        # Attach each sequence's current cadence `kind` for TRACKER.
        payload_seqs = []
        for s in due:
            cadence = followup_step(s["step"]) or {}
            payload_seqs.append({**s, "kind": cadence.get("kind", "nudge")})

        self.memory.set_stage(client_id, "followup")
        resp = self.dispatch("TRACKER", TaskPayload(
            agent="TRACKER", client_id=client_id,
            client_tier=cfg.get("segment", ""),
            instructions="Redacta el siguiente mensaje de seguimiento para cada secuencia vencida.",
            data={"sequences": payload_seqs},
            constraints=Constraints(channels=cfg["channels"]),
        ))
        if resp.status == "error":
            return self._fail(client_id, "followup", resp)

        messages = resp.result.get("messages", [])
        by_lead = {m.get("lead_key"): m for m in messages}
        sent = 0
        for s in due:
            self.memory.mark_contacted(s["lead_key"])
            if self.crm:
                cadence = followup_step(s["step"]) or {}
                self.crm.log(client_id, s["lead_key"], "followup",
                             f"paso {s['step']} ({cadence.get('kind', '')})")
            msg = by_lead.get(s["lead_key"])
            if msg:
                rec = self.crm.get(client_id, s["lead_key"]) if self.crm else None
                to = (rec or {}).get("email") or (rec or {}).get("phone")
                res = self._deliver(client_id, s["lead_key"], to, msg)
                if res["status"] == "sent":
                    sent += 1
            self.memory.advance_sequence(s)
        self.memory.log("followup", client=client_id, advanced=len(due), sent=sent)
        self.memory.set_stage(client_id, "delivered")
        self.memory.save()
        if self.crm:
            self.crm.save()
        open_remaining = sum(
            1 for s in self.memory.sequences
            if s["client_id"] == client_id and s["status"] == "open"
        )
        return {
            "client_id": client_id,
            "advanced": len(due),
            "sent": sent,
            "delivery": "live" if self.outbox.live else "mock",
            "replies_detected": replies["matched"],
            "open_remaining": open_remaining,
            "followups": messages,
        }

    # --- reply detection (closes sequences automatically) ---------------------
    def check_replies(self) -> Dict[str, Any]:
        """Pull unread inbound messages and close the loop for each one via
        `handle_inbound` (match → register_reply → CONCIERGE). The inbox is mock
        and empty by default, so this is a free no-op until a real source
        (inbox.json drop-box, IMAP) is plugged in."""
        msgs = self.inbox.fetch()
        results = []
        for m in msgs:
            out = self.handle_inbound(m["from"], m["body"], channel=m["channel"])
            results.append({"from": m["from"], "channel": m["channel"],
                            "matched": out.get("matched", False),
                            "company": out.get("company"),
                            "sequence_closed": out.get("sequence_closed", False)})
        matched = sum(1 for r in results if r["matched"])
        if msgs:
            self.memory.log("replies_check", checked=len(msgs), matched=matched)
            self.memory.save()
        return {"checked": len(msgs), "matched": matched,
                "source": "live" if self.inbox.live else "mock",
                "replies": results}

    # --- inbound reply (closes the loop) -------------------------------------
    def register_reply(self, client_id: str, lead_key: str,
                       text: Optional[str] = None,
                       channel: Optional[str] = None) -> Dict[str, Any]:
        """A lead replied: stop chasing it and hand it to a human.

        Closes the follow-up sequence (TRACKER stops nudging someone who already
        answered) and moves the CRM record forward to `replied`. Forward-only:
        a lead already at `meeting`/`won` isn't dragged back. This is the seam an
        inbox/webhook plugs into later; the logic here is pure and testable.
        """
        lead_key = str(lead_key).lower()
        closed = self.memory.close_sequence_for_lead(client_id, lead_key, reason="replied")

        moved = None
        if self.crm:
            detail = (text.strip()[:120] if text and text.strip() else "respuesta recibida")
            moved = self.crm.advance(client_id, lead_key, "replied", detail=detail)

        self.memory.log("reply", client=client_id, lead=lead_key,
                        channel=channel, sequence_closed=bool(closed),
                        text=(text or "")[:500])
        self.memory.save()
        if self.crm:
            self.crm.save()

        open_remaining = sum(
            1 for s in self.memory.sequences
            if s["client_id"] == client_id and s["status"] == "open"
        )
        return {
            "client_id": client_id,
            "lead_key": lead_key,
            "stage": moved["stage"] if moved else None,
            "sequence_closed": bool(closed),
            "open_remaining": open_remaining,
        }

    def converse_result(self, client_id: str, message: str,
                        lead: Optional[Dict[str, Any]] = None,
                        channel: str = "whatsapp") -> Dict[str, Any]:
        """Draft a reply to an inbound message using the client's business context
        (ICP). Pure drafting — doesn't send. Returns the full CONCIERGE result
        ({reply, intent}) so callers can act on the intent (e.g. pending offers)."""
        icp = self.memory.get_client_icp(client_id) if client_id else {}
        resp = self.dispatch("CONCIERGE", TaskPayload(
            agent="CONCIERGE", client_id=client_id or "", client_tier="",
            instructions="Responde el mensaje entrante del lead, en su idioma, breve y útil.",
            data={"message": message, "lead": lead or {}, "icp": icp},
            constraints=Constraints(channels=[channel]),
        ))
        return resp.result or {}

    def converse(self, client_id: str, message: str,
                 lead: Optional[Dict[str, Any]] = None,
                 channel: str = "whatsapp") -> str:
        """Reply text only — the seam `handle_inbound` and the 'try the agent'
        tester share so its answers can be evaluated on real questions."""
        return self.converse_result(client_id, message, lead=lead, channel=channel).get("reply") or ""

    def optimize_campaigns(self, client_id: str, campaigns: List[Dict[str, Any]],
                           good_cpl_clp: int = 6000) -> Dict[str, Any]:
        """MEDIABUYER analiza las campañas y devuelve recomendaciones + plan
        (recomienda, no gasta). Usa el ICP del cliente para alinear el targeting."""
        icp = self.memory.get_client_icp(client_id) if client_id else {}
        resp = self.dispatch("MEDIABUYER", TaskPayload(
            agent="MEDIABUYER", client_id=client_id or "", client_tier="",
            instructions="Analiza las campañas y propone un plan de gestión (Chile, foco Santiago).",
            data={"campaigns": campaigns, "good_cpl_clp": good_cpl_clp, "icp": icp},
        ))
        return resp.result if resp.status != "error" else {"recommendations": [], "plan": resp.notes or ""}

    def write_pitch(self, prospect: Dict[str, Any], notes: str = "") -> Dict[str, Any]:
        """PITCHWRITER redacta un pitch de venta creativo y personalizado (anti-plantilla)."""
        resp = self.dispatch("PITCHWRITER", TaskPayload(
            agent="PITCHWRITER", client_id="", client_tier="",
            instructions="Escribe un pitch de venta creativo, personalizado y distinto cada vez.",
            data={"prospect": prospect or {}, "notes": notes or ""},
        ))
        return resp.result if resp.status != "error" else {"subject": "", "body": ""}

    def import_ad_leads(self, client_id: str, leads: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Mete los leads de Meta Lead Ads al CRM (etapa qualified, tag 'Meta Ads') —
        así un lead de un anuncio entra al mismo pipeline que el resto."""
        if not self.crm:
            return {"imported": 0, "client_id": client_id}
        imported = 0
        for ld in leads:
            rec = self.crm.upsert(client_id, ld, stage="qualified")
            tags = rec.setdefault("tags", [])
            if "Meta Ads" not in tags:
                tags.append("Meta Ads")
            self.crm.log(client_id, rec["key"], "ad_lead", f"Meta Ads · {ld.get('campaign', '')}")
            imported += 1
        self.crm.save()
        self.memory.log("ad_leads_import", client=client_id, count=imported)
        self.memory.save()
        return {"imported": imported, "client_id": client_id}

    def handle_inbound(self, from_contact: str, text: str,
                       channel: str = "whatsapp") -> Dict[str, Any]:
        """An inbound message arrived (e.g. a WhatsApp reply). Match it to its lead,
        close the loop (`register_reply`), then draft + send a reply with CONCIERGE.
        Unmatched senders are logged (a number we never contacted), not an error."""
        rec = self.crm.find_by_contact(phone=from_contact, email=from_contact) if self.crm else None
        if not rec:
            self.memory.log("inbound_unmatched", channel=channel,
                            sender=from_contact, text=(text or "")[:200])
            self.memory.save()
            return {"matched": False, "sender": from_contact}

        client_id, key = rec["client_id"], rec["key"]
        out = self.register_reply(client_id, key, text=text, channel=channel)

        # An offer was pending (summary / 3 examples) and the lead accepted:
        # fulfill it instead of drafting — a promise kept beats a fresh pitch.
        pending = self.memory.get_pending_offer(client_id, key)
        if pending and accepts_offer(text):
            body = build_info_summary(self.memory.get_client_icp(client_id), rec)
            out_channel, to = pick_channel(text, rec, default_channel=channel)
            self._deliver(client_id, key, to, {
                "channel": out_channel,
                "subject": "ZeroAI — resumen y 3 ejemplos" if out_channel == "email" else None,
                "body": body,
            })
            self.memory.clear_pending_offer(client_id, key)
            self.memory.log("offer_fulfilled", client=client_id, lead=key,
                            kind=pending.get("kind"), channel=out_channel)
            self.memory.save()
            if self.crm:
                self.crm.log(client_id, key, "info_sent",
                             f"resumen + ejemplos ({pending.get('kind')}, {out_channel})")
                self.crm.save()
            return {"matched": True, "company": rec.get("company"), "reply": body,
                    "intent": "fulfill", **out}

        res = self.converse_result(client_id, text, lead=rec, channel=channel)
        reply, intent = res.get("reply") or "", res.get("intent") or "general"
        if reply:
            self._deliver(client_id, key, rec.get("phone") or rec.get("email"),
                          {"channel": channel, "subject": None, "body": reply})
            if self.crm:
                self.crm.log(client_id, key, "auto_reply", reply[:140])
                self.crm.save()
        # The reply itself made an offer → remember it; an opt-out voids any open one.
        if intent in ("info", "objection"):
            self.memory.set_pending_offer(client_id, key, intent)
            self.memory.save()
        elif intent == "optout" and pending:
            self.memory.clear_pending_offer(client_id, key)
            self.memory.save()
        return {"matched": True, "company": rec.get("company"), "reply": reply,
                "intent": intent, **out}

    # --- forecasting (ANALYST proposes rates; ZERO does the math) ------------
    def forecast(self, client_id: str) -> Dict[str, Any]:
        """Project pipeline for a client from its logged activity.

        ANALYST only decides the conversion rates; the funnel arithmetic is
        deterministic (`project_funnel`), so the numbers are exact on any backend.
        """
        cfg = tier_config(self.memory.clients.get(client_id, {}).get("tier", "STARTER"))
        metrics = self._client_metrics(client_id)
        self.memory.set_stage(client_id, "forecast")
        resp = self.dispatch("ANALYST", TaskPayload(
            agent="ANALYST", client_id=client_id,
            client_tier=cfg.get("segment", ""),
            instructions="Revisa y, si corresponde, ajusta las tasas de conversión. No calcules.",
            data={"metrics": metrics, "rates": FORECAST_RATES},
        ))
        if resp.status == "error":
            return self._fail(client_id, "forecast", resp)

        proposed = resp.result.get("rates") or {}
        projection = project_funnel(metrics["contacted"], proposed, AVG_DEAL_VALUE_CLP)
        rates_used = projection.pop("_rates_used")
        forecast = {
            "inputs": metrics,
            "assumptions": {**rates_used, "avg_deal_value_clp": AVG_DEAL_VALUE_CLP},
            "projection": projection,
            "commentary": resp.result.get("commentary"),
        }
        self.memory.log("forecast", client=client_id,
                        pipeline_clp=projection["expected_pipeline_clp"])
        self.memory.set_stage(client_id, "delivered")
        self.memory.save()
        return {"client_id": client_id, "forecast": forecast, "notes": resp.notes}

    def _client_metrics(self, client_id: str) -> Dict[str, Any]:
        """Aggregate this client's funnel counts from the audit log + state."""
        discovered = qualified = 0
        for a in self.memory.actions:
            if a.get("action") == "validation" and a.get("client") == client_id:
                qualified += int(a.get("qualified", 0))
                discovered += int(a.get("qualified", 0)) + int(a.get("rejected", 0))

        seqs = [s for s in self.memory.sequences if s["client_id"] == client_id]
        open_sequences = sum(1 for s in seqs if s["status"] == "open")
        contacted = len(seqs)  # one sequence per contacted, qualified lead
        return {
            "discovered": discovered,
            "qualified": qualified,
            "contacted": contacted or qualified,
            "open_sequences": open_sequences,
        }

    def _fail(self, client_id: str, stage: str, resp: AgentResponse) -> Dict[str, Any]:
        self.memory.set_stage(client_id, f"error:{stage}")
        self.memory.log("pipeline_error", client=client_id, stage=stage, notes=resp.notes)
        self.memory.save()
        return {"client_id": client_id, "error": stage, "notes": resp.notes}
