"""ZERO — the orchestrator brain.

ZERO owns strategy and every deliverable. It composes JSON tasks, dispatches them
to sub-agents, validates returned output against the qualified-lead bar, logs every
state change, and assembles the client deliverable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    AVG_DEAL_VALUE_USD,
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
from .memory import SessionMemory


class Zero:
    def __init__(self, agents: Dict[str, Any], memory: Optional[SessionMemory] = None,
                 crm: Any = None, outbox: Optional[Outbox] = None):
        self.agents = agents
        self.memory = memory or SessionMemory()
        self.crm = crm   # optional system of record; pipeline updates it when present
        self.outbox = outbox or Outbox()   # mock by default; sends what gets drafted

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
        sequences_opened = 0
        sent = 0
        if write_outreach and messages:
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
        due = self.memory.due_sequences(client_id, as_of=as_of)
        if not due:
            return {"client_id": client_id, "followups": [], "advanced": 0,
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
            "open_remaining": open_remaining,
            "followups": messages,
        }

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

    def converse(self, client_id: str, message: str,
                 lead: Optional[Dict[str, Any]] = None,
                 channel: str = "whatsapp") -> str:
        """Draft a reply to an inbound message using the client's business context
        (ICP). Pure drafting — doesn't send. Used both by `handle_inbound` and the
        'try the agent' tester so its answers can be evaluated on real questions."""
        icp = self.memory.get_client_icp(client_id) if client_id else {}
        resp = self.dispatch("CONCIERGE", TaskPayload(
            agent="CONCIERGE", client_id=client_id or "", client_tier="",
            instructions="Responde el mensaje entrante del lead, en su idioma, breve y útil.",
            data={"message": message, "lead": lead or {}, "icp": icp},
            constraints=Constraints(channels=[channel]),
        ))
        return resp.result.get("reply") or ""

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

        reply = self.converse(client_id, text, lead=rec, channel=channel)
        if reply:
            self._deliver(client_id, key, rec.get("phone") or rec.get("email"),
                          {"channel": channel, "subject": None, "body": reply})
            if self.crm:
                self.crm.log(client_id, key, "auto_reply", reply[:140])
                self.crm.save()
        return {"matched": True, "company": rec.get("company"), "reply": reply, **out}

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
        projection = project_funnel(metrics["contacted"], proposed, AVG_DEAL_VALUE_USD)
        rates_used = projection.pop("_rates_used")
        forecast = {
            "inputs": metrics,
            "assumptions": {**rates_used, "avg_deal_value_usd": AVG_DEAL_VALUE_USD},
            "projection": projection,
            "commentary": resp.result.get("commentary"),
        }
        self.memory.log("forecast", client=client_id,
                        pipeline_usd=projection["expected_pipeline_usd"])
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
