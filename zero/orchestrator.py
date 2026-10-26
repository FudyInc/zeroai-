"""ZERO — the orchestrator brain.

ZERO owns strategy and every deliverable. It composes JSON tasks, dispatches them
to sub-agents, validates returned output against the qualified-lead bar, logs every
state change, and assembles the client deliverable.
"""
from __future__ import annotations

import difflib
import json
import hashlib

import logging

import os
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    LOSETASCHILE_CHOICE_STYLE,
    LOSETASCHILE_PAGO_GENERICO,
    LOSETASCHILE_TEMAS_SIN_INVENTAR,
    ACTIVE_MARKET_REGIONS,
    AVG_DEAL_VALUE_CLP,
    DEFAULT_VENDOR_ID,
    LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE,
    LOSETASCHILE_WHATSAPP_CATALOG_URL,
    FORECAST_RATES,
    MAX_INBOUND_MESSAGE_CHARS,
    QUOTE_REVIEW_REQUIRED_CLIENT_IDS,
    RECONTACT_BLACKOUT_DAYS,
    REQUIRED_FIELDS,
    email_subject_fallback,
    followup_step,
    min_icp_score,
    project_funnel,
    tier_config,
    WHATSAPP_FALLBACK_GREETINGS,
    WHATSAPP_FALLBACK_GREETINGS_NAMED,
    WHATSAPP_REVIEW_NOTICES,
)
from .channels import Outbox
from .agent_rules import check_reply
from .contracts import AgentResponse, Constraints, Lead, TaskPayload
from .icp import describe_icp, is_empty, normalize_icp
from .inbox import Inbox, MockInbox
from .losetas_color import (COLOR_CATALOG_IMAGE_PATH, color_preference,
                            color_question, latest_color_preference)
from .losetas_budget import format_internal_budget
from .losetas_text import normalize_customer_text, plain
from .attention import fixed_answer, learned_alias, learned_answer
from .losetas_shipping import (SHIPPING_COVERAGE_REPLY, SHIPPING_PRICE_REPLY,
                               delivery_detail, delivery_poll_choice_response,
                               shipping_coverage_request, shipping_delivery_followup)
from .losetas_polls import (DELIVERY_POLL_QUESTION as LOSETAS_DELIVERY_POLL_QUESTION,
                            PRODUCT_POLL_QUESTION,
                            category_for_poll_choice, poll_answer_for_history,
                            direct_product_category, selected_category_from_history,
                            is_factory_pickup, FACTORY_ADDRESS, FACTORY_MAP_URL,
                            paver_order_details, canonical_choice, numbered_choices,
                            BORDER_MODEL_QUESTION, POOL_SHAPE_QUESTION,
                            PAVER_AREA_QUESTION, PAVER_MODEL_QUESTION,
                            WHATSAPP_WEB_POLL_KEYS)
from .memory import SessionMemory
from .quotes import compute_quote, extract_request, format_quote, normalize_pricing
from .pool_border import (POOL_PHOTO_MARKER, POOL_PHOTO_REQUEST, _MEASUREMENT_QUESTION as POOL_MEASUREMENT_QUESTION,
                          pool_photo_followup, roman_pool,
                          border_plan, catalog_requested, visual_catalog_category,
                          delegates_piece_calculation,
                          format_product_quote, shipping_price_request,
                          border_model_followup, measurement_followup, pool_shape_followup,
                          unquoted_piece_count,
                          wants_border_budget, wants_product_quote,
                          pool_border_models_reply, pool_measurement_message)
from .vendors import credentials_for
from .whatsapp_context import select_history, select_knowledge
from .whatsapp_format import format_whatsapp_reply, pick_variant
from .whatsapp_greeting import align_opening_greeting, whatsapp_greeting

# --- pending offers (the CONCIERGE promises, ZERO fulfills) -------------------
# When the agent replies "te mando un resumen" / "¿te dejo 3 ejemplos?", that's a
# promise. ZERO remembers it (memory.pending_offers) and, when the lead's next
# message accepts, sends the actual summary. The helpers live here — not in the
# agent — because keeping promises is orchestration, not drafting.

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

_QUOTE_REQUEST_RE = re.compile(
    r"\b(precio|precios|costo|costos|cu[aá]nto|valor|cotiza\w*|presupuesto)\b",
    re.IGNORECASE,
)

_HUMAN_REQUEST_RE = re.compile(
    r"\b(?:hablar|conversar|comunicarme|contactarme|atenderme)\s+con\s+(?:un[ao]?\s+)?(?:humano|persona|asesor[ae]?|vendedor[ae]?)\b"
    r"|\b(?:quiero|necesito|prefiero)\s+(?:que\s+me\s+atienda\s+)?(?:un[ao]?\s+)?(?:humano|persona|asesor[ae]?)\b",
    re.IGNORECASE,
)


def _same_reply(first: str, second: str) -> bool:
    normalize = lambda value: " ".join(re.findall(r"\w+", (value or "").casefold()))
    return bool(normalize(first) and normalize(first) == normalize(second))


# Saludos que se combinan entre sí: «Hola buenas tardes», «Hola, buenas noches,
# ¿cómo están?». Visto en vivo (2026-10-15): «Hola buenas tardes» no estaba en la
# lista cerrada anterior, llegó al modelo y nunca se mandó la encuesta de producto.
_GREETING_WORD = (r"(?:h?o+la+s?|hla|holi+s?|w[ae]{1,2}na+s?|buenas|saludos|"
                  r"buen[oa]?s?\s+(?:d[ií]as?|tardes|noches)|"
                  r"qu[eé]\s+tal|c[oó]mo\s+(?:est[aá][sn]?|va)(?:\s+(?:ustedes|usted|todo))?)")
_GREETING_SEP = r"[\s,!¡¿?.]+"
_GREETING_RE = re.compile(
    rf"[\s¡¿]*{_GREETING_WORD}(?:{_GREETING_SEP}{_GREETING_WORD}){{0,3}}[\s!?.,]*",
    re.IGNORECASE)


# «Hola, soy nuevo» describe al contacto; no es su nombre.
_NOT_A_NAME = frozenset({
    "nuevo", "nueva", "cliente", "clienta", "arquitecto", "arquitecta", "constructor",
    "constructora", "contratista", "particular", "empresa", "instalador", "instaladora",
    "maestro", "vecino", "vecina", "yo", "el", "la", "de", "del", "un", "una",
})


def _introduced_name(text: str) -> Optional[str]:
    match = re.fullmatch(
        rf"(?:{_GREETING_WORD}{_GREETING_SEP}){{0,3}}(?:me llamo|soy)\s+([^\W\d_]{{2,30}})[.!?]*",
        (text or "").strip(), re.IGNORECASE | re.UNICODE)
    if not match or match.group(1).casefold() in _NOT_A_NAME:
        return None
    return match.group(1).capitalize()


def _simple_greeting(text: str) -> bool:
    return bool(_GREETING_RE.fullmatch(text or "")) or _introduced_name(text) is not None


def _unreadable_whatsapp_message(text: str, client_id: str = "") -> bool:
    value = (text or "").strip()
    # Both Meta and the Web bridge use bracketed placeholders for attachments.
    # LosetasChile handles a location as delivery data in its quote flow.
    if re.fullmatch(r"\[location\](?:\s+https://www\.google\.com/maps\?q=[-\d.]+,[-\d.]+)?",
                    value, re.IGNORECASE):
        return client_id != "losetaschile"
    if re.fullmatch(r"\[[a-z_]+\]", value, re.IGNORECASE):
        return True
    # A single apparent keyboard mash with a long consonant run is not a
    # product question. Do not apply this to longer messages or model codes.
    return bool(re.fullmatch(r"[a-záéíóúñ]{6,}[\s\d?!.,]*", value, re.IGNORECASE)
                and re.search(r"[bcdfghjklmnpqrstvwxyz]{5,}", value, re.IGNORECASE))


def _asks_again_for_supplied_measurements(message: str, reply: str,
                                           history: List[Dict[str, Any]]) -> bool:
    lead_text = " ".join([message] + [str(turn.get("text") or "") for turn in history
                                     if turn.get("role") == "lead"])
    measurements = re.search(r"\b\d+(?:[.,]\d+)?\s*(?:x|por|×)\s*\d+(?:[.,]\d+)?\b"
                             r"|\b\d+(?:[.,]\d+)?\s*(?:m|mts?|metros?)\b", lead_text, re.IGNORECASE)
    return bool(measurements and re.search(r"\bmedidas?\b|\bmetros?\s+lineales?\b", reply, re.IGNORECASE)
                and re.search(r"(?:\?|\b(?:dime|das|indica|necesito|envía|envia|comparte)\b)",
                              reply, re.IGNORECASE))


def _unverified_shipping_claim(message: str, reply: str, knowledge: str) -> bool:
    if reply == SHIPPING_COVERAGE_REPLY:
        return False
    return bool("despach" in message.casefold() and
                "despacho requieren revisión humana" in knowledge.casefold() and
                re.search(r"\b(?:hacemos|realizamos|tenemos|ofrecemos|despachamos|entregamos)\b"
                           r".{0,45}\bdespacho\b", reply, re.IGNORECASE))


def _unverified_quote_review_claim(reply: str) -> bool:
    """A generated draft cannot assert that a person reviewed a customer case."""
    return bool(re.search(
        r"\b(?:revis[eé]|revisamos|verifiqu[eé]|verificamos|confirm[eé]|confirmamos|"
        r"revisad[oa]|verificad[oa]|confirmad[oa])\b"
        r".{0,45}\b(?:consulta|cotizaci[oó]n|presupuesto)\b"
        r"|\b(?:consulta|cotizaci[oó]n|presupuesto)\b.{0,45}"
        r"\b(?:revisad[oa]|verificad[oa]|confirmad[oa])\b",
        reply or "", re.IGNORECASE))



_ASKS_RE = re.compile(
    r"\?|^\s*¿|(?:^|\b(?:a|de|en|por|con)\s+)que\b|\bqué\b|"
    r"\b(?:c[oó]mo|cu[aá]nt[oa]s?|cu[aá]l(?:es)?|aceptan?|aceptas|hacen|"
    r"tienen?|emiten|dan|reciben|se\s+puede|puedo|podr[ií]a|d[oó]nde|me\s+pasa[sn]?|"
    r"me\s+env[ií]a[sn]?|p[aá]same|p[aá]sanme|p[aá]senme|env[ií]a(?:me|nme))\b",
    re.IGNORECASE)
# A bare «que» is in every sentence («quiero que me despachen»): only «qué», or
# «que» opening the message or after a preposition («a que cuenta deposito»).
# «quiero», «necesito», «por favor» stay out: «Quiero 20 m2 gris, retiro en fábrica,
# pago con transferencia» is an order, and it must not get the bank details back.
# A message this short that names a topic is asking about it: «pago con débito»,
# «efectivo». An order statement is longer: «Retiro en fábrica, pago con transferencia».
_SHORT_QUESTION_WORDS = 4
# «ya pagué», «listo, transferí»: the customer reports, it does not ask.
_REPORTS_RE = re.compile(
    r"^\W*(?:ya|listo|hice|hicimos)\b|\b(?:transfer[ií]|deposit[eé]|pagu[eé]|abon[eé])\b",
    re.IGNORECASE)
# Real words close to a topic word that are not typos of it.
_NOT_TYPOS = frozenset({"efectiva", "efectivas", "efectivamente", "efecto", "efectos",
                        "debido", "debida", "cancelar", "cancela", "cancelo", "cancele"})
# «cuánto pago por 20 m2» asks a price; «cancelar el pedido» calls an order off.
_PRICE_OR_CALL_OFF_RE = re.compile(
    r"\bcu[aá]nt[oa]\b(?!.*\b(?:abon|transf|deposit|efectiv))|\bprecios?\b|\bvalor\b|"
    r"\bcancel\w*\s+(?:el|la|mi|los|las|este|esta|ese|esa)?\s*"
    r"(?:pedido|compra|orden|reserva|cotizaci)", re.IGNORECASE)


_TOPIC_VOCABULARY = sorted({w for words, _ in LOSETASCHILE_TEMAS_SIN_INVENTAR.values()
                            for w in words if " " not in w and len(w) >= 6})
# «cuánto es el despacho y cómo pago» asks a price and also how to pay.
_HOW_TO_PAY_RE = re.compile(r"\bc[oó]mo\b.{0,20}\b(?:pag|cancel)", re.IGNORECASE)


def _fix_topic_typos(asked: str) -> str:
    """«transferensia» → «transferencia», «efectvo» → «efectivo»: typos nobody listed."""
    out = []
    for w in asked.split():
        if len(w) >= 6 and w not in _TOPIC_VOCABULARY and w not in _NOT_TYPOS:
            # A typo keeps the first letter: «quiero» is not «crédito».
            w = next(iter(difflib.get_close_matches(
                w, [v for v in _TOPIC_VOCABULARY if v[0] == w[0]], n=1, cutoff=0.8)), w)
        out.append(w)
    return " ".join(out)


def _asked_topic(message: str):
    """El tema de política por el que pregunta el cliente, o None."""
    # Only a question: «pago el viernes con efectivo» closes an order, it asks nothing.
    words = plain(message).split()
    if not words or ("?" not in message and _REPORTS_RE.search(message)):
        return None
    if len(words) > _SHORT_QUESTION_WORDS and not _ASKS_RE.search(message):
        return None
    asked = f" {_fix_topic_typos(' '.join(words))} "
    generic_pay_only = bool(_PRICE_OR_CALL_OFF_RE.search(message)
                            and not _HOW_TO_PAY_RE.search(message))
    return next((topic for topic, (words, _) in LOSETASCHILE_TEMAS_SIN_INVENTAR.items()
                 if any(f" {w} " in asked for w in words
                        if not (generic_pay_only and w in LOSETASCHILE_PAGO_GENERICO))), None)


def _uncovered_topic(message: str, knowledge: str):
    """El tema de política que pregunta el cliente y que la ficha no respalda.

    Sin respaldo en la ficha, cualquier respuesta del modelo sobre boleta,
    garantía, pagos o plazos es inventada: mejor que la conteste una persona
    una vez y quede aprendida."""
    topic = _asked_topic(message)
    if not topic:
        return None
    ficha = f" {plain(knowledge)} "
    _, evidence = LOSETASCHILE_TEMAS_SIN_INVENTAR[topic]
    return None if any(f" {w} " in ficha for w in evidence) else topic


# The model saying it does not know is a case for a person, not a reply:
# «no tenemos información» answers nothing and leaves no trace. «no sé» only
# with its accent: «no se incluye» / «no se requiere» are ordinary answers.
_ADMITS_NOT_KNOWING_RE = re.compile(
    r"\bno\s+(?:tengo|tenemos|cuento|contamos|dispongo|disponemos|manejo|manejamos)\s+"
    r"(?:con\s+|de\s+)?(?:esa\s+|la\s+|ese\s+|el\s+)?(?:informaci[oó]n|datos?|detalle)"
    r"|\bno\s+(?:lo\s+)?sé\b|\bno\s+sabr[ií]a\b|\bno\s+estoy\s+segur[oa]\b"
    r"|\bconsult(?:o|ar[eé]?|aremos)\s+con\s+(?:el\s+|nuestro\s+)?equipo\b",
    re.IGNORECASE)
_CANNOT_CONFIRM_RE = re.compile(
    r"\bno\s+(?:puedo|podemos)\s+(?:confirmar|asegurar|indicar|decir)\w*", re.IGNORECASE)
# «Sin las medidas no puedo confirmar el precio» asks for a fact; it is not ignorance.
_MISSING_INPUT_RE = re.compile(r"\b(?:sin|hasta|mientras|antes|primero|necesito)\b",
                               re.IGNORECASE)


def _admits_not_knowing(reply: str) -> bool:
    if _ADMITS_NOT_KNOWING_RE.search(reply or ""):
        return True
    return any(_CANNOT_CONFIRM_RE.search(sentence) and not _MISSING_INPUT_RE.search(sentence)
               for sentence in re.split(r"(?<=[.!?\n])\s*", reply or ""))


# «¿Cuánto demora el despacho?» asks for a fact, not for a price: it must not
# get the product menu.
_INFO_QUESTION_RE = re.compile(
    r"\b(?:demora\w*|tarda\w*|plazos?|horarios?|garant[ií]a|boleta|factura)\b", re.IGNORECASE)


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
    """Resumen de hechos confirmados en el ICP de la empresa atendida."""
    sells = str((icp or {}).get("sells") or "").strip()
    name = (lead or {}).get("name")
    hi = f"Hola {name}" if name else "Hola"
    examples = [str(e).strip() for e in ((icp or {}).get("examples") or [])
                if str(e).strip()][:3]
    lines = [f"{hi}, aquí va la información que tengo confirmada."]
    if sells:
        lines.append(f"• Qué ofrecemos: {sells}.")
    else:
        lines.append("Todavía no tengo una descripción del servicio confirmada para enviarte.")
    if examples:
        lines.append("• Ejemplos registrados:")
        lines += [f"   {i}. {e}" for i, e in enumerate(examples, 1)]
    else:
        lines.append("No tengo ejemplos confirmados para compartir por ahora.")
    lines.append("Si me cuentas qué necesitas, puedo revisar los detalles con el equipo.")
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

    def _vendors_for_recipient(self, recipient: Optional[str]) -> List[Dict[str, Any]]:
        """Vendedores cuyo identificador Meta recibió el mensaje."""
        if not recipient:
            return []
        return [v for v in self.memory.list_vendors()
                if v.get("whatsapp_phone_id") == recipient
                and recipient not in ("000000000000001", "000000000000002")]

    def vendor_by_phone_id(self, phone_id: Optional[str]) -> Dict[str, Any]:
        """Vendedor receptor, solo cuando el identificador no es ambiguo."""
        matches = self._vendors_for_recipient(phone_id)
        return matches[0] if len(matches) == 1 else {}

    def _resolve_inbound_client(self, to_phone_id: Optional[str]) -> Optional[str]:
        """Which client's business context a first-time (unmatched) WhatsApp
        contact should be answered as — see DEFAULT_INBOUND_CLIENT_ID in
        config.py for the policy this implements and why it's needed.

        Tries the Meta phone ID first. A receiver
        assigned to exactly one client wins. If several clients share it,
        returns None: answering with a guessed business would mix brands.
        Unknown receivers use DEFAULT_INBOUND_CLIENT_ID only when there is one
        client or the receiver is the configured global number."""
        # Import local (no al tope del módulo): así una prueba que reasigna
        # config.DEFAULT_INBOUND_CLIENT_ID en caliente (ej. para probar el
        # catch-all desactivado) se refleja de inmediato — mismo motivo que
        # WhatsAppSender._template_body importa WHATSAPP_TEMPLATE adentro.

        from .config import DEFAULT_INBOUND_CLIENT_ID, DEFAULT_INBOUND_WHATSAPP_NUMBER
        if to_phone_id:
            from .client_integrations import credentials, whatsapp_provider
            recipient = str(to_phone_id)
            digits = "".join(ch for ch in recipient if ch.isdigit())
            bound = [cid for cid in self.memory.clients
                     if digits and digits == "".join(ch for ch in str(
                         self.memory.get_client_agent_profile(cid).get("whatsapp_number") or "")
                         if ch.isdigit())]
            if bound:
                return bound[0] if len(bound) == 1 else None
            integrated = [cid for cid in self.memory.clients
                          if whatsapp_provider(cid) == "meta" and
                          credentials(cid, "whatsapp").get("WHATSAPP_PHONE_ID") == recipient]
            if integrated:
                return integrated[0] if len(integrated) == 1 else None
        vendors = self._vendors_for_recipient(to_phone_id)
        vendor_ids = {v.get("id") for v in vendors}
        matches = [c for c in self.memory.clients
                   if self.memory.get_client_vendor(c) in vendor_ids]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None  # un número compartido no identifica a una empresa
        if vendors:
            return None  # número asignado, pero sin empresa asociada
        if to_phone_id and not vendors and len(self.memory.clients) > 1:
            # Con varias empresas configuradas, un receptor desconocido no
            # autoriza a presentar ZeroAI en un número quizá ajeno. Solo el
            # receptor global configurado conserva el catch-all histórico.
            global_recipient = os.environ.get("WHATSAPP_PHONE_ID") or ""
            own_number = "".join(ch for ch in str(DEFAULT_INBOUND_WHATSAPP_NUMBER) if ch.isdigit())
            if (not global_recipient or str(to_phone_id) != global_recipient) and (
                    not own_number or "".join(ch for ch in str(to_phone_id) if ch.isdigit()) != own_number):
                return None
        return DEFAULT_INBOUND_CLIENT_ID or None


    def _last_agent_text(self, client_id: str, lead_key: str) -> str:
        for turn in reversed(self.memory.get_conversation(client_id, lead_key)):
            if turn.get("role") == "agent":
                return turn.get("text") or ""
        return ""

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
        payload = {**msg, "to": to, "client_id": client_id}
        if (msg.get("channel") or "") == "whatsapp" and client_id:
            from .config import DEFAULT_INBOUND_CLIENT_ID, DEFAULT_INBOUND_WHATSAPP_NUMBER
            profile_number = self.memory.get_client_agent_profile(client_id).get("whatsapp_number")
            payload["client_id"] = client_id
            payload["whatsapp_from"] = (msg.get("whatsapp_from") or profile_number or
                                        (DEFAULT_INBOUND_WHATSAPP_NUMBER
                                         if client_id == DEFAULT_INBOUND_CLIENT_ID else ""))
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

        last = self.memory.last_contacted(client_id, lead.key())
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
    @staticmethod
    def _avisar(on_progress, **datos) -> None:
        """Reporta avance a quien esté mirando, sin poder romper la corrida.

        Avisar es secundario frente a entregar leads: si el observador falla —o es
        una función mal escrita del lado del dashboard— se pierde una animación, no
        el trabajo. Mismo criterio que zero/telemetry.py.
        """
        if on_progress is None:
            return
        try:
            on_progress(**datos)
        except Exception:   # noqa: BLE001 — nunca rompe lo que mide
            pass

    def _validate_and_record(
        self, client_id: str, scored: List[Lead], exclusions: List[str], tier: Optional[str] = None,
        on_progress=None,
    ) -> Tuple[List[Lead], List[Dict[str, Any]]]:
        """Run the qualified-lead gate over scored leads, updating CRM + memory log."""
        self.memory.set_stage(client_id, "validate")
        self._avisar(on_progress, fase="validando")
        qualified: List[Lead] = []
        rejected: List[Dict[str, Any]] = []
        for lead in scored:
            ok, fails = self.validate_lead(lead, exclusions, tier=tier, client_id=client_id)
            if ok:
                qualified.append(lead)
            else:
                rejected.append({"company": lead.company, "score": lead.score, "reasons": fails})
            # Acá el avance es real lead por lead (el gate itera), no por lote.
            self._avisar(on_progress, empresa=lead.company,
                         etapa="aprobada" if ok else "descartada",
                         motivo=None if ok else ", ".join(fails))
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
            self.memory.mark_contacted(client_id, lead.key())
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
            self.memory.mark_contacted(client_id, lead_key)
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
        on_progress=None,
    ) -> Dict[str, Any]:
        """discover → enrich → qualify → (validate) → outreach → report.

        `on_progress(**datos)` recibe el avance mientras corre: `fase=` para la
        corrida entera y `empresa=`/`etapa=` para cada empresa. Es opcional y nadie
        que no lo pase nota diferencia; lo usa la API para que el dashboard pueda
        mostrar qué está pasando en vez de una pantalla quieta durante minutos.
        Ojo con la granularidad real: discover y qualify son UNA llamada al modelo
        cada una, así que sus empresas aparecen en tanda; validate y outreach sí
        avanzan de a una.
        """
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
        self._avisar(on_progress, fase="descubriendo")
        disc = self.dispatch("PROSPECTOR", TaskPayload(
            agent="PROSPECTOR", client_id=client_id, client_tier=tier,
            instructions=f"Descubre y enriquece leads B2B para: {query}",
            data={"query": query, "icp": icp},
            constraints=Constraints(max_items=max_items, channels=channels),
        ))
        if disc.status == "error":
            return self._fail(client_id, "discover", disc)
        raw_leads = [Lead.from_dict(d) for d in disc.result.get("leads", [])]
        for lead in raw_leads:
            self._avisar(on_progress, empresa=lead.company, etapa="descubierta")

        # 2) QUALIFY ----------------------------------------------------------
        self.memory.set_stage(client_id, "qualify")
        self._avisar(on_progress, fase="calificando")
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
        for lead in scored:
            self._avisar(on_progress, empresa=lead.company, etapa="calificada",
                         score=lead.score)

        # 3) VALIDATE against the qualified-lead definition -------------------
        qualified, rejected = self._validate_and_record(client_id, scored, exclusions, tier=tier,
                                                        on_progress=on_progress)

        # 4) OUTREACH (first touch) ------------------------------------------
        messages: List[Dict[str, Any]] = []
        if write_outreach and qualified:
            self.memory.set_stage(client_id, "outreach")
            self._avisar(on_progress, fase="escribiendo")
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
                for m in messages:
                    self._avisar(on_progress, empresa=m.get("company"), etapa="lista",
                                 canal=m.get("channel"))

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
        self._avisar(on_progress, fase="listo")
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
            self.memory.mark_contacted(client_id, s["lead_key"])
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
                        vendor: Optional[Dict[str, Any]] = None,
                        feedback: str = "") -> Dict[str, Any]:
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
        knowledge = self.memory.get_client_knowledge(client_id) if client_id else ""
        local_whatsapp = (getattr(getattr(self, "agents", {}).get("CONCIERGE"), "prompt_file", "") ==
                          "concierge-whatsapp-local.md")
        # Historial del diálogo (turnos previos, NO incluye `message`): pasado
        # explícito (p.ej. el simulador) o recuperado de memoria por lead.
        if history is None and lead and lead.get("key") and client_id:
            history = self.memory.get_conversation(
                client_id, lead["key"], limit=None if local_whatsapp else 12)
        order_history = history or []
        if client_id == "losetaschile" and channel == "whatsapp":
            # Typos fixed and loose sizes rewritten before any step reads it.
            message = normalize_customer_text(message)
            # A phrase the team taught as a synonym becomes that option.
            message = learned_alias(self.memory, client_id, message) or message
            chosen = canonical_choice(message, order_history)
            if chosen:
                message = chosen
            else:
                learned = learned_answer(self.memory, client_id, message)
                if learned:
                    # The team answered this question once from the dashboard.
                    return {"reply": learned, "intent": "info", "flow_step": True}
                # Bank details and the like go out exactly as the team wrote them
                # in the sheet: the model must never retype an account number.
                fixed = fixed_answer(knowledge, _asked_topic(message) or "")
                if fixed:
                    return {"reply": fixed, "intent": "info", "flow_step": True}
                topic = _uncovered_topic(message, knowledge)
                if topic:
                    return {"reply": "", "intent": "handoff",
                            "gap_reason": f"Pregunta sobre {topic}: no está en la ficha"}
        greeting = whatsapp_greeting() if channel == "whatsapp" else ""
        if client_id == "losetaschile" and channel == "whatsapp" and _simple_greeting(message):
            introduced = _introduced_name(message)
            salutation = f"¡{greeting}, {introduced}!" if introduced else f"¡{greeting}!"
            return {"reply": f"{salutation} ¿En qué puedo ayudarte?", "intent": "general",
                    "customer_poll": "product"}
        if client_id == "losetaschile" and channel == "whatsapp":
            visual_category = visual_catalog_category(message)
            if visual_category:
                title = ("Catálogo Bordes de Piscina" if visual_category == "bordes"
                         else "Catálogo Pastelones")
                pricing = normalize_pricing(self.memory.get_client_pricing(client_id))
                return {"reply": title, "intent": "catalog",
                        "catalog_document": {"category": visual_category, "pricing": pricing}}
            if catalog_requested(message):
                return {"reply": LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE, "intent": "catalog"}
            selected_category = category_for_poll_choice(message, order_history)
            typed_category = direct_product_category(message)
            # A typed product name restarts the step only when it is a new choice:
            # repeating the category just chosen must not resend PDF and color poll.
            if (not selected_category and typed_category and
                    selected_category_from_history(order_history[-6:]) != typed_category):
                selected_category = typed_category
            if selected_category:
                # Size first; the catalog follows with «which model did you like?».
                return {"reply": (POOL_MEASUREMENT_QUESTION if selected_category == "bordes"
                                  else PAVER_AREA_QUESTION),
                        "intent": "qualification", "flow_step": True}
            if (_QUOTE_REQUEST_RE.search(message) and not _INFO_QUESTION_RE.search(message) and
                    not re.search(r"\b(?:bordes?\s+(?:de|para)\s+(?:la\s+)?piscina|pastelones?)\b",
                                  message, re.IGNORECASE) and not order_history):
                return {"reply": PRODUCT_POLL_QUESTION, "intent": "qualification",
                        "customer_poll": "product"}
            choice_reply = delivery_poll_choice_response(message)
            category_in_history = selected_category_from_history(order_history)
            paver_details = paver_order_details(message, order_history) \
                if category_in_history == "pastelones" else {}
            factory_order_ready = (
                is_factory_pickup(message) and latest_color_preference(order_history) and
                (category_in_history == "bordes" or
                 (category_in_history == "pastelones" and paver_details.get("model") and
                  paver_details.get("area_m2")))
            )
            if choice_reply and not factory_order_ready:
                return {"reply": choice_reply, "intent": "info"}
        if (client_id == "losetaschile" and channel == "whatsapp" and
                shipping_price_request(message)):
            return {"reply": SHIPPING_PRICE_REPLY, "intent": "pricing",
                    "delivery_poll": True}
        if (client_id == "losetaschile" and channel == "whatsapp" and
                shipping_coverage_request(message) and
                not wants_product_quote(message) and
                not wants_border_budget(message)):
            return {"reply": SHIPPING_COVERAGE_REPLY, "intent": "info",
                    "delivery_poll": True}
        # El contexto de Ollama en WhatsApp es pequeño. Un prompt de 11 KB más
        # toda la ficha del CRM hacía que Ollama recortara el mensaje entrante.
        lead_context = lead or {}
        if local_whatsapp:
            lead_context = {key: lead_context[key] for key in ("name", "role", "company")
                            if lead_context.get(key)}
            # Short follow-ups often name no product or policy. Use the latest
            # exchange only to find matching sections of the same knowledge sheet.
            followup = (bool(re.search(r"\b(?:eso|esto|ese|esa|aquello)\b", message, re.I)) or
                        bool(re.match(r"^\s*[¿¡]?\s*y\b", message, re.I)) or
                        bool(re.fullmatch(r"\s*[¿]?\s*cu[aá]nto\s+(?:sale|cuesta)\s*[?]?\s*",
                                          message, re.I)))
            retrieval_query = message
            if followup:
                retrieval_query += " " + " ".join(
                    str(turn.get("text") or "")[:180] for turn in (history or [])[-2:])
            knowledge = select_knowledge(knowledge, retrieval_query, max_chars=1600)
            history = select_history(history or [], message, max_turns=6)
        else:
            knowledge = knowledge[:4000]
        # Persona del vendedor asignado (Fernanda/Stéfano/...): solo name/tone, para
        # que CONCIERGE suene como esa persona. Nunca el token/phone_id (secretos).
        if vendor is None:
            vendor = self.vendor_for(client_id) if client_id else {}
        profile = self.memory.get_client_agent_profile(client_id) if client_id else {}
        persona = {"name": vendor.get("name"),
                   "tone": profile.get("tone") or vendor.get("tone")}
        # Presupuesto: si el mensaje pide precios de ítems del catálogo del cliente,
        # se calcula ACÁ (quotes.py, determinista) y se adjunta tras la respuesta del
        # agente — mismo patrón que project_funnel: el LLM redacta, nunca calcula.
        pricing = normalize_pricing(self.memory.get_client_pricing(client_id)) \
            if client_id else {"items": []}

        if client_id == "losetaschile" and channel == "whatsapp":
            models_reply = pool_border_models_reply(message, order_history, pricing)
            if models_reply:
                return {"reply": models_reply, "intent": "catalog"}

        if client_id == "losetaschile" and channel == "whatsapp":
            # Payment methods are a «tema sin inventar» (config): a case, not a non-answer.
            if re.search(r"\bdescuentos?\b", message, re.IGNORECASE):
                return {"reply": ("No tengo un descuento confirmado para este pedido. "
                                  "Debe confirmarse antes de incluirlo en el presupuesto."),
                        "intent": "info"}

        selected_tone = (color_preference(message, order_history) or
                         latest_color_preference(order_history)) \
            if client_id == "losetaschile" and channel == "whatsapp" else None
        if (client_id == "losetaschile" and channel == "whatsapp" and selected_tone and
                poll_answer_for_history(message, order_history) == "color" and
                selected_category_from_history(order_history) == "pastelones"):
            paver_details = paver_order_details(message, order_history)
            if paver_details["model"] and paver_details["area_m2"]:
                return {"reply": f"Anoté el color {selected_tone}. {LOSETAS_DELIVERY_POLL_QUESTION}",
                        "intent": "qualification", "delivery_poll": True}
            return {"reply": (f"Anoté el color {selected_tone}. " +
                              (PAVER_AREA_QUESTION if paver_details["model"] else
                               PAVER_MODEL_QUESTION)),
                    "intent": "qualification", "flow_step": True,
                    **({} if paver_details["model"] else {"customer_poll": "paver_model"})}
        if (client_id == "losetaschile" and channel == "whatsapp" and
                selected_category_from_history(order_history) == "pastelones" and
                not shipping_delivery_followup(message, order_history) and
                any(turn.get("role") == "agent" and "cuántos m²" in
                    str(turn.get("text") or "").casefold() for turn in order_history[-6:])):
            paver_details = paver_order_details(message, order_history)
            if paver_details["model"] and paver_details["area_m2"]:
                if not latest_color_preference(order_history):
                    return {"reply": color_question(), "intent": "qualification",
                            "media_asset": COLOR_CATALOG_IMAGE_PATH, "customer_poll": "color"}
                return {"reply": LOSETAS_DELIVERY_POLL_QUESTION, "intent": "qualification",
                        "delivery_poll": True}
            if paver_details["model"]:
                return {"reply": f"Anoté el modelo {paver_details['model']}. {PAVER_AREA_QUESTION}",
                        "intent": "qualification", "flow_step": True}
            if paver_details["area_m2"]:
                ask = {"reply": f"Anoté {paver_details['area_m2']} m². {PAVER_MODEL_QUESTION}",
                       "intent": "qualification", "customer_poll": "paver_model"}
                if any(turn.get("role") == "agent" and turn.get("text") == "Catálogo Pastelones"
                       for turn in order_history[-8:]):
                    return ask  # catalog already sent: ask again, never resend the PDF
                pricing = normalize_pricing(self.memory.get_client_pricing(client_id))
                return {**ask, "reply_after_document": True,
                        "catalog_document": {"category": "pastelones", "pricing": pricing}}
        if (client_id == "losetaschile" and channel == "whatsapp" and
                selected_category_from_history(order_history) == "pastelones" and
                shipping_delivery_followup(message, order_history)):
            return {"reply": ("Gracias, recibí el modelo, los m² y la ubicación. "
                              "Debo confirmar el tamaño del modelo antes de calcular las cantidades."),
                    "intent": "info",
                    "attention": "Pastelones: confirmar el tamaño del modelo y cotizar"}
        if (client_id == "losetaschile" and channel == "whatsapp" and
                (wants_border_budget(message) or pool_measurement_message(message) or measurement_followup(
                    message, order_history) or border_model_followup(message, order_history) or
                 pool_shape_followup(message, order_history) or
                 roman_pool(message, order_history) or
                 color_preference(message, order_history) or
                 shipping_delivery_followup(message, order_history))):
            plan, clarification = border_plan(message, order_history)
            if plan is None:
                if shipping_delivery_followup(message, order_history):
                    return {"reply": "Gracias, recibí los datos de entrega. El equipo revisará cobertura y flete.",
                            "intent": "info"}
                if clarification == POOL_PHOTO_REQUEST:
                    last_agent = next((str(t.get("text") or "") for t in reversed(order_history)
                                       if t.get("role") == "agent"), "")
                    if POOL_PHOTO_MARKER in last_agent:
                        # Already asked and alerted: no second case, no second alert.
                        return {"reply": ("Quedo atento a la foto de la piscina; con ella "
                                          "calculamos los bordes."),
                                "intent": "pricing", "flow_step": True}
                    # The piece rule assumes a rectangle: the owner reviews the photo.
                    return {"reply": clarification, "intent": "pricing", "flow_step": True,
                            "attention": "Piscina no rectangular: revisar la foto y cotizar",
                            "owner_alert": "pool_photo"}
                if clarification == BORDER_MODEL_QUESTION and not any(
                        turn.get("role") == "agent" and
                        turn.get("text") == "Catálogo Bordes de Piscina"
                        for turn in order_history[-8:]):
                    # Measurements are in: now the catalog, asking which model.
                    pricing = normalize_pricing(self.memory.get_client_pricing(client_id))
                    return {"reply": clarification, "intent": "qualification",
                            "customer_poll": "border_model",
                            "catalog_document": {"category": "bordes", "pricing": pricing},
                            "reply_after_document": True}
                if clarification in (BORDER_MODEL_QUESTION, POOL_SHAPE_QUESTION):
                    return {"reply": clarification, "intent": "qualification",
                            "customer_poll": ("border_model" if clarification ==
                                              BORDER_MODEL_QUESTION else "shape")}
                return {"reply": clarification, "intent": "pricing"}
            if not selected_tone:
                return {"reply": color_question(), "intent": "qualification",
                        "media_asset": COLOR_CATALOG_IMAGE_PATH,
                        "customer_poll": "color"}
            if not delivery_detail(message, order_history):
                return {"reply": LOSETAS_DELIVERY_POLL_QUESTION, "intent": "qualification",
                        "delivery_poll": True}
            order = [{"id": plan["border_id"], "qty": plan["straight"]},
                     {"id": "esquina-piscina-50x50", "qty": plan["corners"]}]
            product_quote = compute_quote(pricing, order)
            product_reply = format_product_quote(plan, product_quote or {})
            if product_reply:
                product_quote["shipping_pending"] = True
                product_quote["delivery_detail"] = delivery_detail(message, order_history)
                return {"reply": product_reply, "intent": "pricing", "quote": product_quote,
                        "selected_tone": selected_tone}
            return {"reply": "Necesito confirmar el precio de ambos productos antes de darte el subtotal.",
                    "intent": "pricing"}

        if client_id in QUOTE_REVIEW_REQUIRED_CLIENT_IDS and (
                _QUOTE_REQUEST_RE.search(message) or extract_request(message, pricing)):
            # El modelo no debe improvisar un total cuando todavía falta revisar
            # el despacho. Respuesta determinista hasta conectar el cotizador de
            # PoolEdge con la aprobación humana del envío.
            return {"reply": ("Para preparar tu presupuesto necesito confirmar "
                              "productos, cantidades y la dirección completa de entrega. "
                              "¿Me compartes esos datos?"), "intent": "pricing"}
        quote_mode = profile.get("quote_mode") or "automatic"
        quote = (compute_quote(pricing, extract_request(message, pricing))
                 if pricing["items"] and quote_mode == "automatic"
                 and client_id not in QUOTE_REVIEW_REQUIRED_CLIENT_IDS else None)
        instructions = "Responde el mensaje entrante del lead, en su idioma, breve y útil."
        if profile.get("instructions"):
            instructions += (" Instrucciones de atención para este negocio: " +
                             profile["instructions"][:1200])
        if client_id in QUOTE_REVIEW_REQUIRED_CLIENT_IDS:
            instructions += (" Esta empresa requiere revisión humana del despacho antes de "
                             "emitir un presupuesto final. No calcules ni prometas un total; "
                             "pide los detalles del pedido y la dirección completa si faltan.")
        if client_id == "losetaschile" and channel == "whatsapp":
            instructions += (" Para LosetasChile, primero interpreta la consulta concreta y "
                             "responde a esa duda antes de pedir datos. Usa el historial para "
                             "no repetir saludos, explicaciones, preguntas ni listas de medidas "
                             "ya solicitadas. Pide solo el dato que falta. Si no logras entender "
                             "la consulta, usa intent handoff.")
        if feedback:
            instructions += " Corrección obligatoria de la respuesta anterior: " + feedback[:450]
        if greeting:
            instructions += (" Si saludas, usa exactamente '" + greeting +
                             "' según la hora de Chile, aunque el contacto use otro saludo. "
                             "No afirmes por eso que el negocio esté abierto.")

        if quote:
            instructions += (" Debajo de tu respuesta se adjuntará un presupuesto ya "
                             "calculado con los ítems que pidió: preséntalo en una frase "
                             "y NO repitas ni inventes montos.")
        elif quote_mode == "manual":
            instructions += (" Los presupuestos de este negocio requieren revisión humana. "
                             "No entregues montos ni totales. Solo si el contacto pregunta por "
                             "precio o presupuesto, pide los datos imprescindibles y ofrece "
                             "cotizar con una persona.")
        instructions += (" Si el mensaje es solo un saludo, saluda y pregunta en qué puedes "
                         "ayudar; no presupongas que quiere cotizar ni pidas medidas.")
        task = TaskPayload(
            agent="CONCIERGE", client_id=client_id or "", client_tier="",
            instructions=instructions,
            data={"message": message, "lead": lead_context, "icp": _icp_para_outreach(icp), "vendor": persona,
                  "knowledge": knowledge, "history": history or [],
                  "quote": quote or {}, "greeting": greeting},
            constraints=Constraints(channels=[channel]),
        )
        resp = self.dispatch("CONCIERGE", task)
        result = dict(resp.result or {})
        failures = (check_reply(result) if local_whatsapp and channel == "whatsapp" else
                    ["respuesta vacía"] if not isinstance(result.get("reply"), str) or
                    not result["reply"].strip() else [])
        if failures:
            retry = TaskPayload(
                agent="CONCIERGE", client_id=client_id or "", client_tier="",
                instructions=instructions +
                " Corrige la respuesta anterior: " + "; ".join(failures)[:350] +
                ". Devuelve JSON con reply no vacío e intent válido, sin cifras inventadas.",
                data=task.data, constraints=task.constraints,
            )
            resp = self.dispatch("CONCIERGE", retry)
            result = dict(resp.result or {})
            failures = (check_reply(result) if local_whatsapp and channel == "whatsapp" else
                        ["respuesta vacía"] if not isinstance(result.get("reply"), str) or
                        not result["reply"].strip() else [])
            if failures:
                logging.error("CONCIERGE no produjo respuesta válida tras dos intentos "
                              "(status=%s, keys=%s, fallas=%s)",
                              resp.status, sorted(result), len(failures))
                return {"reply": "", "intent": "handoff"}
        if (client_id == "losetaschile" and channel == "whatsapp" and
                delegates_piece_calculation(message, result.get("reply") or "")):
            result["reply"] = ("¿Me confirmas el modelo de borde y las medidas "
                               "de la piscina para darte la cantidad exacta?")
        if greeting and isinstance(result.get("reply"), str):
            result["reply"] = align_opening_greeting(result["reply"], greeting)
            if _simple_greeting(message) and not result["reply"].lstrip(" ¡!").casefold().startswith(
                    greeting.casefold()):
                result["reply"] = f"¡{greeting}! " + result["reply"].lstrip()
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
        """Mete formularios de Meta al CRM como nuevos, pendientes de calificación.

        Nunca a
        prueba de opt-out por defecto: alguien que ya dijo 'no me interesa' por
        WhatsApp puede volver a aparecer acá con el mismo email/teléfono (mismo
        lead_key) — se salta por completo, ni se registra ni se cuenta como
        importado, para que quede a la vista que hay algo que Meta le sigue
        mandando pero ZeroAI ya no le va a escribir."""
        if not self.crm:
            return {"imported": 0, "blocked": 0, "skipped": 0, "client_id": client_id}
        imported = 0
        blocked = 0
        skipped = 0
        seen_meta_ids = {
            h.get("detail")
            for rec in self.crm.list(client_id)
            for h in rec.get("history") or []
            if h.get("event") == "ad_lead" and
            str(h.get("detail") or "").startswith("Meta Ads · lead ")
        }
        for ld in leads:
            if not (ld.get("email") or ld.get("phone")):
                skipped += 1
                continue
            if self.crm.is_blocked_lead(client_id, ld):
                blocked += 1
                continue
            marker = f"Meta Ads · lead {ld['meta_lead_id']}" if ld.get("meta_lead_id") else ""
            if marker and marker in seen_meta_ids:
                skipped += 1
                continue
            rec = self.crm.upsert(client_id, ld)
            tags = rec.setdefault("tags", [])
            if "Meta Ads" not in tags:
                tags.append("Meta Ads")
            self.crm.log(client_id, rec["key"], "ad_lead",
                         marker or f"Meta Ads · {ld.get('campaign', '')}")
            if marker:
                seen_meta_ids.add(marker)
            imported += 1
        self.crm.save()
        self.memory.log("ad_leads_import", client=client_id, count=imported,
                        blocked=blocked, skipped=skipped)
        self.memory.save()
        return {"imported": imported, "blocked": blocked, "skipped": skipped,
                "client_id": client_id}

    def handle_inbound(self, from_contact: str, text: str,
                       channel: str = "whatsapp",
                       to_phone_id: Optional[str] = None,

                       profile_name: Optional[str] = None,
                       whatsapp_chat_id: Optional[str] = None) -> Dict[str, Any]:

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

        # El número receptor define el negocio antes de buscar al contacto. Una
        # misma persona puede ser lead de varias empresas: un lookup global
        # respondería con la primera ficha encontrada, aunque haya escrito a otra.
        inbound_client = self._resolve_inbound_client(to_phone_id) if to_phone_id and self.crm else None
        rec = None
        global_recipient = os.environ.get("WHATSAPP_PHONE_ID") or ""
        if (self.crm and to_phone_id and global_recipient == str(to_phone_id)
                and not self._vendors_for_recipient(to_phone_id)):
            # El número Meta global puede atender más de una empresa. Un lead
            # ya registrado identifica su ficha si hay una única coincidencia;
            # dos coincidencias no autorizan a usar el catch-all de ZeroAI.
            matches = [match for cid in self.memory.clients
                       if credentials_for(self.vendor_for(cid))[0] == str(to_phone_id)
                       if (match := self.crm.find_by_contact(
                           phone=from_contact, email=from_contact, client_id=cid))]
            if len(matches) > 1:
                self.memory.log("inbound_unmatched", channel=channel,
                                sender=from_contact, text=(text or "")[:200])
                self.memory.save()
                return {"matched": False, "sender": from_contact}
            if matches:
                rec = matches[0]
                inbound_client = rec["client_id"]

        if to_phone_id and not inbound_client and not rec and not self._vendors_for_recipient(to_phone_id):
            self.memory.log("inbound_unmatched", channel=channel, sender=from_contact,
                            destination=to_phone_id, text=(text or "")[:200])
            self.memory.save()
            return {"matched": False, "sender": from_contact, "reason": "unknown_destination"}
        if not rec:
            rec = (self.crm.find_by_contact(phone=from_contact, email=from_contact,
                                            client_id=inbound_client) if inbound_client else
                   self.crm.find_by_contact(phone=from_contact, email=from_contact)
                   if self.crm and not to_phone_id else None)
        if not rec and to_phone_id and not inbound_client and self.crm:
            # Un número compartido no identifica a un remitente nuevo. Para un
            # contacto ya registrado, solo se puede responder si aparece en una
            # única empresa asociada a ese receptor.
            recipient_vendor_ids = {v.get("id") for v in
                                    self._vendors_for_recipient(to_phone_id)}
            candidates = [self.crm.find_by_contact(phone=from_contact,
                                                     email=from_contact, client_id=cid)
                          for cid in self.memory.clients
                          if self.memory.get_client_vendor(cid) in recipient_vendor_ids]
            matches = [candidate for candidate in candidates if candidate]
            if len(matches) == 1:
                rec = matches[0]
        name_from_profile = " ".join(str(profile_name or "").split())[:80]
        if not any(ch.isalpha() for ch in name_from_profile):
            name_from_profile = ""
        if not rec:
            client_id = inbound_client or (self._resolve_inbound_client(None) if self.crm and not to_phone_id else None)
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
                "name": name_from_profile or None,
                "source": "whatsapp_inbound",
            })
            self.crm.save()
            self.memory.log("inbound_auto_registered", client=client_id,
                            lead=rec["key"], channel=channel, sender=from_contact)
            self.memory.save()
        elif name_from_profile and not (rec.get("name") or "").strip():
            # El perfil de WhatsApp completa un nombre ausente; no pisa un nombre
            # confirmado antes por el cliente o en el CRM.
            rec = self.crm.upsert(rec["client_id"], {"key": rec["key"], "name": name_from_profile})
            self.crm.save()

        client_id, key = rec["client_id"], rec["key"]
        if client_id == "losetaschile" and channel == "whatsapp":
            # «2» answers the numbered options; store the option itself, because
            # later steps read the order back from the conversation.
            text = normalize_customer_text(text)
            text = learned_alias(self.memory, client_id, text) or text
            text = canonical_choice(text, self.memory.get_conversation(client_id, key)) or text
        if name_from_profile and channel == "whatsapp":
            display_names = self.memory.clients.setdefault(client_id, {}).setdefault(
                "whatsapp_display_names", {})
            display_names[key] = name_from_profile
            # Drafting may reload the store before sending; retain provenance.
            self.memory.save()
        introduced_name = _introduced_name(text)
        if introduced_name and not rec.get("name") and self.crm:
            # Supabase find_by_contact devuelve una copia; modificarla no persiste.
            rec = self.crm.upsert(client_id, {"key": key, "name": introduced_name})
            self.crm.save()
        handoff_key = whatsapp_chat_id or key
        # Reply from the number the lead wrote to (its vendor), else the client's vendor.
        inbound_vendor = self.vendor_by_phone_id(to_phone_id)
        wa_creds = credentials_for(inbound_vendor) if inbound_vendor else None
        out = self.register_reply(client_id, key, text=text, channel=channel)
        profile = self.memory.get_client_agent_profile(client_id)
        response_mode = profile.get("response_mode") or "automatic"
        handoff = self.memory.get_whatsapp_handoff(client_id, handoff_key) if channel == "whatsapp" else None
        if response_mode == "manual" or handoff:
            self.memory.add_turn(client_id, key, "lead", text)
            self.memory.log("inbound_manual_review", client=client_id, lead=key,
                            channel=channel, reason="business_manual" if response_mode == "manual" else "chat_handoff")
            self.memory.save()
            if self.crm:
                self.crm.log(client_id, key, "awaiting_human", "Mensaje en bandeja de WhatsApp")
                self.crm.save()
            return {"matched": True, "manual_review": True,
                    "company": rec.get("company"), **out}

        if channel == "whatsapp" and (_HUMAN_REQUEST_RE.search(text or "") or
                                       _unreadable_whatsapp_message(text, client_id)):
            self.memory.add_turn(client_id, key, "lead", text)
            photo = (client_id == "losetaschile" and
                     pool_photo_followup(text, self.memory.get_conversation(client_id, key)[:-1]))
            reason = ("El contacto pidió atención humana" if _HUMAN_REQUEST_RE.search(text or "") else
                      "Foto de la piscina recibida: revisar y cotizar" if photo else
                      "Mensaje no interpretable por el agente")
            if photo:
                # The owner reviews the photo; the customer knows it arrived.
                ack = "Gracias, recibí la foto. La revisamos y te respondemos por este chat."
                ack_delivery = self._deliver(
                    client_id, key, rec.get("phone") or rec.get("email"),
                    {"channel": channel, "subject": None, "body": ack,
                     "whatsapp_from": to_phone_id, "whatsapp_chat_id": whatsapp_chat_id},
                    wa_creds=wa_creds)
                if ack_delivery.get("status") == "sent":
                    self.memory.add_turn(client_id, key, "agent", ack)
                else:
                    self.memory.log("pool_photo_ack_failed", client=client_id, lead=key,
                                    error=ack_delivery.get("error"))
            self.memory.set_whatsapp_handoff(client_id, handoff_key, reason)
            self.memory.log("whatsapp_handoff", client=client_id, lead=key, reason=reason)
            self.memory.save()
            if self.crm:
                self.crm.log(client_id, key, "awaiting_human", reason)
                self.crm.save()
            return {"matched": True, "manual_review": True, "intent": "handoff",
                    "company": rec.get("company"), **out}

        # An offer was pending (summary / 3 examples) and the lead accepted:
        # fulfill it instead of drafting — a promise kept beats a fresh pitch.
        pending = self.memory.get_pending_offer(client_id, key)
        # Perfiles nuevos desactivan este flujo heredado de ventas de ZeroAI.
        # Los clientes antiguos sin perfil conservan su comportamiento.
        offer_flow = self.memory.get_client_agent_profile(client_id).get("offer_flow", True)
        if (offer_flow and pending and accepts_offer(text) and not
                (client_id == "losetaschile" and channel == "whatsapp" and
                 catalog_requested(text))):
            body = build_info_summary(self.memory.get_client_icp(client_id), rec)
            out_channel, to = pick_channel(text, rec, default_channel=channel)
            delivery = self._deliver(client_id, key, to, {
                "channel": out_channel,
                "subject": "Información solicitada" if out_channel == "email" else None,
                "body": body,
                "whatsapp_from": to_phone_id,
                "whatsapp_chat_id": whatsapp_chat_id,
            }, wa_creds=wa_creds)
            self.memory.add_turn(client_id, key, "lead", text)
            sent = delivery.get("status") == "sent"
            if sent:

                self.memory.clear_pending_offer(client_id, key)
                self.memory.add_turn(client_id, key, "agent", body)
                self.memory.log("offer_fulfilled", client=client_id, lead=key,
                                kind=pending.get("kind"), channel=out_channel)

            else:
                self.memory.log("offer_delivery_failed", client=client_id, lead=key,
                                kind=pending.get("kind"), channel=out_channel,
                                error=delivery.get("error"))
            self.memory.save()
            if self.crm:
                if sent:
                    self.crm.log(client_id, key, "info_sent",
                                 f"información confirmada ({pending.get('kind')}, {out_channel})")
                self.crm.save()
            return {"matched": True, "company": rec.get("company"),
                    "reply": body if sent else "",
                    "intent": "fulfill" if sent else "fulfill_failed",
                    "delivery": delivery, **out}


        # Redactar ANTES de registrar los turnos: así el historial que ve CONCIERGE
        # son solo los turnos previos (el mensaje actual viaja aparte en `message`).
        prior_turns = self.memory.get_conversation(client_id, key)
        res = self.converse_result(client_id, text, lead=rec, channel=channel)
        # A teammate may take the chat while the local model is drafting. Reload
        # persisted state before sending, so that takeover wins over the draft.
        if channel == "whatsapp" and whatsapp_chat_id and (
                self.memory.path is not None or type(self.memory) is not SessionMemory):
            fresh_memory = (type(self.memory)(str(self.memory.path)) if self.memory.path is not None
                            else type(self.memory)())
            self.memory = fresh_memory
            if fresh_memory.get_whatsapp_handoff(client_id, handoff_key):
                self.memory.add_turn(client_id, key, "lead", text)
                self.memory.log("inbound_manual_review", client=client_id, lead=key,
                                channel=channel, reason="chat_taken_during_draft")
                self.memory.save()
                if self.crm:
                    self.crm.log(client_id, key, "awaiting_human", "El equipo tomó el chat")
                    self.crm.save()
                return {"matched": True, "manual_review": True,
                        "company": rec.get("company"), **out}
        reply, intent = res.get("reply") or "", res.get("intent") or "general"
        quote = res.get("quote")
        if client_id == "losetaschile" and channel == "whatsapp" and quote:
            # The customer never receives an automatic budget. The structured
            # calculation goes to a separate review group for a person to check.
            internal_budget = format_internal_budget(
                quote, profile_name=(name_from_profile or self.memory.clients.get(
                    client_id, {}).get("whatsapp_display_names", {}).get(key)),
                phone=from_contact,
                tone=res.get("selected_tone"))
            self.memory.add_turn(client_id, key, "lead", text)
            group_id = (os.environ.get("LOSETASCHILE_REVIEW_GROUP_ID") or "").strip()
            if not internal_budget or not group_id or not to_phone_id or not whatsapp_chat_id:
                reason = "Falta número, presupuesto o grupo interno verificado"
                delivery = {"status": "error", "error": reason}
            else:
                signature = hashlib.sha256(internal_budget.encode("utf-8")).hexdigest()
                signatures = self.memory.clients.setdefault(client_id, {}).setdefault(
                    "internal_budget_signatures", {})
                if signatures.get(key) == signature:
                    self.memory.log("internal_budget_already_sent", client=client_id, lead=key)
                    self.memory.save()
                    return {"matched": True, "manual_review": True,
                            "intent": "pricing", "company": rec.get("company"), **out}
                try:
                    from .whatsapp_web import send_group_text
                    group_result = send_group_text(client_id, to_phone_id, group_id,
                                                   internal_budget)
                    signatures[key] = signature
                    # Keep the group-send dedupe durable before sending the
                    # separate customer acknowledgment.
                    self.memory.save()
                    delivery = {"status": "accepted", "via": "whatsapp_web_group",
                                "id": group_result["id"], "ack": group_result.get("ack")}
                except (RuntimeError, ValueError) as exc:
                    # A send with an uncertain outcome must be reviewed in the
                    # group before any manual retry. Never send the budget to the lead.
                    delivery = {"status": "error", "error": str(exc)}
            customer_ack = None
            if delivery["status"] == "accepted":
                tone = res.get("selected_tone")
                if color_preference(text, prior_turns):
                    thanks = f"Gracias, anoté el color {tone}. "
                elif shipping_delivery_followup(text, prior_turns):
                    thanks = "Gracias, recibí los datos de entrega. "
                else:
                    thanks = "Gracias, recibí los datos de tu pedido. "
                acknowledgment = thanks + (
                    (f"El retiro es en {FACTORY_ADDRESS}" +
                     (f" ({FACTORY_MAP_URL}). " if FACTORY_MAP_URL else ". ")
                     if delivery_detail(text, prior_turns) and
                     str(delivery_detail(text, prior_turns)).startswith("Retiro en fábrica:")
                     else "") +
                    "Tu presupuesto está pendiente de revisión por nuestro equipo; "
                    "te responderemos por este chat.")
                try:
                    customer_ack = self._deliver(
                        client_id, key, rec.get("phone") or from_contact,
                        {"channel": channel, "subject": None, "body": acknowledgment,
                         "whatsapp_from": to_phone_id, "whatsapp_chat_id": whatsapp_chat_id, "humanize": True},
                        wa_creds=wa_creds)
                except (RuntimeError, ValueError) as exc:
                    customer_ack = {"status": "error", "error": str(exc)}
                if customer_ack["status"] == "sent":
                    self.memory.add_turn(client_id, key, "agent", acknowledgment)
            self.memory.log("internal_budget_review", client=client_id, lead=key,
                            status=delivery["status"], total=quote.get("total"))
            self.memory.save()
            if self.crm:
                self.crm.log(client_id, key, "awaiting_human",
                             "Presupuesto aceptado por WhatsApp Web; revisar en grupo" if
                             delivery["status"] == "accepted" else
                             "Presupuesto interno pendiente de revisión del envío")
                if customer_ack:
                    self.crm.log(client_id, key,
                                 "auto_reply_accepted" if customer_ack["status"] == "sent"
                                 else "auto_reply_failed", acknowledgment[:140])
                self.crm.save()
            if customer_ack and customer_ack["status"] != "sent":
                # The budget is already in the group, but the lead may not have
                # received this acknowledgment. Keep the event for human review.
                delivery = {"status": "error", "error": customer_ack.get("error") or
                            "No se confirmó el aviso al cliente"}
            return {"matched": True, "manual_review": delivery["status"] == "accepted",
                    "intent": "pricing", "company": rec.get("company"),
                    "delivery": delivery, "customer_ack": customer_ack, **out}
        def repetition(candidate: str) -> bool:
            # A deterministic step that sends a poll is the flow asking its next
            # question, not the model looping; flagging it would hand the chat off.
            if (candidate in (SHIPPING_COVERAGE_REPLY, SHIPPING_PRICE_REPLY) or intent == "catalog"
                    or res.get("customer_poll") or res.get("delivery_poll")
                    or res.get("flow_step")):
                return False
            return bool(channel == "whatsapp" and client_id == "losetaschile" and
                        (any(turn.get("role") == "agent" and _same_reply(candidate, turn.get("text"))
                             for turn in prior_turns) or
                         _asks_again_for_supplied_measurements(text, candidate, prior_turns)))
        repeated = repetition(reply)
        unsafe_shipping = (client_id == "losetaschile" and
                           _unverified_shipping_claim(text, reply,
                                                      self.memory.get_client_knowledge(client_id)))
        unsupported_review = _unverified_quote_review_claim(reply)
        unsupported_count = (client_id == "losetaschile" and
                             unquoted_piece_count(reply, quote))
        if ((repeated and not _simple_greeting(text)) or unsafe_shipping or unsupported_review) and intent != "handoff":
            revised = self.converse_result(
                client_id, text, lead=rec, channel=channel, history=prior_turns,
                feedback="El cliente ya entregó medidas o esa respuesta ya se dio. "
                         "Responde la pregunta nueva usando esos datos. No vuelvas a pedir medidas "
                         "ni repitas la respuesta anterior. No afirmes que revisaste una consulta, "
                         "cotización o presupuesto sin evidencia. Si consulta por despacho, no "
                         "afirmes disponibilidad: requiere revisión humana. Si no puedes responder, "
                         "usa intent handoff.")
            reply, intent = revised.get("reply") or "", revised.get("intent") or "general"
            quote = revised.get("quote")
            repeated = repetition(reply)
            unsafe_shipping = _unverified_shipping_claim(
                text, reply, self.memory.get_client_knowledge(client_id))
            unsupported_review = _unverified_quote_review_claim(reply)
            unsupported_count = (client_id == "losetaschile" and
                                 unquoted_piece_count(reply, quote))
        if repeated and _simple_greeting(text) and intent != "handoff":
            # Un saludo nuevo no debe silenciar el chat por una respuesta anterior igual.
            # Responder sin repetir preguntas viejas ni inventar datos del negocio.
            greeting = whatsapp_greeting()
            reply = (pick_variant(WHATSAPP_FALLBACK_GREETINGS_NAMED, key, self._last_agent_text(client_id, key),
                                  greeting=greeting, name=introduced_name) if introduced_name
                     else pick_variant(WHATSAPP_FALLBACK_GREETINGS, key,
                                       self._last_agent_text(client_id, key), greeting=greeting))
            intent, quote = "general", None
            repeated = False
        if client_id == "losetaschile" and channel == "whatsapp" and reply:
            reply = format_whatsapp_reply(reply)
        not_known = (client_id == "losetaschile" and channel == "whatsapp" and
                     intent != "handoff" and not res.get("flow_step") and
                     _admits_not_knowing(reply))
        if channel == "whatsapp" and (intent == "handoff" or not reply.strip() or repeated or
                                      unsafe_shipping or unsupported_review or unsupported_count
                                      or not_known):
            reason = ((res.get("review_reason") or res.get("gap_reason") or
                       "El agente no entendió la consulta")
                      if intent == "handoff" else
                      "El agente no tenía la información" if not_known else
                      "Respuesta sobre despacho requiere revisión" if unsafe_shipping else
                      "Revisión de consulta no comprobada" if unsupported_review else
                      "Cantidad de piezas sin presupuesto comprobado" if unsupported_count else
                      "El agente repitió una respuesta" if repeated else
                      "El agente no pudo redactar una respuesta")
            self.memory.add_turn(client_id, key, "lead", text)
            # A generated draft can require human review for this message
            # without taking over the chat forever. Explicit human requests
            # and unreadable attachments are handled earlier and remain handoffs.
            self.memory.log("whatsapp_review_required", client=client_id,
                            lead=key, reason=reason)
            # La consulta que llegó hasta acá es una que el agente no supo
            # contestar. Se guarda la PREGUNTA, nunca el borrador: ese texto es
            # justo el que no sirvió. Una persona escribe la respuesta buena una
            # vez y entra a la ficha, que ya se consulta en cada conversación.
            self.memory.add_knowledge_gap(
                client_id, text, reason, chat_id=whatsapp_chat_id or key,
                contacto=rec.get("name") or rec.get("phone") or "", lead_key=key,
                tipo="pedido" if res.get("review_reason") else "pregunta")
            self.memory.save()
            if self.crm:
                self.crm.log(client_id, key, "awaiting_human", reason)
                self.crm.save()
            notice = pick_variant(WHATSAPP_REVIEW_NOTICES, key,
                                  self._last_agent_text(client_id, key))
            notice_delivery = self._deliver(
                client_id, key, rec.get("phone") or rec.get("email"),
                {"channel": channel, "subject": None, "body": notice,
                 "whatsapp_from": to_phone_id, "whatsapp_chat_id": whatsapp_chat_id, "humanize": True},
                wa_creds=wa_creds)
            if notice_delivery["status"] == "sent":
                self.memory.add_turn(client_id, key, "agent", notice)
                self.memory.save()
            if self.crm:
                self.crm.log(client_id, key,
                             "auto_reply_accepted" if notice_delivery["status"] == "sent"
                             else "auto_reply_failed", notice[:140])
                self.crm.save()
            return {"matched": True, "manual_review": True, "intent": "handoff",
                    "company": rec.get("company"),
                    "delivery": notice_delivery, **out}
        self.memory.add_turn(client_id, key, "lead", text)

        numbered_key = (("delivery" if res.get("delivery_poll") else res.get("customer_poll"))
                        if client_id == "losetaschile" and channel == "whatsapp" else None)
        if (numbered_key and LOSETASCHILE_CHOICE_STYLE == "poll" and
                numbered_key in WHATSAPP_WEB_POLL_KEYS):
            numbered_key = None  # the bridge has a poll for this question
        if numbered_key and reply:
            reply = reply.rstrip() + "\n\n" + numbered_choices(str(numbered_key), reply)
            res = {key_: value for key_, value in res.items()
                   if key_ not in ("customer_poll", "delivery_poll")}
        delivery = {"status": "error", "error": "El agente no produjo una respuesta"}
        poll_delivery = None
        if reply:
            if client_id == "losetaschile" and channel == "whatsapp" and res.get("catalog_document"):
                if not whatsapp_chat_id or not to_phone_id:
                    delivery = {"status": "error", "error": "Falta chat Web para enviar catálogo visual"}
                else:
                    from .whatsapp_web import send_catalog_document
                    try:
                        document = res["catalog_document"]
                        sent = send_catalog_document(
                            client_id, to_phone_id, rec.get("phone") or from_contact,
                            document["category"], document["pricing"],
                            chat_id=whatsapp_chat_id)
                        delivery = {"status": "sent", "via": "whatsapp_web",
                                    "id": sent["id"], "ack": sent.get("ack")}
                        self.memory.add_turn(client_id, key, "agent",
                                             "Catálogo Bordes de Piscina" if
                                             document["category"] == "bordes" else
                                             "Catálogo Pastelones")
                        if res.get("reply_after_document"):
                            delivery = self._deliver(
                                client_id, key, rec.get("phone") or from_contact,
                                {"channel": channel, "subject": None, "body": reply,
                                 "whatsapp_from": to_phone_id,
                                 "whatsapp_chat_id": whatsapp_chat_id, "humanize": True}, wa_creds=wa_creds)
                        if res.get("media_asset"):
                            from .whatsapp_web import send_catalog_image
                            from pathlib import PurePosixPath
                            image = send_catalog_image(
                                client_id, to_phone_id, rec.get("phone") or from_contact,
                                PurePosixPath(res["media_asset"]).name, reply,
                                chat_id=whatsapp_chat_id)
                            delivery = {"status": "sent", "via": "whatsapp_web",
                                        "id": image["id"], "ack": image.get("ack")}
                    except (RuntimeError, ValueError) as exc:
                        delivery = {"status": "error", "error": str(exc)}
                        if res.get("reply_after_document"):
                            # The question still goes out: without it the chat stalls.
                            delivery = self._deliver(
                                client_id, key, rec.get("phone") or from_contact,
                                {"channel": channel, "subject": None, "body": reply,
                                 "whatsapp_from": to_phone_id,
                                 "whatsapp_chat_id": whatsapp_chat_id, "humanize": True}, wa_creds=wa_creds)
            elif client_id == "losetaschile" and channel == "whatsapp" and res.get("media_asset"):
                if not whatsapp_chat_id or not to_phone_id:
                    delivery = {"status": "error", "error": "Falta chat Web para enviar imagen"}
                else:
                    try:
                        from .whatsapp_web import send_catalog_image
                        from pathlib import PurePosixPath
                        sent_image = send_catalog_image(
                            client_id, to_phone_id, rec.get("phone") or from_contact,
                            PurePosixPath(res["media_asset"]).name, reply,
                            chat_id=whatsapp_chat_id)
                        delivery = {"status": "sent", "via": "whatsapp_web",
                                    "id": sent_image["id"], "ack": sent_image.get("ack")}
                    except (RuntimeError, ValueError) as exc:
                        delivery = {"status": "error", "error": str(exc)}
            else:
                delivery = self._deliver(client_id, key, rec.get("phone") or rec.get("email"),
                              {"channel": channel, "subject": None, "body": reply,
                               "whatsapp_from": to_phone_id,
                               "whatsapp_chat_id": whatsapp_chat_id, "humanize": True}, wa_creds=wa_creds)
            if delivery.get("partial"):
                # Part of the reply is already in the chat: keep what went out and
                # leave the case for a person, not for an automatic retry.
                self.memory.add_turn(client_id, key, "agent", delivery.get("sent_text") or "")
                self.memory.log("whatsapp_review_required", client=client_id, lead=key,
                                reason=delivery.get("error") or "envío parcial")
                if self.crm:
                    self.crm.log(client_id, key, "awaiting_human", delivery.get("error") or "envío parcial")
            if delivery["status"] == "sent":

                self.memory.add_turn(client_id, key, "agent", reply)
                if res.get("attention"):
                    # Answered, but a person still has to act: it goes to the
                    # dashboard's attention list with this chat attached.
                    self.memory.add_knowledge_gap(
                        client_id, text, res["attention"], chat_id=whatsapp_chat_id or key,
                        contacto=rec.get("name") or rec.get("phone") or "", lead_key=key, tipo="pedido")
                if res.get("owner_alert") == "pool_photo":
                    from .alerts import notify_owner
                    # Every case is a different customer: no throttle window.
                    alert = notify_owner(
                        "Losetas Chile — piscina no rectangular.\n"
                        f"Cliente: {name_from_profile or rec.get('name') or 'sin nombre'} "
                        f"(+{rec.get('phone') or from_contact})\n"
                        f"Escribió: {(text or '')[:200]}\n"
                        "Se le pidió una foto de la piscina; revísala en el chat y cotiza.",
                        kind="pool_photo", throttle_minutes=0)
                    self.memory.log("owner_alert", client=client_id, lead=key,
                                    kind="pool_photo", status=alert.get("status"))
                if (client_id == "losetaschile" and channel == "whatsapp" and
                        res.get("delivery_poll") and whatsapp_chat_id and to_phone_id):
                    try:
                        from .whatsapp_web import send_delivery_poll
                        poll_delivery = send_delivery_poll(
                            client_id, to_phone_id, rec.get("phone") or from_contact,
                            whatsapp_chat_id)
                    except (RuntimeError, ValueError) as exc:
                        poll_delivery = {"status": "error", "error": str(exc)}
                    self.memory.log("delivery_poll", client=client_id, lead=key,
                                    status=poll_delivery.get("status", "sent"))
                    if poll_delivery.get("status") == "sent":
                        self.memory.add_turn(client_id, key, "agent",
                                             LOSETAS_DELIVERY_POLL_QUESTION)
                if (client_id == "losetaschile" and channel == "whatsapp" and
                        res.get("customer_poll") and whatsapp_chat_id and to_phone_id):
                    try:
                        from .losetas_polls import CHOICE_PROMPTS
                        from .whatsapp_web import send_choice_poll
                        poll_delivery = send_choice_poll(
                            client_id, to_phone_id, rec.get("phone") or from_contact,
                            whatsapp_chat_id, str(res["customer_poll"]))
                        question = CHOICE_PROMPTS[str(res["customer_poll"])][0]
                        self.memory.add_turn(client_id, key, "agent", question)
                    except (RuntimeError, ValueError) as exc:
                        poll_delivery = {"status": "error", "error": str(exc)}
                    self.memory.log("customer_poll", client=client_id, lead=key,
                                    poll=res["customer_poll"],
                                    status=poll_delivery.get("status", "error"))
            if self.crm:
                # Un presupuesto enviado es un evento de venta, no una respuesta más:
                # queda aparte en el historial para que un humano lo vea de un vistazo.

                if quote:
                    if quote.get("shipping_pending"):
                        quote_event = ("product_subtotal_failed" if delivery["status"] != "sent" else
                                       "product_subtotal_accepted" if delivery.get("via") == "whatsapp_web"
                                       else "product_subtotal_sent")
                        quote_detail = (f"productos {quote['currency']} {quote['total']:,.0f} "
                                        f"({len(quote['lines'])} ítems); despacho pendiente")
                    else:
                        quote_event = ("quote_failed" if delivery["status"] != "sent" else
                                       "quote_accepted" if delivery.get("via") == "whatsapp_web" else "quote_sent")
                        quote_detail = (f"presupuesto {quote['currency']} {quote['total']:,.0f} "
                                        f"({len(quote['lines'])} ítems)")
                    self.crm.log(client_id, key, quote_event, quote_detail)
                else:
                    reply_event = ("auto_reply_failed" if delivery["status"] != "sent" else
                                   "auto_reply_accepted" if delivery.get("via") == "whatsapp_web" else "auto_reply")
                    self.crm.log(client_id, key, reply_event, reply[:140])
                self.crm.save()
        if quote and delivery["status"] == "sent":

            self.memory.log("quote", client=client_id, lead=key,
                            total=quote["total"], currency=quote["currency"],
                            items=[(l["id"], l["qty"]) for l in quote["lines"]])
        self.memory.save()
        # The reply itself made an offer → remember it; an opt-out voids any open one.

        if offer_flow and intent == "info" and delivery["status"] == "sent":

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

        return {"matched": True, "company": rec.get("company"),
                "reply": reply if delivery.get("status") == "sent" else "", "intent": intent,
                "delivery": delivery, "poll_delivery": poll_delivery, **out}


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
        # La proyección sigue siendo útil cuando ANALYST no puede consultar su
        # modelo (por ejemplo, saldo agotado): se usan las tasas base declaradas
        # en config y se informa el origen en la API y el dashboard.
        base_rates = resp.status == "error"
        proposed = FORECAST_RATES if base_rates else (resp.result.get("rates") or {})
        projection = project_funnel(metrics["contacted"], proposed, AVG_DEAL_VALUE_CLP)
        rates_used = projection.pop("_rates_used")
        forecast = {
            "inputs": metrics,
            "assumptions": {**rates_used, "avg_deal_value_clp": AVG_DEAL_VALUE_CLP},
            "projection": projection,
            "commentary": ("Tasas base sin ajuste: el modelo de IA no estuvo disponible."
                           if base_rates else resp.result.get("commentary")),
        }
        self.memory.log("forecast", client=client_id,
                        pipeline_clp=projection["expected_pipeline_clp"])
        self.memory.set_stage(client_id, "delivered")
        self.memory.save()
        return {"client_id": client_id, "forecast": forecast, "notes": resp.notes,
                "rate_source": "base_rates" if base_rates else "model"}

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
