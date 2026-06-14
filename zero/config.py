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
MIN_ICP_SCORE = 70           # score >= this to be deliverable
RECONTACT_BLACKOUT_DAYS = 90  # do not deliver a lead contacted more recently
REQUIRED_FIELDS = ("company", "role", "channel")  # minimum fields a lead needs

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
