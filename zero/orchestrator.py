"""ZERO — the orchestrator brain.

ZERO owns strategy and every deliverable. It composes JSON tasks, dispatches them
to sub-agents, validates returned output against the qualified-lead bar, logs every
state change, and assembles the client deliverable.
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    ACTIVE_MARKET_REGIONS,
    AVG_DEAL_VALUE_CLP,
    DEFAULT_VENDOR_ID,
    FORECAST_RATES,
    MAX_INBOUND_MESSAGE_CHARS,
    RECONTACT_BLACKOUT_DAYS,
    REQUIRED_FIELDS,
    email_subject_fallback,
    followup_step,
    min_icp_score,
    project_funnel,
    tier_config,
)
from .channels import Outbox
from .contracts import AgentResponse, Constraints, Lead, TaskPayload
from .icp import describe_icp, is_empty, normalize_icp
from .inbox import Inbox, MockInbox
from .memory import SessionMemory
from .quotes import compute_quote, extract_request, format_quote, normalize_pricing
from .vendors import credentials_for

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


def _merge_qualifier_scores(raw_leads: List[Lead], qual_leads: List[Dict[str, Any]]) -> List[Lead]:
    """QUALIFIER only OWES a score + icp_reasons per lead — every other field
    (company, contacto, canal, dominio) must come from the lead PROSPECTOR already
    found, never from the model re-typing it. Backends real (local/live) no
    siempre devuelven el JSON completo que se les pasó: un modelo chico puede
    omitir `channel`/`email`/`phone` o hasta `role` al reescribir la lista — visto
    en vivo con qwen2.5:7b, de forma no determinista entre corridas. Confiar en
    esos campos re-emitidos rompía el gate de campos requeridos por una falla de
    fidelidad del modelo, no por un lead realmente incompleto.

    Empareja por nombre de empresa (normalizado); una entrada del modelo que no
    calce con ningún lead original (alucinada) se descarta en vez de confiar en
    ella a ciegas."""
    by_company = {(l.company or "").strip().lower(): l for l in raw_leads}
    merged: List[Lead] = []
    for qd in qual_leads:
        base = by_company.get((qd.get("company") or "").strip().lower())
        if base is None:
            continue
        merged.append(Lead.from_dict({
            **base.to_dict(),
            "score": qd.get("score"),
            "icp_reasons": qd.get("icp_reasons"),
        }))
    return merged


# Los criterios con los que BUSCAMOS un lead no son hechos sobre ese lead. `must_have`
# ("atiende consultas seguido", "presencia digital activa") y `exclude` son el filtro de
# prospección: describen qué mirar antes de aceptar a alguien, no algo que se haya
# comprobado del negocio que tenemos al frente.
#
# Encontrado en vivo (2026-08-22): con esos campos en el task, el motor local se los
# afirmó a tres leads distintos —"he visto que atienden consultas frecuentemente por
# WhatsApp"— sin haber visto nada. Es una mentira comprobable en el primer correo que esa
# empresa recibe de nosotros.
#
# Mismo remedio que el `icp` de CONCIERGE (2026-08-21): se corta en el mecanismo, no por
# prompt. Si el dato no viaja, no puede filtrarse a la respuesta. A diferencia de
# CONCIERGE, aquí el lead SÍ fue elegido por el ICP, así que el segmento (`industry`,
# `regions`, `company_size`, `buyer_roles`) sigue siendo cierto y se conserva.
_ICP_SOLO_PROSPECCION = ("must_have", "exclude")


def _icp_para_outreach(icp: Dict[str, Any]) -> Dict[str, Any]:
    """El ICP sin los criterios de filtro — lo que OUTREACH puede decir sin mentir."""
    return {k: v for k, v in (icp or {}).items() if k not in _ICP_SOLO_PROSPECCION}


def _nombre_motor(agent: Any) -> str:
    """Con qué cerebro corrió: 'mock', o el modelo del backend ('qwen2.5:14b…').

    Sirve para responder de un vistazo dos preguntas que hoy hay que adivinar: ¿esto
    salió del mock o de un modelo de verdad?, ¿y entró el respaldo pagado sin que nadie
    lo pidiera? Solo lectura y a prueba de todo — si el backend no expone nada, se
    devuelve cadena vacía en vez de romper el dispatch.
    """
    try:
        if getattr(agent, "mock", False):
            return "mock"
        backend = getattr(agent, "backend", None)
        if backend is None:
            return ""
        # FallbackBackend delega en su primario; el nombre del que de verdad respondió.
        primary = getattr(backend, "primary", None) or backend
        return str(getattr(primary, "model", "") or type(primary).__name__)
    except Exception:   # noqa: BLE001
        return ""


def _asunto(msg: Dict[str, Any], company: Optional[str] = None) -> Optional[str]:
    """El asunto que va al borrador. Para email nunca vacío (ver
    config.email_subject_fallback); para WhatsApp sigue siendo None, que es lo
    correcto: ese canal no tiene asunto."""
    if (msg.get("channel") or "") != "email":
        return msg.get("subject")
    return (msg.get("subject") or "").strip() or email_subject_fallback(
        msg.get("company") or company)


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

    def vendor_by_phone_id(self, phone_id: Optional[str]) -> Dict[str, Any]:
        """The vendor that owns a WhatsApp number (by whatsapp_phone_id), or {} if
        none matches — used to reply from the same number a lead wrote to."""
        if not phone_id:
            return {}
        for v in self.memory.list_vendors():
            if v.get("whatsapp_phone_id") == phone_id:
                return v
        return {}

    def _resolve_inbound_client(self, to_phone_id: Optional[str]) -> Optional[str]:
        """Which client's business context a first-time (unmatched) WhatsApp
        contact should be answered as — see DEFAULT_INBOUND_CLIENT_ID in
        config.py for the policy this implements and why it's needed.

        Tries the number that received the message first: if it resolves to a
        vendor assigned to exactly ONE client, that's unambiguous and correct
        (the path that matters in production, once each client has its own
        WhatsApp number). Zero or several clients sharing that vendor is
        ambiguous — guessing which one could answer a stranger with the wrong
        business's prices — so it falls back to the configured default catch-all
        instead of picking one. Returns None (never a bare guess) if neither
        resolves, e.g. DEFAULT_INBOUND_CLIENT_ID is unset."""
        # Import local (no al tope del módulo): así una prueba que reasigna
        # config.DEFAULT_INBOUND_CLIENT_ID en caliente (ej. para probar el
        # catch-all desactivado) se refleja de inmediato — mismo motivo que
        # WhatsAppSender._template_body importa WHATSAPP_TEMPLATE adentro.
        from .config import DEFAULT_INBOUND_CLIENT_ID
        vendor_id = self.vendor_by_phone_id(to_phone_id).get("id") if to_phone_id else None
        if vendor_id:
            matches = [c for c in self.memory.clients if self.memory.get_client_vendor(c) == vendor_id]
            if len(matches) == 1:
                return matches[0]
        return DEFAULT_INBOUND_CLIENT_ID or None

    # --- sending (OUTREACH/TRACKER draft; the outbox delivers) ---------------
    def _deliver(self, client_id: str, lead_key: str, to: Optional[str],
                 msg: Dict[str, Any], wa_creds: Optional[Tuple[Optional[str], Optional[str]]] = None) -> Dict[str, Any]:
        """Send one drafted message and record the outcome on the CRM record.

        WhatsApp goes out from a vendor's number (its own phone_id/token); the
        outbox uses these only when sending for real. `wa_creds` overrides the
        sender (e.g. reply from the number a lead wrote to); when omitted, it falls
        back to the client's assigned vendor."""
        vendor = self.vendor_for(client_id) if client_id else {}
        if wa_creds is None and (msg.get("channel") or "") == "whatsapp" and client_id:
            wa_creds = credentials_for(vendor)
        payload = {**msg, "to": to}
        # Un correo sin asunto sale con el default del transporte ("Hola" en
        # channels.py): en frío, desde una dirección desconocida, eso es spam.
        # Se rellena acá —el punto por el que pasa TODO envío— para que ningún
        # camino de redacción pueda saltárselo. Ver config.email_subject_fallback.
        if (msg.get("channel") or "") == "email" and not (msg.get("subject") or "").strip():
            payload["subject"] = email_subject_fallback(msg.get("company"))
        # Nombre del remitente en el "From" del email (EmailSender lo usa si viene) —
        # sin esto, el correo sale con la dirección pelada (ej. una Gmail personal),
        # que se ve poco profesional y no dice de parte de quién escribe.
        if vendor.get("name") and (msg.get("channel") or "") == "email":
            payload["from_name"] = vendor["name"]
        res = self.outbox.send(payload, wa_creds=wa_creds)
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
        inicio = time.monotonic()
        if agent is None:
            resp = AgentResponse(task.task_id, agent_name, "error", {}, "no such agent")
        else:
            resp = agent.run(task)
        # Cuánto tardó y con qué motor. Va acá y no dentro de cada agente porque este es
        # el único punto por el que pasan TODOS: un agente nuevo queda medido sin que
        # nadie se acuerde de instrumentarlo. Envuelto en try porque medir jamás puede
        # tumbar lo medido (ver zero/telemetry.py).
        try:
            from .telemetry import registrar
            registrar(agent_name, status=resp.status,
                      ms=(time.monotonic() - inicio) * 1000.0,
                      engine=_nombre_motor(agent), client_id=task.client_id,
                      task_id=task.task_id,
                      in_chars=len(task.to_json() or ""),
                      out_chars=len(json.dumps(resp.result or {}, ensure_ascii=False)))
        except Exception:   # noqa: BLE001
            pass
        self.memory.set_agent_status(agent_name, resp.status)
        self.memory.log(
            "dispatch", agent=agent_name, task_id=task.task_id, status=resp.status, notes=resp.notes
        )
        return resp

    # --- qualified-lead gate -------------------------------------------------
    def validate_lead(
        self, lead: Lead, exclusions: List[str], tier: Optional[str] = None,
        client_id: Optional[str] = None,
    ) -> Tuple[bool, List[str]]:
        """A lead is deliverable only if it passes EVERY check. `tier` selects
        the score bar (config.min_icp_score) — el plan que paga más exige más
        precisión; sin tier (ej. llamadas directas/tests) cae al default.
        `client_id` habilita el chequeo de opt-out (`crm.is_blocked`) — sin él
        (llamadas directas/tests que no pasan cliente) ese chequeo se salta,
        igual que ya hace `tier`."""
        fails: List[str] = []
        bar = min_icp_score(tier)

        if not (lead.email or lead.phone):
            fails.append("sin contacto verificado")
        for f in REQUIRED_FIELDS:
            if not getattr(lead, f, None):
                fails.append(f"falta campo: {f}")
        if lead.score is None or lead.score < bar:
            fails.append(f"score {lead.score} < {bar}")

        dom = (lead.domain or (lead.email.split("@")[-1] if lead.email else "") or "").lower()
        if dom and dom in {e.lower() for e in exclusions}:
            fails.append("en lista de exclusión")

        last = self.memory.contacted.get(lead.key())
        if last and self._days_since(last) < RECONTACT_BLACKOUT_DAYS:
            fails.append(f"contactado hace <{RECONTACT_BLACKOUT_DAYS}d")

        # Opt-out durable: un "no me interesa" de antes bloquea CUALQUIER
        # campaña futura para este cliente, sin importar cuánto tiempo pase —
        # a diferencia del blackout de arriba (temporal), esto nunca expira.
        if client_id and self.crm and self.crm.is_blocked(client_id, lead.key()):
            fails.append("optó por no ser contactado (opt-out)")

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
        self, client_id: str, scored: List[Lead], exclusions: List[str], tier: Optional[str] = None
    ) -> Tuple[List[Lead], List[Dict[str, Any]]]:
        """Run the qualified-lead gate over scored leads, updating CRM + memory log."""
        self.memory.set_stage(client_id, "validate")
        qualified: List[Lead] = []
        rejected: List[Dict[str, Any]] = []
        for lead in scored:
            ok, fails = self.validate_lead(lead, exclusions, tier=tier, client_id=client_id)
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
                        "status": "sent",
                    })
            if msg:
                # Primer contacto por WhatsApp = en frío, el lead nunca escribió antes —
                # Meta exige plantilla pre-aprobada (ver WHATSAPP_TEMPLATE en config.py).
                to_send = ({**msg, "whatsapp_send_type": "template"}
                          if msg.get("channel") == "whatsapp" else msg)
                res = self._deliver(client_id, lead.key(), lead.email or lead.phone, to_send)
                if res["status"] == "sent":
                    sent += 1
            seq = self.memory.open_sequence(client_id, {**lead.to_dict(), "key": lead.key()})
            if seq["step"] == 0:
                sequences_opened += 1
                if self.crm:
                    self.crm.advance(client_id, lead.key(), "nurturing")
        return sequences_opened, sent

    def _draft_first_touch(self, client_id: str, qualified: List[Lead],
                           messages: List[Dict[str, Any]]) -> int:
        """Modo revisión (`auto_send=False`): redacta y guarda el primer mensaje
        en cada lead calificado, SIN mandarlo — el lead se queda en 'calificado'
        (no 'contactado') hasta que alguien lo revise/edite y lo mande a mano
        desde el dashboard (ver `send_pending_outreach`). No abre secuencia de
        seguimiento todavía: esa cadencia empieza a contar desde el contacto
        real, no desde que quedó redactado."""
        if not self.crm:
            return 0
        by_company = {m.get("company"): m for m in messages}
        drafted = 0
        for lead in qualified:
            msg = by_company.get(lead.company)
            if not msg:
                continue
            self.crm.set_outreach(client_id, lead.key(), {
                "channel": msg.get("channel"),
                "subject": _asunto(msg, lead.company),
                "body": msg.get("body"),
                "status": "draft",
            })
            drafted += 1
        return drafted

    def send_pending_outreach(self, client_id: str, lead_key: str,
                              message: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Manda AHORA el mensaje que quedó en borrador (modo revisión) — con el
        texto guardado o, si se pasa `message` (channel/subject/body), con
        ediciones (para mejorar el outbound antes de mandarlo). A diferencia de
        `_send_first_touch` (que avanza la etapa optimistamente para toda una
        corrida), acá solo se avanza a 'contacted'/'nurturing' si el envío
        realmente salió — es un solo lead, vale la pena ser estricto."""
        if not self.crm:
            raise RuntimeError("sin CRM configurado")
        rec = self.crm.get(client_id, lead_key)
        if rec is None:
            raise ValueError("lead no encontrado")
        draft = rec.get("outreach") or {}
        if draft.get("status") != "draft":
            raise ValueError("este lead no tiene un borrador pendiente de envío")
        msg = {
            "channel": (message or {}).get("channel") or draft.get("channel"),
            "subject": (message or {}).get("subject") or draft.get("subject"),
            "body": (message or {}).get("body") or draft.get("body"),
        }
        to = rec.get("email") or rec.get("phone")
        to_send = ({**msg, "whatsapp_send_type": "template"}
                  if msg.get("channel") == "whatsapp" else msg)
        res = self._deliver(client_id, lead_key, to, to_send)
        self.crm.set_outreach(client_id, lead_key,
                              {**msg, "status": "sent" if res["status"] == "sent" else "failed"})
        if res["status"] == "sent":
            self.memory.mark_contacted(lead_key)
            # Distingue primer contacto de seguimiento por si YA hay una
            # secuencia abierta para este lead (la abrió el primer envío) —
            # find_open_sequence no crea nada, a diferencia de open_sequence.
            existing_seq = self.memory.find_open_sequence(client_id, lead_key)
            if existing_seq is not None:
                # Seguimiento (nudge/value/breakup): solo avanza su paso. La
                # etapa del CRM no cambia — ya está en 'nurturing' o donde
                # corresponda desde el primer contacto.
                self.memory.advance_sequence(existing_seq)
            else:
                # Primer contacto: recién ahora abre su secuencia.
                self.crm.advance(client_id, lead_key, "contacted")
                seq = self.memory.open_sequence(client_id, rec)
                if seq["step"] == 0:
                    self.crm.advance(client_id, lead_key, "nurturing")
        return {"lead": self.crm.get(client_id, lead_key), "result": res}

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
        auto_send: bool = True,
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
        # Mercado activo (ver zero.config.ACTIVE_MARKET_REGIONS): si nadie definió
        # zona, no se despacha a PROSPECTOR/QUALIFIER "sin país" — se asume el
        # mercado en el que ZeroAI opera hoy. Se aplica DESPUÉS del chequeo de
        # is_empty()/persistencia de arriba (que sí debe distinguir "el cliente no
        # configuró nada" de "configuró Chile"), y no se guarda de vuelta en
        # memory — es un default de ejecución, no algo que deba "ensuciar" el ICP
        # guardado del cliente.
        if not icp["regions"]:
            icp = {**icp, "regions": list(ACTIVE_MARKET_REGIONS)}

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
        scored = _merge_qualifier_scores(raw_leads, qual.result.get("leads", []))

        # 3) VALIDATE against the qualified-lead definition -------------------
        qualified, rejected = self._validate_and_record(client_id, scored, exclusions, tier=tier)

        # 4) OUTREACH (first touch) ------------------------------------------
        messages: List[Dict[str, Any]] = []
        if write_outreach and qualified:
            self.memory.set_stage(client_id, "outreach")
            # Persona del vendedor asignado (Fernanda/Stéfano/...): mismo patrón que
            # converse_result (CONCIERGE) — solo name/tone, nunca el token/phone_id.
            # Sin esto, OUTREACH no tiene con qué firmar y puede inventar un remitente
            # (visto en vivo: firmaba como "OUTREACH", el nombre interno del agente).
            vendor = self.vendor_for(client_id)
            persona = {"name": vendor.get("name"), "tone": vendor.get("tone")}
            out = self.dispatch("OUTREACH", TaskPayload(
                agent="OUTREACH", client_id=client_id, client_tier=tier,
                instructions="Redacta el primer mensaje para cada lead calificado.",
                data={"leads": [l.to_dict() for l in qualified],
                      "icp": _icp_para_outreach(icp), "vendor": persona,
                      "knowledge": self.memory.get_client_knowledge(client_id)[:4000]},
                constraints=Constraints(channels=channels),
            ))
            if out.status != "error":
                messages = out.result.get("messages", [])

        # 4b) SEND first touch + OPEN FOLLOW-UP SEQUENCES ---------------------
        # (o, si auto_send=False, deja los mensajes en borrador para revisar y
        # mandar a mano desde el dashboard — ver _draft_first_touch)
        sequences_opened, sent, drafted = (0, 0, 0)
        if write_outreach and messages:
            if auto_send:
                sequences_opened, sent = self._send_first_touch(client_id, qualified, messages)
            else:
                drafted = self._draft_first_touch(client_id, qualified, messages)

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
                "drafted": drafted,
                "delivery": "pending_review" if not auto_send else ("live" if self.outbox.live else "mock"),
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
    def run_followups(self, client_id: str, as_of: Optional[str] = None,
                      auto_send: bool = True) -> Dict[str, Any]:
        """Advance every due follow-up: draft the next step, then reschedule/close.

        `auto_send=False` (modo revisión, mismo patrón que run_pipeline): cada
        mensaje queda en borrador en el lead (outreach.status="draft") para
        aprobar a mano desde el dashboard — ver Zero.send_pending_outreach. La
        secuencia NO avanza hasta que de verdad se manda, así el mismo paso no
        se pierde ni se duplica entre corridas."""
        cfg = tier_config(self.memory.clients.get(client_id, {}).get("tier", "STARTER"))
        # First, sweep the inbox: whoever already replied gets its sequence closed
        # here and is never nudged below.
        replies = self.check_replies()
        due = self.memory.due_sequences(client_id, as_of=as_of)
        if not due:
            return {"client_id": client_id, "followups": [], "advanced": 0,
                    "replies_detected": replies["matched"],
                    "notes": "no hay seguimientos pendientes"}

        # Filtrar ANTES de pedirle a TRACKER que redacte nada: sin esto se le
        # pediría un mensaje de todos modos para un lead bloqueado, solo para
        # descartarlo después — con un backend real (Anthropic) eso es una
        # llamada pagada tirada a la basura, no solo trabajo de más.
        # Defensivo: un opt-out ya cierra su secuencia abierta al momento de
        # detectarse (register_reply, en handle_inbound), así que esto
        # normalmente no debería encontrar nada — pero si una secuencia queda
        # abierta por otra vía (bloqueo aplicado fuera de handle_inbound,
        # carrera entre procesos), nunca se manda un follow-up a un lead
        # bloqueado. Se auto-repara: cierra la secuencia en vez de solo saltarla.
        blocked = 0
        if self.crm:
            still_due = []
            for s in due:
                if self.crm.is_blocked(client_id, s["lead_key"]):
                    self.memory.close_sequence_for_lead(client_id, s["lead_key"], reason="blocked")
                    blocked += 1
                else:
                    still_due.append(s)
            due = still_due
        # Modo revisión: no le vuelvas a pedir a TRACKER un mensaje para un
        # lead que ya tiene un borrador esperando aprobación — se perdería el
        # que ya está (quizás editado a mano) y sería trabajo de más.
        if not auto_send and self.crm:
            due = [s for s in due
                  if ((self.crm.get(client_id, s["lead_key"]) or {}).get("outreach") or {}).get("status") != "draft"]
        if not due:
            self.memory.log("followup", client=client_id, advanced=0, sent=0, blocked=blocked)
            self.memory.save()
            return {"client_id": client_id, "followups": [], "advanced": 0, "sent": 0,
                    "blocked": blocked, "replies_detected": replies["matched"],
                    "notes": "no hay seguimientos pendientes"}

        # Attach each sequence's current cadence `kind` for TRACKER.
        payload_seqs = []
        for s in due:
            cadence = followup_step(s["step"]) or {}
            payload_seqs.append({**s, "kind": cadence.get("kind", "nudge")})

        self.memory.set_stage(client_id, "followup")
        # Mismo patrón que OUTREACH (run_pipeline): sin esto, TRACKER no tiene
        # con quién firmar y puede inventar un remitente (ej. su propio nombre
        # de agente, "TRACKER").
        vendor = self.vendor_for(client_id)
        persona = {"name": vendor.get("name"), "tone": vendor.get("tone")}
        resp = self.dispatch("TRACKER", TaskPayload(
            agent="TRACKER", client_id=client_id,
            client_tier=cfg.get("segment", ""),
            instructions="Redacta el siguiente mensaje de seguimiento para cada secuencia vencida.",
            # `knowledge` — encontrado en vivo (2026-07-20): sin esto, el paso
            # "value" (que el prompt le pide sumar "una prueba concreta") no
            # tenía NADA real de dónde sacarla, y el modelo real inventó un
            # caso de cliente falso con una cifra falsa ("redujo sus costos en
            # un 20%") para un lead real recién contactado. Mismo campo que ya
            # recibe OUTREACH — ahora TRACKER tiene algo real de qué hablar.
            data={"sequences": payload_seqs, "vendor": persona,
                  "knowledge": self.memory.get_client_knowledge(client_id)[:4000]},
            constraints=Constraints(channels=cfg["channels"]),
        ))
        if resp.status == "error":
            return self._fail(client_id, "followup", resp)

        messages = resp.result.get("messages", [])
        by_lead = {m.get("lead_key"): m for m in messages}
        sent = 0
        advanced = 0
        skipped = 0
        drafted = 0
        for s in due:   # `due` ya viene filtrado de bloqueados, arriba
            msg = by_lead.get(s["lead_key"])
            if msg is None:
                # El modelo real no devolvió mensaje para este lead (encontrado
                # en vivo, 2026-07-20: a veces pide N y contesta menos que N).
                # Antes esto avanzaba la secuencia igual, en silencio — un paso
                # de la cadencia se saltaba sin que nadie lo notara y sin que
                # el lead recibiera ese toque. Ahora se deja "debida" (se
                # reintenta en la próxima corrida) en vez de darla por hecha.
                if self.crm:
                    self.crm.log(client_id, s["lead_key"], "followup_skip",
                                 "TRACKER no devolvió mensaje para este paso — se reintenta")
                skipped += 1
                continue
            if not auto_send:
                # Modo revisión: el mensaje queda en borrador en el lead, la
                # secuencia NO avanza (se reintentaría redactar de nuevo, pero
                # el filtro de arriba ya evita eso) hasta que se apruebe y
                # mande a mano — ver Zero.send_pending_outreach.
                if self.crm:
                    self.crm.set_outreach(client_id, s["lead_key"], {
                        "channel": msg.get("channel"),
                        "subject": _asunto(msg, s.get("company")),
                        "body": msg.get("body"), "status": "draft",
                    })
                    cadence = followup_step(s["step"]) or {}
                    self.crm.log(client_id, s["lead_key"], "followup_draft",
                                 f"borrador listo, paso {s['step']} ({cadence.get('kind', '')})")
                drafted += 1
                continue
            self.memory.mark_contacted(s["lead_key"])
            if self.crm:
                cadence = followup_step(s["step"]) or {}
                self.crm.log(client_id, s["lead_key"], "followup",
                             f"paso {s['step']} ({cadence.get('kind', '')})")
            rec = self.crm.get(client_id, s["lead_key"]) if self.crm else None
            to = (rec or {}).get("email") or (rec or {}).get("phone")
            # Seguimiento a alguien que no ha respondido = sigue siendo contacto
            # en frío por WhatsApp (fuera de la ventana de 24h) — misma regla que
            # el primer toque: exige plantilla pre-aprobada.
            to_send = ({**msg, "whatsapp_send_type": "template"}
                      if msg.get("channel") == "whatsapp" else msg)
            res = self._deliver(client_id, s["lead_key"], to, to_send)
            if res["status"] == "sent":
                sent += 1
            self.memory.advance_sequence(s)
            advanced += 1
        self.memory.log("followup", client=client_id, advanced=advanced, sent=sent,
                        blocked=blocked, skipped=skipped, drafted=drafted)
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
            "advanced": advanced,
            "sent": sent,
            "blocked": blocked,
            "skipped": skipped,
            "drafted": drafted,
            "delivery": "pending_review" if not auto_send else ("live" if self.outbox.live else "mock"),
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
                        channel: str = "whatsapp",
                        history: Optional[List[Dict[str, Any]]] = None,
                        vendor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Draft a reply to an inbound message using the client's business context
        (ICP + base de conocimiento + historial del diálogo). Pure drafting —
        doesn't send. Returns the full CONCIERGE result ({reply, intent}) so
        callers can act on the intent (e.g. pending offers)."""
        # Un mensaje entrante desmedido (spam, copy-paste de un documento entero)
        # puede hacer que un modelo chico abandone el esquema JSON pedido y
        # devuelva algo irreconocible → reply vacío para el lead, en silencio.
        # Visto en vivo (2026-07-13): 3000 repeticiones de "hola " bastaron.
        message = (message or "")[:MAX_INBOUND_MESSAGE_CHARS]
        # CONCIERGE recibe SOLO qué vende la empresa, no a quién sale a buscar.
        # El resto del ICP (industry, buyer_roles, regions, must_have, exclude,
        # context) es política de PROSPECCIÓN: describe al lead que queremos
        # encontrar, no al lead que ya está escribiendo. MEDIABUYER sí recibe el
        # ICP completo — ahí el targeting es justo el punto.
        #
        # Encontrado en vivo (2026-08-21): con `industry = "empresas de mudanzas"`,
        # el agente abría con "ayudamos a empresas de mudanzas como la tuya" a un
        # lead del que solo sabía el nombre. Pedírselo por prompt NO bastó — el
        # motor local (qwen2.5:14b) siguió usando el campo igual. Se resuelve
        # mecánicamente: si el dato no viaja, no puede filtrarse a la respuesta.
        _icp_completo = self.memory.get_client_icp(client_id) if client_id else {}
        icp = {"sells": _icp_completo["sells"]} if _icp_completo.get("sells") else {}
        # La ficha de la empresa cargada desde el dashboard: acotada para que un
        # documento largo no reviente el presupuesto de contexto del modelo.
        knowledge = (self.memory.get_client_knowledge(client_id) if client_id else "")[:4000]
        # Historial del diálogo (turnos previos, NO incluye `message`): pasado
        # explícito (p.ej. el simulador) o recuperado de memoria por lead.
        if history is None and lead and lead.get("key") and client_id:
            history = self.memory.get_conversation(client_id, lead["key"], limit=12)
        # Persona del vendedor asignado (Fernanda/Stéfano/...): solo name/tone, para
        # que CONCIERGE suene como esa persona. Nunca el token/phone_id (secretos).
        if vendor is None:
            vendor = self.vendor_for(client_id) if client_id else {}
        persona = {"name": vendor.get("name"), "tone": vendor.get("tone")}
        # Presupuesto: si el mensaje pide precios de ítems del catálogo del cliente,
        # se calcula ACÁ (quotes.py, determinista) y se adjunta tras la respuesta del
        # agente — mismo patrón que project_funnel: el LLM redacta, nunca calcula.
        pricing = normalize_pricing(self.memory.get_client_pricing(client_id)) \
            if client_id else {"items": []}
        quote = compute_quote(pricing, extract_request(message, pricing)) \
            if pricing["items"] else None
        instructions = "Responde el mensaje entrante del lead, en su idioma, breve y útil."
        if quote:
            instructions += (" Debajo de tu respuesta se adjuntará un presupuesto ya "
                             "calculado con los ítems que pidió: preséntalo en una frase "
                             "y NO repitas ni inventes montos.")
        resp = self.dispatch("CONCIERGE", TaskPayload(
            agent="CONCIERGE", client_id=client_id or "", client_tier="",
            instructions=instructions,
            data={"message": message, "lead": lead or {}, "icp": _icp_para_outreach(icp), "vendor": persona,
                  "knowledge": knowledge, "history": history or [],
                  "quote": quote or {}},
            constraints=Constraints(channels=[channel]),
        ))
        result = dict(resp.result or {})
        if quote:
            reply = (result.get("reply") or "").strip()
            result["reply"] = (reply + "\n\n" if reply else "") + format_quote(quote)
            result["quote"] = quote
        return result

    def converse(self, client_id: str, message: str,
                 lead: Optional[Dict[str, Any]] = None,
                 channel: str = "whatsapp",
                 history: Optional[List[Dict[str, Any]]] = None,
                 vendor: Optional[Dict[str, Any]] = None) -> str:
        """Reply text only — the seam `handle_inbound` and the 'try the agent'
        tester share so its answers can be evaluated on real questions."""
        return self.converse_result(client_id, message, lead=lead, channel=channel,
                                    history=history, vendor=vendor).get("reply") or ""

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
        así un lead de un anuncio entra al mismo pipeline que el resto. Nunca a
        prueba de opt-out por defecto: alguien que ya dijo 'no me interesa' por
        WhatsApp puede volver a aparecer acá con el mismo email/teléfono (mismo
        lead_key) — se salta por completo, ni se registra ni se cuenta como
        importado, para que quede a la vista que hay algo que Meta le sigue
        mandando pero ZeroAI ya no le va a escribir."""
        if not self.crm:
            return {"imported": 0, "blocked": 0, "client_id": client_id}
        imported = 0
        blocked = 0
        for ld in leads:
            if self.crm.is_blocked_lead(client_id, ld):
                blocked += 1
                continue
            rec = self.crm.upsert(client_id, ld, stage="qualified")
            tags = rec.setdefault("tags", [])
            if "Meta Ads" not in tags:
                tags.append("Meta Ads")
            self.crm.log(client_id, rec["key"], "ad_lead", f"Meta Ads · {ld.get('campaign', '')}")
            imported += 1
        self.crm.save()
        self.memory.log("ad_leads_import", client=client_id, count=imported, blocked=blocked)
        self.memory.save()
        return {"imported": imported, "blocked": blocked, "client_id": client_id}

    def handle_inbound(self, from_contact: str, text: str,
                       channel: str = "whatsapp",
                       to_phone_id: Optional[str] = None) -> Dict[str, Any]:
        """An inbound message arrived (e.g. a WhatsApp reply). Match it to its lead,
        close the loop (`register_reply`), then draft + send a reply with CONCIERGE.
        Reply goes from the vendor that owns `to_phone_id` (the number the lead wrote
        to); falls back to the client's assigned vendor.

        A first-time contact (no existing lead) is NOT ignored — a real sales
        agent answers strangers, not just people ZERO already reached out to.
        It's auto-registered as a new lead (stage "new", source
        "whatsapp_inbound") under whatever client `_resolve_inbound_client`
        resolves to, then handled exactly like a match. Only truly unresolvable
        senders (no CRM at all, or no default configured — see
        DEFAULT_INBOUND_CLIENT_ID in config.py) fall back to the old
        "inbound_unmatched" log-and-stop."""
        rec = self.crm.find_by_contact(phone=from_contact, email=from_contact) if self.crm else None
        if not rec:
            client_id = self._resolve_inbound_client(to_phone_id) if self.crm else None
            if not client_id:
                self.memory.log("inbound_unmatched", channel=channel,
                                sender=from_contact, text=(text or "")[:200])
                self.memory.save()
                return {"matched": False, "sender": from_contact}
            is_email = "@" in from_contact
            rec = self.crm.upsert(client_id, {
                "channel": channel,
                "email": from_contact if is_email else None,
                "phone": None if is_email else from_contact,
                "source": "whatsapp_inbound",
            })
            self.crm.save()
            self.memory.log("inbound_auto_registered", client=client_id,
                            lead=rec["key"], channel=channel, sender=from_contact)
            self.memory.save()

        client_id, key = rec["client_id"], rec["key"]
        # Reply from the number the lead wrote to (its vendor), else the client's vendor.
        inbound_vendor = self.vendor_by_phone_id(to_phone_id)
        wa_creds = credentials_for(inbound_vendor) if inbound_vendor else None
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
            }, wa_creds=wa_creds)
            self.memory.clear_pending_offer(client_id, key)
            self.memory.add_turn(client_id, key, "lead", text)
            self.memory.add_turn(client_id, key, "agent", body)
            self.memory.log("offer_fulfilled", client=client_id, lead=key,
                            kind=pending.get("kind"), channel=out_channel)
            self.memory.save()
            if self.crm:
                self.crm.log(client_id, key, "info_sent",
                             f"resumen + ejemplos ({pending.get('kind')}, {out_channel})")
                self.crm.save()
            return {"matched": True, "company": rec.get("company"), "reply": body,
                    "intent": "fulfill", **out}

        # Redactar ANTES de registrar los turnos: así el historial que ve CONCIERGE
        # son solo los turnos previos (el mensaje actual viaja aparte en `message`).
        res = self.converse_result(client_id, text, lead=rec, channel=channel)
        reply, intent = res.get("reply") or "", res.get("intent") or "general"
        quote = res.get("quote")
        self.memory.add_turn(client_id, key, "lead", text)
        if reply:
            self.memory.add_turn(client_id, key, "agent", reply)
            self._deliver(client_id, key, rec.get("phone") or rec.get("email"),
                          {"channel": channel, "subject": None, "body": reply}, wa_creds=wa_creds)
            if self.crm:
                # Un presupuesto enviado es un evento de venta, no una respuesta más:
                # queda aparte en el historial para que un humano lo vea de un vistazo.
                if quote:
                    self.crm.log(client_id, key, "quote_sent",
                                 f"presupuesto {quote['currency']} {quote['total']:,.0f} "
                                 f"({len(quote['lines'])} ítems)")
                else:
                    self.crm.log(client_id, key, "auto_reply", reply[:140])
                self.crm.save()
        if quote:
            self.memory.log("quote", client=client_id, lead=key,
                            total=quote["total"], currency=quote["currency"],
                            items=[(l["id"], l["qty"]) for l in quote["lines"]])
        self.memory.save()
        # The reply itself made an offer → remember it; an opt-out voids any open one.
        if intent in ("info", "objection"):
            self.memory.set_pending_offer(client_id, key, intent)
            self.memory.save()
        elif intent == "optout":
            if pending:
                self.memory.clear_pending_offer(client_id, key)
                self.memory.save()
            # Bloqueo DURABLE, no solo anular la oferta pendiente de esta
            # conversación — sin esto, nada impedía que este mismo contacto
            # recibiera un mensaje nuevo en una campaña futura (run_pipeline,
            # run_followups, import_ad_leads). Independiente de si había o no
            # una oferta pendiente: "no me interesa" bloquea igual.
            if self.crm:
                self.crm.block(client_id, key, reason="optout")
                self.crm.save()
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
