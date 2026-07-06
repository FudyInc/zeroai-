"""Static configuration: models, tiers, and qualified-lead rules.

Everything that defines *policy* (what a tier gets, what makes a lead deliverable,
which model each role uses) lives here so it can change without touching logic.
"""
from __future__ import annotations

# --- Models ------------------------------------------------------------------
FABLE = "claude-fable-5"      # el más potente — cerebro de ZERO (orquestador).
OPUS = "claude-opus-4-8"      # Opus 4.8 — alternativa fuerte.
SONNET = "claude-sonnet-4-6"  # sub-agentes críticos en la ruta API.

ZERO_MODEL = FABLE

# --- Vendors -------------------------------------------------------------------
# Vendedor asignado a un cliente cuando no se elige uno explícitamente. Debe
# existir en el catálogo semilla (zero/vendors.py::seed_vendors).
DEFAULT_VENDOR_ID = "fernanda"

# --- WhatsApp Business — plantilla para contacto en frío ----------------------
# Meta EXIGE una plantilla pre-aprobada para el primer mensaje a un lead que nunca
# escribió, o cualquier mensaje fuera de la ventana de 24h desde su último mensaje —
# un mensaje de texto libre en frío es rechazado por la Graph API real. Dentro de esa
# ventana (o respondiendo a algo que el lead ya escribió) el texto libre SÍ está bien.
# `name` queda en None hasta que Diego cree la plantilla en Meta Business Manager y
# Meta la apruebe (paso manual, fuera del código) — sin nombre, WhatsAppSender no
# manda nada en frío y lo reporta como error visible en el CRM (mock-first: nunca
# intenta un texto libre que Meta rechazaría en silencio).
WHATSAPP_TEMPLATE = {
    "name": None,      # nombre exacto de la plantilla aprobada en Meta Business Manager
    "language": "es",  # código de idioma de la plantilla aprobada
}

# --- Reintentos de envío (Outbox) ---------------------------------------------
# Un corte de red momentáneo no debe perder un envío para siempre. Outbox.send
# reintenta hasta OUTBOX_RETRY_ATTEMPTS veces en total (incluye el primer intento),
# esperando OUTBOX_RETRY_DELAY_SECONDS entre cada uno, antes de degradar a "error".
OUTBOX_RETRY_ATTEMPTS = 3
OUTBOX_RETRY_DELAY_SECONDS = 1.0

# --- Client tiers ------------------------------------------------------------
# leads_per_mo = None means "custom / negotiated".
# price_clp = lo que el cliente paga por mes (el MRR de la agencia). ENTERPRISE = custom.
TIERS = {
    "STARTER": {
        "segment": "Básico",
        "price_clp": 50_000,
        "leads_per_mo": 50,
        "scoring": "basic",        # generic ICP
        "channels": ["email", "whatsapp"],
    },
    "GROWTH": {
        "segment": "Pro",
        "price_clp": 100_000,
        "leads_per_mo": 200,
        "scoring": "advanced",     # client-specific ICP
        "channels": ["email", "whatsapp", "cold_call"],
    },
    "SCALE": {
        "segment": "Full",
        "price_clp": 500_000,
        "leads_per_mo": 500,
        "scoring": "intent",       # ICP + buying intent
        "channels": ["email", "whatsapp", "cold_call", "linkedin"],
    },
    "ENTERPRISE": {
        "segment": "Custom",
        "price_clp": None,         # negociado
        "leads_per_mo": None,
        "scoring": "vertical",     # per-vertical model
        "channels": ["email", "whatsapp", "cold_call", "linkedin", "sdr_ai"],
    },
}


def tier_config(tier: str) -> dict:
    try:
        return TIERS[tier]
    except KeyError:
        raise ValueError(f"Unknown tier: {tier!r}. Valid: {list(TIERS)}")


# --- Contact validator tiers (zero/validators.py) -----------------------------
# How strict validators.py is about a contact's email/phone/name before a lead
# is allowed past discovery into the CRM. GROWTH is liberal (some contact info
# is better than none); ENTERPRISE is strict (only well-formed, reachable
# contacts — matches the "confiable" promise for paying enterprise clients).
# Tiers without an explicit entry fall back to DEFAULT_VALIDATOR_TIER.
VALIDATOR_TIERS = {
    "GROWTH": {
        "email": {"require": True, "min_len": 5, "must_have_tld": False},
        "phone": {"require": False, "min_digits": 7},
        "name": {"require": True, "min_len": 1},
    },
    "ENTERPRISE": {
        "email": {"require": True, "min_len": 6, "must_have_tld": True,
                  "valid_tlds": [".com", ".es", ".mx", ".cl", ".co", ".ar"]},
        "phone": {"require": True, "min_digits": 9},
        "name": {"require": True, "min_len": 3},
    },
}
DEFAULT_VALIDATOR_TIER = "GROWTH"


def validator_tier(tier: str) -> dict:
    """Validator rules for `tier`, falling back to the default for tiers
    (STARTER, SCALE, ...) that don't have a dedicated entry yet."""
    return VALIDATOR_TIERS.get(tier, VALIDATOR_TIERS[DEFAULT_VALIDATOR_TIER])


# --- Qualified-lead rules ----------------------------------------------------
# El piso de calificación varía por tier — el modelo de negocio (2026-07-04,
# decisión de Diego) es vender el mismo servicio a empresas chicas, medianas y
# grandes, a distinto precio y con distinto volumen/calidad de entrega según el
# plan. STARTER (plan de entrada, barato) prioriza volumen — sirve también a
# pymes chicas donde el decisor no siempre se puede verificar con discovery sin
# key. ENTERPRISE (el que más paga) exige más precisión. Encontrado en vivo
# (pipeline real, Ollama qwen2.5:7b, PyMEs reales de "pooledge"): con el piso
# único de 70, 0/8 empresas reales calificaban — todas penalizadas por falta de
# decisor verificado, no por mal fit de industria.
MIN_ICP_SCORE = 60            # default / fallback para tiers sin entrada propia
MIN_ICP_SCORE_BY_TIER = {
    "STARTER": 50,
    "GROWTH": 60,
    "SCALE": 70,
    "ENTERPRISE": 80,
}
RECONTACT_BLACKOUT_DAYS = 90  # do not deliver a lead contacted more recently
REQUIRED_FIELDS = ("company", "role", "channel")  # minimum fields a lead needs


def min_icp_score(tier: Optional[str]) -> int:
    """Piso de calificación para `tier` — cae a MIN_ICP_SCORE si el tier no
    tiene entrada propia o no se pasa ninguno (ej. tests que llaman a
    validate_lead sin tier)."""
    return MIN_ICP_SCORE_BY_TIER.get(tier or "", MIN_ICP_SCORE)

# --- Follow-up cadence (TRACKER) ---------------------------------------------
# After OUTREACH sends the first touch (step 0), TRACKER advances a lead through
# these steps. `day` is the offset from the first touch; the sequence closes
# after the last step. Keep it short and respectful.
FOLLOWUP_STEPS = (
    {"day": 3, "kind": "nudge"},     # gentle reminder
    {"day": 7, "kind": "value"},     # add a proof point / case
    {"day": 14, "kind": "breakup"},  # last touch, leave the door open
)


def followup_step(step: int) -> dict:
    """Return the cadence entry for a step index, or None past the last one."""
    return FOLLOWUP_STEPS[step] if 0 <= step < len(FOLLOWUP_STEPS) else None


# --- Forecasting (ANALYST) ---------------------------------------------------
# Stage-to-stage conversion assumptions used to project pipeline from current
# activity. Deliberately conservative defaults; ANALYST may refine them live.
FORECAST_RATES = {
    "reply_rate": 0.18,       # contacted -> replied
    "meeting_rate": 0.35,     # replied -> meeting booked
    "win_rate": 0.25,         # meeting -> closed won
}
AVG_DEAL_VALUE_CLP = 1_000_000   # valor promedio por cierre, en CLP (ajustable)


# --- Presupuestos (cotizaciones por chat) --------------------------------------
# El IVA que se aplica a un presupuesto cuando la lista de precios del cliente no
# lo especifica. La aritmética del presupuesto NUNCA la hace el LLM (quotes.py).
IVA_RATE = 0.19   # IVA Chile


# --- CRM pipeline stages -----------------------------------------------------
# The lifecycle a lead moves through in ZERO's system of record. Ordered; the
# CRM board renders them left→right. ZERO advances the first ones automatically;
# the later ones (replied→won) are set as the human learns what happened.
CRM_STAGES = (
    "new",          # captured, not yet judged
    "qualified",    # passed the qualified-lead gate
    "disqualified", # failed the gate (kept for the record + analytics)
    "contacted",    # first touch sent
    "nurturing",    # in an active follow-up sequence
    "replied",      # the lead answered
    "meeting",      # a meeting is booked
    "won",          # closed won
    "lost",         # closed lost / gave up
)
CRM_OPEN_STAGES = ("new", "qualified", "contacted", "nurturing", "replied", "meeting")


def _rate(value: Any, fallback: float) -> float:
    """Accept a model-supplied rate only if it's a valid probability in [0, 1];
    anything else (non-numeric or out of range) is malformed → use the baseline."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    return v if 0.0 <= v <= 1.0 else fallback


def project_funnel(contacted: int, rates: Dict[str, Any], deal_value: float) -> Dict[str, float]:
    """Deterministic funnel math — never delegated to an LLM.

    ANALYST may *propose* rates, but the projection itself is computed here so the
    numbers are exact on every backend.
    """
    reply = _rate(rates.get("reply_rate"), FORECAST_RATES["reply_rate"])
    meeting = _rate(rates.get("meeting_rate"), FORECAST_RATES["meeting_rate"])
    win = _rate(rates.get("win_rate"), FORECAST_RATES["win_rate"])

    replies = contacted * reply
    meetings = replies * meeting
    wins = meetings * win
    return {
        "expected_replies": round(replies, 1),
        "expected_meetings": round(meetings, 1),
        "expected_wins": round(wins, 2),
        "expected_pipeline_clp": round(wins * deal_value, 2),
        "_rates_used": {"reply_rate": reply, "meeting_rate": meeting, "win_rate": win},
    }
