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

# --- WhatsApp entrante de un desconocido (sin lead previo) --------------------
# Un vendedor de verdad SIEMPRE contesta a quien le escribe por primera vez —
# no solo a quienes ZERO contactó antes. Decisión de Diego (2026-07-22): un
# desconocido que escribe se registra como lead NUEVO bajo este cliente, en vez
# de ignorarse en silencio (antes: "inbound_unmatched" y nada más).
#
# Por qué hace falta un default explícito: el número que RECIBE el mensaje
# resuelve a un VENDEDOR (Fernanda/Stéfano), no a un cliente — y varios
# clientes pueden compartir el mismo vendedor (zero/vendors.py::
# clients_count_for). Si ese número pertenece a un único cliente sin
# ambigüedad, ZERO usa ese (correcto en producción, con un número propio por
# cliente). Si no — hoy, mientras el sandbox de Twilio usa UN SOLO número
# compartido para cualquier prueba — cae aquí.
# `None`/"" desactiva el catch-all (vuelve al comportamiento anterior: ignora
# al desconocido) — útil si algún día hay varios clientes reales y ya no
# tiene sentido adivinar.
#
# 2026-08-21: pasa de "demo" a "zeroai". El catch-all decide CON QUÉ NEGOCIO se
# atiende a un desconocido, y "demo" era una ficha de prueba (pallets de madera):
# quien escribiera al WhatsApp recibía una oferta de pallets en vez de nuestros
# servicios. Hoy el número entrante es el nuestro y a quien escribe le vendemos
# lo nuestro. Cuando haya un segundo cliente real con número propio, esto deja de
# usarse: `_resolve_inbound_client` resuelve por `phone_id` del vendedor y solo
# cae acá si no puede (ver zero/orchestrator.py::handle_inbound).
DEFAULT_INBOUND_CLIENT_ID = "zeroai"

# --- Acciones que una función programada puede PEDIR --------------------------
# Una función sandboxeada nunca actúa por sí misma: corre con --network=none y
# sin credenciales (zero/sandbox.py), así que lo único que puede hacer es
# DEVOLVER acciones como datos ({"actions": [...]} en su `result`). El lado
# confiable —fuera de Docker— las valida contra esta política y recién ahí las
# ejecuta con el mismo Outbox/CRM de siempre (zero/function_actions.py). Darle
# red y credenciales al sandbox para que mandara mensajes él mismo sería
# regalarle a código arbitrario la capacidad de exfiltrar el CRM entero.
#
# Tipos permitidos. Sacar uno de acá lo deshabilita para TODAS las funciones,
# sin tocar lógica — un tipo no listado se rechaza con motivo claro:
#   whatsapp / email → mandan un mensaje al lead (vía Outbox: sigue siendo mock
#                      salvo que OUTBOX_LIVE=1, igual que cualquier otro envío)
#   stage            → mueve el lead de etapa en el CRM
#   note             → deja una nota en el historial del lead
FUNCTION_ALLOWED_ACTION_TYPES = ("whatsapp", "email", "stage", "note")

# Tope de acciones por corrida. Una función con un bug (un bucle que agrega una
# acción por lead sin filtrar) no puede convertirse en un envío masivo
# accidental a toda la cartera: lo que pase de este número se rechaza y queda
# reportado, no se ejecuta a medias en silencio.
FUNCTION_MAX_ACTIONS_PER_RUN = 25

# --- trabajos de agente pedidos por una función programada -------------------
# Lo que convierte al panel de Funciones en una empresa que opera sola: una
# función vencida puede pedir que corran los AGENTES (buscar leads nuevos,
# avanzar seguimientos), no solo tocar leads uno por uno. Misma regla de
# siempre: el sandbox no ejecuta nada — pide, y este lado confiable valida y
# corre. Ver zero/function_actions.py.
FUNCTION_ALLOWED_JOB_TYPES = ("pipeline", "followups")

# Un trabajo por corrida. Los `actions` normales toleran 25 porque son baratos
# (mover una etapa, dejar una nota); un trabajo de agente sale a la web, llama
# al modelo y tarda minutos. Una función con un bucle con bug que pidiera 25
# pipelines dejaría al scheduler ocupado horas y llenaría el CRM de basura.
FUNCTION_MAX_JOBS_PER_RUN = 1

# Tope duro de leads por corrida automática, por encima de lo que pida la
# función. El límite mensual del tier sigue aplicando aparte (tier_config);
# esto es el freno de mano de lo desatendido: nadie mira una corrida a las
# 07:00, así que no puede irse a 200 leads por un número mal escrito.
FUNCTION_JOB_MAX_COUNT = 10

# Las corridas automáticas NUNCA envían: dejan el mensaje en borrador
# (outreach.status="draft") para que una persona lo apruebe desde el dashboard.
# Es la misma decisión que ya rige el disparo manual (auto_send=False por
# defecto en la API desde 2026-07-19), sostenida acá donde más importa: si algo
# sale mal a las 07:00, ensucia el CRM — no le llega a un cliente real.
FUNCTION_JOBS_AUTO_SEND = False

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

# --- Mensaje entrante de un lead (CONCIERGE) ----------------------------------
# Tope al mensaje que un lead escribe (WhatsApp/email) antes de pasarlo a
# CONCIERGE. Hallado en vivo (2026-07-13) contra el modelo real (qwen2.5:7b):
# un mensaje muy largo y degenerado ("hola " x3000) hizo que el modelo
# abandonara por completo el esquema JSON pedido ({"reply","intent"}) e
# inventara uno propio ({"greeting","message","options"}) — como ninguna de
# esas claves está en el contrato, la respuesta al lead terminaba VACÍA (sin
# romper nada, pero sin contestarle). WhatsApp real ya limita cada mensaje a
# ~4096 caracteres; este tope es más chico a propósito, con margen.
MAX_INBOUND_MESSAGE_CHARS = 2000

# --- Motor de WhatsApp (2026-08-21) -------------------------------------------
# QUÉ CEREBRO contesta un WhatsApp entrante. Es el único frente del producto que
# corre con modelo LOCAL a propósito; el resto (dashboard, scheduler, funciones)
# no cambia de motor por esto.
#
# El porqué: WhatsApp es conversación de alto volumen y baja dificultad —
# responder dudas de un lead con la ficha del vendor delante. Un modelo local
# lo hace bien y su costo marginal es CERO, mientras que la API paga cobra por
# cada mensaje de cada lead, para siempre. Medido en esta máquina (2026-08-21):
# qwen2.5:14b-instruct-q4_K_M en la RTX 5060 Ti da ~40 tokens/s, 100% en GPU.
#
# La jaula es deliberada: el modelo local se limita a este canal. No se extiende
# a otros agentes sin una decisión explícita — decisión de Diego, 2026-08-21.
#
# Orden de preferencia: local (gratis) → Anthropic (pago) → mock. El respaldo
# pago existe porque un Ollama caído no debe dejar a un lead sin respuesta;
# es un respaldo, no el camino normal.
WHATSAPP_ENGINE = {
    "model": "qwen2.5:14b-instruct-q4_K_M",   # el que ya está cargado en VRAM
    "base_url": "http://localhost:11434/v1",  # Ollama, endpoint OpenAI-compatible
    "fallback_to_paid": True,                 # si el local no responde → Anthropic
}

# --- Avisos al dueño (zero/alerts.py) -----------------------------------------
# Caer al motor pagado es exactamente el evento que no debe pasar inadvertido:
# empieza a costar plata sin que nadie lo haya pedido. Se avisa al celular por el
# MISMO WhatsApp del producto (sin servicio nuevo), al número de OWNER_WHATSAPP_TO.
# Sin esa variable no se avisa a nadie y no es un error — es el default.
#
# La ventana evita el peor modo de falla de un aviso: un Ollama caído una hora
# genera un aviso, no doscientos.
ALERT_THROTTLE_MINUTES = 30

# --- Mercado activo (2026-07-19) -----------------------------------------------
# ZeroAI prospecta SOLO en Chile por ahora — decisión explícita de Diego mientras
# se prueba con leads reales; otros países son plan a futuro (cuando eso cambie,
# se actualiza ACÁ, no la lógica de discovery/validators que lo usa). Dos efectos:
#   1) icp.normalize_icp() usa ACTIVE_MARKET_REGIONS como default de `regions`
#      cuando el cliente no especificó zona — ningún cliente queda "sin país"
#      por accidente, ni depende de que alguien lo escriba a mano en el ICP.
#   2) ValidatorRules.validate_phone() descarta cualquier teléfono con código de
#      país EXPLÍCITO distinto de +56 (ej. uno argentino/peruano capturado por
#      el patrón internacional genérico de discovery.py). Un teléfono en
#      formato local (sin "+", el caso más común en sitios chilenos) se deja
#      pasar — no hay señal de que sea de otro país. Esto es un filtro
#      pragmático, no un validador geográfico exhaustivo: no verifica que el
#      NEGOCIO esté físicamente en Chile, solo descarta contactos con un
#      código de país explícitamente extranjero.
ACTIVE_MARKET_REGIONS = ["Chile"]
ACTIVE_MARKET_PHONE_COUNTRY_CODE = "56"   # sin '+', para comparar dígitos

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
        "price_clp": 200_000,
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
# --- Asunto de correo (2026-08-21) -------------------------------------------
# Los prompts de OUTREACH/TRACKER declaran `"subject": "string|null"` y el
# modelo, teniendo permitido null, lo devuelve null casi siempre. El transporte
# entonces caía a "Hola" (zero/channels.py) — un correo B2B en frío titulado
# "Hola", desde una dirección desconocida, es candidato directo a spam.
#
# Se pide bien en el prompt Y se asegura acá: con motor local ya comprobamos que
# pedir por prompt no alcanza (ver converse_result). El asunto es texto de cara
# al cliente, o sea política: se cambia acá, no en la lógica.
# `{company}` es el único campo que se sustituye; si falta, se usa la variante corta.
EMAIL_SUBJECT_FALLBACK = "{company}: una idea para conseguir más clientes"
EMAIL_SUBJECT_FALLBACK_SIN_EMPRESA = "Una idea para conseguir más clientes"


def email_subject_fallback(company: Optional[str] = None) -> str:
    """Asunto de respaldo cuando el modelo no redactó uno. Nunca vacío."""
    nombre = (company or "").strip()
    if not nombre:
        return EMAIL_SUBJECT_FALLBACK_SIN_EMPRESA
    return EMAIL_SUBJECT_FALLBACK.format(company=nombre)


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


# --- Finanzas de la AGENCIA (zero/finance.py) ----------------------------------
# Qué rubros de costo existen para ZeroAI — la política. Las cifras reales nunca
# van aquí ni en ningún archivo versionado: viven en finance.json (local,
# gitignorado, mismo trato que crm.json). Un costo con rubro desconocido cae en
# "otros" en vez de perderse.
FINANCE_COST_CATEGORIES = (
    "vapi",         # llamadas (por minuto, USD → anotar ya convertido a CLP)
    "elevenlabs",   # voz Francisca (por caracteres)
    "supabase",     # hoy plan gratis ($0)
    "dominio",      # 1 cifra al año
    "vps",          # hipotético (si se migra del PC Ubuntu)
    "anthropic",    # solo si se activa --live (motor local gratis desde 2026-07)
    "otros",
)


# --- Formularios públicos de la landing (zeroai.cl) ----------------------------
# Quien deja sus datos en la landing es un lead NUESTRO, no de un cliente: entra
# al CRM bajo este client_id. Hoy vale lo mismo que DEFAULT_INBOUND_CLIENT_ID —
# son la misma idea vista desde dos puertas (el que escribe al WhatsApp y el que
# llena el formulario), pero responden preguntas distintas y se dejan separadas a
# propósito: cambiar el catch-all de WhatsApp no debe mudar de dueño a la waitlist.
AGENCY_CLIENT_ID = "zeroai"

# De qué formulario viene. La landing tiene dos y ambos escriben al mismo
# endpoint; sin esto, en el CRM no se distingue a quien pidió entrar a la lista
# de espera de quien estaba conversando con el chat — que son dos intenciones de
# compra muy distintas. Un origen fuera de esta lista se rechaza: es mejor un 400
# visible que un CRM con etiquetas inventadas por un formulario mal desplegado.
PUBLIC_FORM_ORIGINS = ("waitlist", "chat")

# Cuántos envíos por hora se aceptan desde una misma IP. Es un endpoint sin
# login: sin tope, un script deja el CRM inservible en una tarde. No pretende
# frenar a un atacante decidido (la IP se puede rotar, y detrás de un proxy
# llega en una cabecera que se puede falsificar); frena el accidente y el script
# perezoso, que es lo que de verdad pasa. Súbelo si una campaña real lo topa.
PUBLIC_FORM_MAX_PER_HOUR_PER_IP = 10


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
