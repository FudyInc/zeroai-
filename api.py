"""HTTP API for ZERO — exposes the pipeline + CRM over JSON (FastAPI).

The foundation a web frontend plugs into. It reuses the exact same core the CLI
uses (orchestrator, CRM, agents) — the API is just a thin HTTP layer, no business
logic of its own. Mock backend by default. Run:

    uvicorn api:app --reload --port 8800

Then the frontend (or http://localhost:8800/docs) talks to it.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel

from zero._env import load_env, set_env
from zero.agents import build_agents

load_env()   # secrets locales (.env) — los de Render env ya están en os.environ
from zero.cloud_env import backed_up_keys, load_into_environ, save_secret
load_into_environ()   # + secretos guardados en la nube (sobreviven a redeploys)
from zero.config import AVG_DEAL_VALUE_CLP, CRM_OPEN_STAGES, CRM_STAGES, DEFAULT_VENDOR_ID, TIERS
from zero.channels import make_outbox
from zero.icp import normalize_icp
from zero.orchestrator import Zero
from zero.quotes import compute_quote, format_quote, normalize_pricing
from zero.store import make_crm, make_memory
from zero.vendors import clients_count_for
from zero._supabase import SupabaseError

CRM_PATH = "crm.json"
STATE_PATH = "state.json"

app = FastAPI(title="ZERO API", version="0.1.0",
              description="Lead-gen B2B — pipeline y CRM por HTTP")

# Open CORS so a frontend on another port (Vite, etc.) can call it during dev.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.exception_handler(SupabaseError)
async def supabase_error_handler(request: Request, exc: SupabaseError):
    """Supabase (CRM o memoria en la nube) inalcanzable/con error — nunca debe
    tirar un 500 crudo. `SupabaseCRM`/`SupabaseMemory` cargan de forma perezosa
    (por diseño, para escalar), así que el fallo real pasa recién al primer query,
    no al construirlas — por eso el manejo va acá, centralizado, y no en cada
    endpoint. 503 = "el servicio de datos está caído ahora", no un bug de ZeroAI."""
    return JSONResponse(
        {"detail": f"Servicio de datos en la nube no disponible: {exc}"},
        status_code=503,
    )

# Endpoints reachable without a token: login, health, auth status, the public
# plans (landing pública, sin login), and the Meta webhook (Meta calls it with
# its own verify token, not ours).
_OPEN_PATHS = {"/api/login", "/api/health", "/api/auth/status", "/api/public/plans"}

# --- roles no-admin: a qué (método, ruta) tiene acceso cada uno --------------
# Todo lo que NO matchee acá para un rol dado exige "admin" — fail closed por
# diseño: una ruta nueva que no se agregue a estas listas queda solo para
# admin automáticamente, nunca abierta a un rol por accidente. "admin" (Diego)
# nunca pasa por esta tabla — ve todo siempre (ver auth_guard).
#
# Construido grepeando qué llama CADA PÁGINA real del dashboard (no adivinado
# — ver el prompt/auditoría que dejó esto documentado), mapeado a las
# personas/áreas que Diego asignó (2026-07-17):
#   - "cro" (Lucas): Clientes, Campañas, Vender, Forecast — más Finanzas,
#     EXCLUSIVO de este rol (ni siquiera "cto" lo tiene).
#   - "cto" (Alejandro): operación de Leads/Pipeline/Forecast — dedicado full
#     a esa área, sin Campañas/Vender/Clientes/Finanzas.
#   - Pipeline (el board) y Forecast son compartidos por los dos — son la
#     vista operativa común de "en qué está cada lead" y "cómo viene el mes";
#     Diego no pidió sacárselos a Lucas al darle esas páginas a Alejandro.
_ROLE_ALLOWED: dict = {
    "cro": (
        ("GET", "/api/clients"),          # selector de cliente (global, App.jsx)
        ("GET", "/api/accounts"),         # Clientes.jsx
        ("POST", "/api/accounts"),        # Clientes.jsx (cambiar plan)
        ("GET", "/api/forecast"),         # Forecast.jsx (compartido con cto)
        ("GET", "/api/campaigns"),        # Campañas.jsx (incluye /campaigns/optimize)
        ("GET", "/api/marketing"),        # Campañas.jsx
        ("POST", "/api/marketing"),       # Campañas.jsx
        ("POST", "/api/campaigns"),       # Campañas.jsx (sync-leads)
        ("POST", "/api/pitch"),           # Vender.jsx (generate/send)
        ("GET", "/api/emails"),           # Vender.jsx
        ("GET", "/api/board"),            # Pipeline.jsx (compartido con cto)
        ("GET", "/api/leads"),            # Pipeline/LeadModal/CommandPalette
        ("POST", "/api/leads"),           # LeadModal (mover etapa, responder)
        ("GET", "/api/icp"),              # modal global "Buscar leads"
        ("POST", "/api/pipeline"),        # modal global "Buscar leads"
        # Finanzas — EXCLUSIVO de cro, "cto" no lo tiene. La ruta todavía no
        # existe en este archivo (GET /api/finance está en revisión, ver
        # workspace FINANZAS) — se deja lista acá de antemano para que, apenas
        # se mergee, Lucas no quede bloqueado por el fail-closed por defecto.
        ("GET", "/api/finance"),
    ),
    "cto": (
        ("GET", "/api/clients"),          # selector de cliente (global, App.jsx)
        ("GET", "/api/leads"),            # Leads.jsx / Pipeline / LeadModal
        ("POST", "/api/leads"),           # LeadModal (mover etapa, responder)
        ("GET", "/api/board"),            # Pipeline.jsx (compartido con cro)
        ("GET", "/api/forecast"),         # Forecast.jsx (compartido con cro)
        ("GET", "/api/kpis"),             # Dashboard.jsx (overview de leads/pipeline)
        ("GET", "/api/icp"),              # modal global "Buscar leads"
        ("POST", "/api/pipeline"),        # modal global "Buscar leads" (operar el pipeline)
    ),
}


def _role_may_access(role: str, method: str, path: str) -> bool:
    for m, prefix in _ROLE_ALLOWED.get(role, ()):
        if method == m and (path == prefix or path.startswith(prefix + "/")):
            return True
    return False


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """Login gate — dos mecanismos: JWT de Supabase Auth (Google, con rol en
    app_metadata) o el modelo local por-persona (users.json, fallback
    transicional, sin roles = admin). Sin ninguno de los dos configurados
    (ni users.json con cuentas, ni SUPABASE_JWT_SECRET) → abierto (dev)."""
    from zero.auth import auth_enabled, token_identity
    path = request.url.path
    needs = (
        auth_enabled() and path.startswith("/api")
        and path not in _OPEN_PATHS and not path.startswith("/api/webhooks/")
        and request.method != "OPTIONS"     # let CORS preflight through
    )
    if needs:
        token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        identity = token_identity(token)
        if identity is None:
            return JSONResponse({"detail": "no autorizado"}, status_code=401)
        role = identity.get("role")
        if role is None:
            return JSONResponse({"detail": "sin rol asignado"}, status_code=403)
        if role != "admin" and not _role_may_access(role, request.method, path):
            return JSONResponse({"detail": "sin permiso para este recurso"}, status_code=403)
        request.state.auth = identity
    return await call_next(request)


class Login(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: Login):
    from zero.auth import make_token, verify_password
    if not verify_password(body.username, body.password):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    token = make_token(body.username)
    if not token:   # carrera rarísima: el usuario se borró justo entremedio
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    return {"token": token}


@app.get("/api/auth/status")
def auth_status(request: Request):
    from zero.auth import auth_enabled, token_identity
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    enabled = auth_enabled()
    identity = token_identity(token) if token else None
    # "authenticated" refleja login de verdad, no también "tiene permiso para
    # todo" — un JWT válido sin rol asignado sigue contando como autenticado
    # acá (el 403 de fail-closed pasa en auth_guard, no en este status check).
    authenticated = (not enabled) or identity is not None
    return {"enabled": enabled, "authenticated": authenticated,
            "username": identity.get("username") if identity else None,
            "role": identity.get("role") if identity else None}


def _crm():
    return make_crm(CRM_PATH)   # Supabase if configured, else local crm.json


# The live app is the Vite dev server (one URL, hot-reload). Anyone landing on the
# API port gets redirected there so there's a single place to work and see changes.
APP_URL = os.environ.get("APP_URL", "http://localhost:5173")


@app.get("/")
def index():
    return RedirectResponse(APP_URL)


@app.get("/favicon.svg")
def favicon():
    return FileResponse("web/favicon.svg")


# --- read ---------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "service": "zero", "version": "0.1.0"}


@app.get("/api/clients")
def clients():
    return {"clients": _crm().client_ids()}


_PLANS = {k: {"segment": v["segment"], "price_clp": v.get("price_clp"),
              "leads_per_mo": v.get("leads_per_mo")} for k, v in TIERS.items()}


@app.get("/api/public/plans")
def public_plans():
    """Endpoint público (sin login, en _OPEN_PATHS) — la landing lo consume en
    vivo en vez de tener los planes hardcodeados. Reutiliza _PLANS tal cual:
    ese dict ya está filtrado a segment/price_clp/leads_per_mo, nunca MRR ni
    datos de clientes reales — eso lo sigue protegiendo el login en /api/accounts."""
    return {"plans": _PLANS}


@app.get("/api/accounts")
def accounts():
    """Clientes con su plan y precio + MRR de la agencia (lo que facturas al mes)."""
    memory = make_memory(STATE_PATH)
    out, mrr = [], 0
    for c in _crm().client_ids():
        tier = memory.clients.get(c, {}).get("tier") or "GROWTH"
        price = TIERS.get(tier, {}).get("price_clp")
        if price:
            mrr += price
        out.append({"client": c, "tier": tier, "price_clp": price,
                    "leads_per_mo": TIERS.get(tier, {}).get("leads_per_mo")})
    return {"accounts": out, "mrr_clp": mrr, "plans": _PLANS}


class PlanChange(BaseModel):
    tier: str


@app.post("/api/accounts/{client}/plan")
def set_plan(client: str, body: PlanChange):
    if body.tier not in TIERS:
        raise HTTPException(status_code=400, detail=f"plan inválido: {body.tier}")
    memory = make_memory(STATE_PATH)
    memory.register_client(client, body.tier)
    memory.save()
    return {"client": client, "tier": body.tier, "price_clp": TIERS[body.tier].get("price_clp")}


@app.get("/api/kpis")
def kpis(client: Optional[str] = None):
    counts = _crm().counts(client)           # one query · None = resumen de agencia
    won = counts.get("won", 0)
    return {
        "total": sum(counts.values()),
        "in_pipeline": sum(counts.get(s, 0) for s in CRM_OPEN_STAGES),
        "won": won,
        "pipeline_clp": won * AVG_DEAL_VALUE_CLP,
    }


@app.get("/api/board")
def board(client: str):
    crm = _crm()
    return {
        "client": client,
        "stages": [{"stage": s, "leads": crm.list(client, s)} for s in CRM_STAGES],
    }


_LEAD_GROUPS = {
    "todos": None,
    "activos": list(CRM_OPEN_STAGES),
    "ganados": ["won"],
    "perdidos": ["lost", "disqualified"],
}


@app.get("/api/leads")
def leads(client: str, group: str = "todos", limit: int = 50, offset: int = 0):
    crm = _crm()
    stages = _LEAD_GROUPS.get(group)
    rows = crm.query(client, stages=stages, limit=limit, offset=offset)
    counts = crm.counts(client)
    total = sum(counts.values()) if stages is None else sum(counts.get(s, 0) for s in stages)
    return {"leads": rows, "total": total, "limit": limit, "offset": offset}


@app.get("/api/leads/search")
def leads_search(q: str, limit: int = 20):
    """Busca un lead por company/email/phone en TODOS los clientes a la vez — el
    salto rápido cuando no se sabe de antemano en qué cuenta está (a diferencia
    de /api/leads, que siempre exige ?client=). Cada resultado ya trae su propio
    client_id (columna nativa del registro), no hace falta ningún wrapper extra."""
    if len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="query muy corta (mínimo 2 caracteres)")
    rows = _crm().search(q, limit=limit)
    return {"results": rows, "q": q, "limit": limit}


def _client_meta_cfg(client: str) -> dict:
    """Marketing config del cliente (Meta), con fallback de zonas al ICP."""
    memory = make_memory(STATE_PATH)
    cfg = dict(memory.get_client_meta(client))
    if not cfg.get("regions"):
        regions = memory.get_client_icp(client).get("regions")
        if regions:
            cfg["regions"] = regions
    return cfg


def _safe_campaigns(client: str, cfg: dict):
    """Trae campañas; si la API real de Meta falla, degrada a mock con el error —
    así la pestaña NUNCA se rompe por un token/cuenta inválidos."""
    from zero.metaads import MockMetaAds, make_metaads
    src = make_metaads(cfg)
    try:
        return src.campaigns(client, cfg), ("live" if getattr(src, "live", False) else "mock"), None
    except Exception as e:   # token inválido, cuenta sin acceso, red, etc.
        return MockMetaAds().campaigns(client, cfg), "mock", str(e)[:300]


@app.get("/api/campaigns")
def campaigns(client: str):
    """Campañas de Meta Ads del cliente, en CLP (mock si no hay credenciales de Meta)."""
    from zero.metaads import CHILE
    cfg = _client_meta_cfg(client)
    items, source, error = _safe_campaigns(client, cfg)
    spent = sum(c["spent_clp"] for c in items)
    leads = sum(c["leads"] for c in items)
    return {
        "client": client,
        "campaigns": items,
        "summary": {
            "spent_clp": spent, "leads": leads,
            "cpl_clp": round(spent / leads) if leads else 0,
            "active": sum(1 for c in items if c["status"] == "active"),
            "currency": "CLP", "good_cpl_clp": CHILE["good_cpl_clp"],
            "source": source, "error": error,
        },
    }


@app.post("/api/campaigns/sync-leads")
def sync_ad_leads(client: str):
    """Trae los leads de Meta Lead Ads y los mete al CRM (el 'producto único')."""
    from zero.metaads import make_metaads
    cfg = _client_meta_cfg(client)
    leads = make_metaads(cfg).lead_ads(client, cfg)
    crm = make_crm(CRM_PATH)
    memory = make_memory(STATE_PATH)
    zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
    return zero.import_ad_leads(client, leads)


@app.get("/api/metaads/accounts")
def metaads_accounts():
    """Prueba el token de Meta y lista las cuentas publicitarias que puede gestionar."""
    token = os.environ.get("META_ADS_TOKEN")
    if not token:
        raise HTTPException(status_code=400, detail="Configura primero el token de Meta Ads.")
    from zero.metaads import list_ad_accounts
    try:
        return {"accounts": list_ad_accounts(token)}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/campaigns/optimize")
def optimize_campaigns(client: str):
    """Claude gestiona: analiza las campañas del cliente y propone un plan (no gasta)."""
    from zero.metaads import CHILE
    cfg = _client_meta_cfg(client)
    items, _src, _err = _safe_campaigns(client, cfg)
    res, mode = _agent_op(lambda z: z.optimize_campaigns(client, items, good_cpl_clp=CHILE["good_cpl_clp"]))
    return {"recommendations": res.get("recommendations", []), "plan": res.get("plan", ""), "mode": mode}


class Marketing(BaseModel):
    ad_account: Optional[str] = None
    monthly_budget_clp: Optional[int] = None
    regions: Optional[list] = None
    objective: Optional[str] = None


@app.get("/api/marketing")
def get_marketing(client: str):
    return {"client": client, "config": make_memory(STATE_PATH).get_client_meta(client)}


@app.post("/api/marketing")
def set_marketing(client: str, body: Marketing):
    memory = make_memory(STATE_PATH)
    cfg = dict(memory.get_client_meta(client))
    cfg.update({k: v for k, v in body.dict().items() if v is not None})
    memory.set_client_meta(client, cfg)
    memory.save()
    return {"client": client, "config": cfg}


@app.get("/api/leads/{key}")
def lead(key: str, client: str):
    rec = _crm().get(client, key.lower())
    if rec is None:
        raise HTTPException(status_code=404, detail="lead no encontrado")
    return rec


# --- write --------------------------------------------------------------------
class StageMove(BaseModel):
    stage: str


@app.post("/api/leads/{key}/stage")
def move_stage(key: str, client: str, body: StageMove):
    crm = _crm()
    try:
        rec = crm.set_stage(client, key.lower(), body.stage, detail="api")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if rec is None:
        raise HTTPException(status_code=404, detail="lead no encontrado")
    crm.save()
    return rec


class Reply(BaseModel):
    text: Optional[str] = None
    channel: Optional[str] = None


@app.post("/api/leads/{key}/reply")
def register_reply(key: str, client: str, body: Reply):
    """A lead replied: close its follow-up sequence and move it to `replied`."""
    crm = make_crm(CRM_PATH)
    memory = make_memory(STATE_PATH)
    if crm.get(client, key.lower()) is None:
        raise HTTPException(status_code=404, detail="lead no encontrado")
    zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
    zero.register_reply(client, key.lower(), text=body.text, channel=body.channel)
    return crm.get(client, key.lower())


# --- WhatsApp conversational agent (CONCIERGE) -------------------------------
def _agents_best(source=None):
    """El mejor cerebro disponible: Anthropic (pago) → modelo local (gratis, Ollama) →
    mock. El local se activa con LOCAL_MODEL en el entorno (sin costo por token).
    Ignora valores vacíos/espacios (un env declarado pero sin valor NO activa 'live').
    `source` (discovery real) se pasa a los agentes en cualquiera de los tres modos."""
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if key:
        try:
            from zero.backends import AnthropicBackend
            return build_agents(backend=AnthropicBackend(api_key=key), mock=False, source=source), "live"
        except Exception:
            pass
    local = (os.environ.get("LOCAL_MODEL") or "").strip()
    if local:
        try:
            from zero.backends import LocalBackend
            url = os.environ.get("LOCAL_MODEL_URL", "http://localhost:11434/v1")
            return build_agents(backend=LocalBackend(model=local, base_url=url), mock=False,
                                source=source), "live"
        except Exception:
            pass
    return build_agents(mock=True, source=source), "mock"


def _discovery_source():
    """Discovery web real (DuckDuckGo, sin key) por defecto; DISCOVER=none vuelve
    al camino mock/LLM. Si la red falla, PROSPECTOR degrada a 'partial' sin crashear."""
    if (os.environ.get("DISCOVER") or "web").strip().lower() != "web":
        return None
    from zero.discovery import DuckDuckGoSource
    return DuckDuckGoSource()


def _nonempty(r) -> bool:
    """¿El agente devolvió algo útil? (string con texto, o dict con algún valor)."""
    if isinstance(r, str):
        return bool(r.strip())
    if isinstance(r, dict):
        return any(bool(v) for v in r.values())
    return r is not None


def _agent_op(fn, memory=None, crm=None):
    """Corre una operación de agente con el mejor cerebro; si el modelo 'live' falla
    en runtime (key inválida, modelo no disponible, Ollama inalcanzable) O devuelve
    vacío, reintenta en mock para que el agente SIEMPRE responda.
    fn(zero) -> result. Devuelve (result, mode)."""
    mem = memory if memory is not None else make_memory(STATE_PATH)
    agents, mode = _agents_best()
    try:
        res = fn(Zero(agents, memory=mem, crm=crm))
        if mode != "mock" and not _nonempty(res):
            raise RuntimeError("el modelo live devolvió vacío")
        return res, mode
    except Exception:
        if mode == "mock":
            raise   # ya era mock: el fallo es real, que lo vea quien llama
        return fn(Zero(build_agents(mock=True), memory=mem, crm=crm)), "mock"


@app.get("/api/whatsapp/status")
def whatsapp_status():
    """Prueba el token + phone_id de WhatsApp contra la Graph API real."""
    if not (os.environ.get("WHATSAPP_TOKEN") and os.environ.get("WHATSAPP_PHONE_ID")):
        raise HTTPException(status_code=400, detail="Configura primero WhatsApp en Configuración.")
    from zero.channels import whatsapp_status as _whatsapp_status
    try:
        return _whatsapp_status()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/webhooks/whatsapp")
def whatsapp_verify(mode: Optional[str] = Query(None, alias="hub.mode"),
                    token: Optional[str] = Query(None, alias="hub.verify_token"),
                    challenge: Optional[str] = Query(None, alias="hub.challenge")):
    """Meta webhook verification handshake — echoes the challenge if the token matches."""
    if mode == "subscribe" and token and token == os.environ.get("WHATSAPP_VERIFY_TOKEN"):
        return PlainTextResponse(challenge or "")
    raise HTTPException(status_code=403, detail="verificación fallida")


@app.post("/api/webhooks/whatsapp")
async def whatsapp_inbound(req: Request):
    """Receive inbound WhatsApp messages from Meta → match to lead → reply via CONCIERGE."""
    from zero.whatsapp_inbound import parse_inbound, verify_meta_signature
    raw = await req.body()
    if not verify_meta_signature(raw, req.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=403, detail="firma inválida — no viene de Meta")
    payload = json.loads(raw.decode("utf-8"))
    msgs = parse_inbound(payload)
    crm = make_crm(CRM_PATH)
    memory = make_memory(STATE_PATH)
    agents, _ = _agents_best()
    zero = Zero(agents, memory=memory, crm=crm, outbox=make_outbox())
    results = [zero.handle_inbound(m["from"], m["text"], to_phone_id=m.get("to_phone_id"))
               for m in msgs]
    return {"received": len(msgs), "results": results}


class Simulate(BaseModel):
    message: str
    client: Optional[str] = None
    lead: Optional[dict] = None
    # Transcripción del chat de prueba (turnos previos, [{"role","text"}]) — la
    # mantiene el frontend; el servidor no guarda nada de un ensayo.
    history: Optional[list] = None
    vendor_id: Optional[str] = None   # probar una personalidad sin asignarla


@app.post("/api/whatsapp/simulate")
def whatsapp_simulate(body: Simulate):
    """Try the agent without WhatsApp: draft (don't send) a reply to a message, to
    evaluate how it answers business questions. Uses the client's saved ICP,
    knowledge base and the passed-in chat history."""
    memory = make_memory(STATE_PATH)
    vendor = memory.get_vendor(body.vendor_id) if body.vendor_id else None
    try:
        res, mode = _agent_op(
            lambda z: z.converse_result(body.client or "", body.message,
                                        lead=body.lead or {},
                                        history=body.history, vendor=vendor),
            memory=memory,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"el agente falló: {e}")
    # `quote` viene solo si el mensaje pidió precios de ítems del catálogo: el
    # presupuesto se calculó en código (zero/quotes.py), no lo inventó el modelo.
    return {"reply": res.get("reply") or "", "mode": mode,
            "quote": res.get("quote")}


class RunRequest(BaseModel):
    client: str
    query: str
    tier: str = "GROWTH"
    count: int = 8
    icp: Optional[dict] = None   # perfil del cliente ideal (adaptación por cliente)


@app.post("/api/pipeline")
def run_pipeline(req: RunRequest):
    crm = make_crm(CRM_PATH)
    memory = make_memory(STATE_PATH)
    memory.register_client(req.client, req.tier)
    # El mejor cerebro disponible + discovery web real. Sin fallback silencioso a
    # mock: una entrega con leads inventados sería mentirle al cliente — si el
    # motor real falla a mitad de pipeline, el resultado lo dice ({"error": etapa}).
    agents, mode = _agents_best(source=_discovery_source())
    zero = Zero(agents, memory=memory, crm=crm, outbox=make_outbox())
    try:
        out = zero.run_pipeline(req.client, req.tier, req.query, count=req.count, icp=req.icp)
    except ValueError as e:   # e.g. unknown tier
        raise HTTPException(status_code=400, detail=str(e))
    out["mode"] = mode
    return out


# --- sales pitch (offer the service by email, demo included) ------------------
class PitchCompose(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None


@app.post("/api/pitch/compose")
def pitch_compose(body: PitchCompose):
    """Generate an editable sales pitch (subject + body) with a demo sample."""
    from zero.sales import compose_pitch
    return compose_pitch(name=body.name, company=body.company)


class PitchGen(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    notes: Optional[str] = None


@app.post("/api/pitch/generate")
def pitch_generate(body: PitchGen):
    """Genera un pitch con IA (creativo, distinto cada vez). Mock varía; con modelo
    (Anthropic o local) es de verdad creativo."""
    res, mode = _agent_op(lambda z: z.write_pitch({"name": body.name, "company": body.company}, body.notes or ""))
    return {"subject": res.get("subject", ""), "body": res.get("body", ""), "mode": mode}


class PitchSend(BaseModel):
    to: str
    subject: str
    body: str


@app.post("/api/pitch/send")
def pitch_send(body: PitchSend):
    """Send the (possibly edited) pitch to a prospect via SMTP."""
    if not os.environ.get("SMTP_HOST"):
        raise HTTPException(status_code=400, detail="Configura primero el SMTP en Configuración → Email.")
    from zero.channels import EmailSender
    try:
        res = EmailSender().send({"channel": "email", "to": body.to.strip(),
                                  "subject": body.subject, "body": body.body})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SMTP falló: {e}")
    if res["status"] != "sent":
        raise HTTPException(status_code=400, detail=res.get("error") or "no se pudo enviar")
    memory = make_memory(STATE_PATH)          # recuerda el correo para autocompletar después
    memory.add_used_email(body.to)
    memory.save()
    return res


@app.get("/api/emails")
def used_emails():
    """Correos ya contactados — para sugerir/autocompletar al escribir."""
    return {"emails": sorted(make_memory(STATE_PATH).used_emails)}


class TestEmail(BaseModel):
    to: str


@app.post("/api/test-email")
def test_email(body: TestEmail):
    """Send one real test email so you can verify SMTP against your own inbox.

    Works regardless of OUTBOX_LIVE (it's a deliberate test), but needs SMTP set.
    """
    if not os.environ.get("SMTP_HOST"):
        raise HTTPException(status_code=400, detail="Configura primero el SMTP (host, usuario, contraseña).")
    from zero.channels import EmailSender
    try:
        res = EmailSender().send({
            "channel": "email", "to": body.to.strip(),
            "subject": "Prueba de ZeroAI ✅",
            "body": "Si lees esto, tu envío por email quedó funcionando. — ZeroAI",
        })
    except Exception as e:   # SMTP auth/connection errors → readable message
        raise HTTPException(status_code=400, detail=f"SMTP falló: {e}")
    if res["status"] != "sent":
        raise HTTPException(status_code=400, detail=res.get("error") or "no se pudo enviar")
    return res


@app.get("/api/icp")
def get_icp(client: str):
    """The client's saved ICP, so the dashboard can show and edit it (not write-only)."""
    memory = make_memory(STATE_PATH)
    return {"client": client, "icp": normalize_icp(memory.get_client_icp(client))}


class IcpBody(BaseModel):
    icp: dict


@app.post("/api/icp")
def set_icp(client: str, body: IcpBody):
    """Guardar el ICP desde el dashboard sin tener que correr un pipeline."""
    memory = make_memory(STATE_PATH)
    memory.set_client_icp(client, normalize_icp(body.icp))
    memory.save()
    return {"client": client, "icp": memory.get_client_icp(client)}


# --- agentes WhatsApp (vendedores) + base de conocimiento ----------------------
# El backend de la sección "Agentes" del dashboard: elegir/crear una personalidad,
# asignarla a un cliente (el "deploy") y cargarle la ficha de la empresa.

@app.get("/api/vendors")
def list_vendors():
    """Catálogo de personalidades (Fernanda, Stéfano, ...), con cuántos clientes
    tiene asignados cada una (clients_count) — presentación, no cambia el
    registro guardado."""
    memory = make_memory(STATE_PATH)
    vendors = [dict(v, clients_count=clients_count_for(v["id"], memory))
              for v in memory.list_vendors()]
    return {"vendors": vendors, "default": DEFAULT_VENDOR_ID}


class VendorBody(BaseModel):
    id: Optional[str] = None      # si falta, se deriva del nombre
    name: str
    tone: Optional[str] = None
    photo: Optional[str] = None
    phone: Optional[str] = None
    whatsapp_phone_id: Optional[str] = None


@app.post("/api/vendors")
def upsert_vendor(body: VendorBody):
    """Crear o editar una personalidad. Solo pisa los campos enviados."""
    memory = make_memory(STATE_PATH)
    vid = "".join(ch for ch in (body.id or body.name).strip().lower() if ch.isalnum())
    if not vid:
        raise HTTPException(status_code=400, detail="el vendedor necesita un nombre")
    vendor = dict(memory.get_vendor(vid) or {})
    vendor["id"] = vid
    for field in ("name", "tone", "photo", "phone", "whatsapp_phone_id"):
        value = getattr(body, field)
        if value is not None:
            vendor[field] = value
    memory.upsert_vendor(vendor)
    memory.save()
    return {"vendor": vendor}


@app.get("/api/vendor")
def client_vendor(client: str):
    """El vendedor asignado a este cliente (o el por defecto)."""
    memory = make_memory(STATE_PATH)
    vid = memory.get_client_vendor(client)
    return {"client": client, "vendor": memory.get_vendor(vid) or {}}


class AssignVendor(BaseModel):
    vendor_id: str


@app.post("/api/vendor")
def assign_vendor(client: str, body: AssignVendor):
    """El "deploy": desde ahora este cliente es atendido por esa personalidad."""
    memory = make_memory(STATE_PATH)
    vendor = memory.get_vendor(body.vendor_id.strip().lower())
    if not vendor:
        raise HTTPException(status_code=404, detail="ese vendedor no existe")
    memory.set_client_vendor(client, vendor["id"])
    memory.save()
    return {"client": client, "vendor": vendor}


@app.get("/api/knowledge")
def get_knowledge(client: str):
    """La ficha de la empresa (texto libre) que alimenta al agente."""
    memory = make_memory(STATE_PATH)
    return {"client": client, "knowledge": memory.get_client_knowledge(client)}


class KnowledgeBody(BaseModel):
    knowledge: str


@app.post("/api/knowledge")
def set_knowledge(client: str, body: KnowledgeBody):
    """Guardar la ficha: qué vende, precios, horarios, tono, políticas... Un
    trabajador la pega tal cual; no necesita saber de IA."""
    memory = make_memory(STATE_PATH)
    memory.set_client_knowledge(client, body.knowledge)
    memory.save()
    return {"client": client, "saved": True, "chars": len(memory.get_client_knowledge(client))}


# --- lista de precios + presupuestos (la aritmética vive en zero/quotes.py) ----

@app.get("/api/pricing")
def get_pricing(client: str):
    """La lista de precios estructurada del cliente (ítems con precio unitario)."""
    memory = make_memory(STATE_PATH)
    return {"client": client, "pricing": normalize_pricing(memory.get_client_pricing(client))}


class PricingBody(BaseModel):
    pricing: dict


@app.post("/api/pricing")
def set_pricing(client: str, body: PricingBody):
    """Guardar la lista de precios. Se normaliza al entrar (ítems sin nombre o sin
    precio > 0 se descartan) — así los presupuestos nunca cotizan basura."""
    memory = make_memory(STATE_PATH)
    pricing = normalize_pricing(body.pricing)
    memory.set_client_pricing(client, pricing)
    memory.save()
    return {"client": client, "saved": True, "pricing": pricing}


class QuoteBody(BaseModel):
    client: str
    items: list   # [{"id": "sitio-web", "qty": 2}]


@app.post("/api/quote")
def make_quote(body: QuoteBody):
    """Cotizador directo (sin conversación): calcula el presupuesto determinista
    para los ítems pedidos, contra la lista de precios del cliente."""
    memory = make_memory(STATE_PATH)
    pricing = normalize_pricing(memory.get_client_pricing(body.client))
    quote = compute_quote(pricing, body.items)
    if quote is None:
        raise HTTPException(status_code=404,
                            detail="ningún ítem pedido está en la lista de precios del cliente")
    return {"client": body.client, "quote": quote, "text": format_quote(quote)}


@app.get("/api/conversation")
def conversation(client: str, lead: str, limit: int = 50):
    """El hilo del diálogo con un lead, para verlo en el dashboard."""
    memory = make_memory(STATE_PATH)
    return {"client": client, "lead": lead.strip().lower(),
            "turns": memory.get_conversation(client, lead.strip(), limit=limit)}


@app.get("/api/forecast")
def forecast(client: str):
    crm = make_crm(CRM_PATH)
    memory = make_memory(STATE_PATH)
    tier = memory.clients.get(client, {}).get("tier", "GROWTH")
    memory.register_client(client, tier)
    # ANALYST solo propone tasas (la aritmética es determinista) — con fallback a
    # mock está bien: nunca inventa datos, solo comenta.
    res, mode = _agent_op(lambda z: z.forecast(client), memory=memory, crm=crm)
    res["mode"] = mode
    return res


# --- config (secrets stored in .env, set once from the dashboard) -------------
@app.get("/api/config")
def get_config():
    """Report which keys are configured — never returns the secret itself."""
    # El motor que corre AHORA de verdad — no inferido de las keys presentes
    # (que puede mentir: una key puede estar seteada y la construcción del
    # backend fallar igual, ej. falta `pip install anthropic`), sino la misma
    # función que decide el backend en cada request real (_agents_best).
    _, engine_mode = _agents_best()
    engine = None
    if engine_mode == "live":
        engine = "anthropic" if (os.environ.get("ANTHROPIC_API_KEY") or "").strip() else "local"
    return {
        "engine_mode": engine_mode,   # "live" | "mock"
        "engine": engine,             # "anthropic" | "local" | None (None si mock)
        "elevenlabs": bool(os.environ.get("ELEVENLABS_API_KEY")),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        # cerebro local (Ollama/vLLM) — gratis; activo si hay un nombre de modelo
        "local_model": (os.environ.get("LOCAL_MODEL") or "").strip() or None,
        # discovery de leads: web real (DuckDuckGo) por defecto, o mock/LLM
        "discover": (os.environ.get("DISCOVER") or "web").strip().lower(),
        # con la API key ya lista agentes y números; assistant/phone son opcionales
        "vapi": bool(os.environ.get("VAPI_API_KEY")),
        "supabase": bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")),
        "email": bool(os.environ.get("SMTP_HOST")),
        "whatsapp": bool(os.environ.get("WHATSAPP_TOKEN") and os.environ.get("WHATSAPP_PHONE_ID")),
        # whether drafted messages are actually sent (vs mock-recorded)
        "outbox_live": os.environ.get("OUTBOX_LIVE") == "1",
        "auth": bool(os.environ.get("AUTH_PASSWORD")),
        "metaads": bool(os.environ.get("META_ADS_TOKEN") and os.environ.get("META_AD_ACCOUNT_ID")),
        # nombres de los secretos respaldados en la nube (sobreviven a redeploys)
        "backed_up": backed_up_keys(),
    }


class ConfigBody(BaseModel):
    elevenlabs_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    local_model: Optional[str] = None
    local_model_url: Optional[str] = None
    discover: Optional[str] = None   # "web" | "none"
    vapi_api_key: Optional[str] = None
    vapi_assistant_id: Optional[str] = None
    vapi_phone_number_id: Optional[str] = None
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[str] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    smtp_from: Optional[str] = None
    whatsapp_token: Optional[str] = None
    whatsapp_phone_id: Optional[str] = None
    whatsapp_verify_token: Optional[str] = None
    whatsapp_app_secret: Optional[str] = None
    auth_password: Optional[str] = None
    meta_ads_token: Optional[str] = None
    meta_ad_account_id: Optional[str] = None
    outbox_live: Optional[bool] = None


@app.post("/api/config")
def set_config(body: ConfigBody):
    saved = []
    fields = {
        "ELEVENLABS_API_KEY": body.elevenlabs_api_key,
        "ANTHROPIC_API_KEY": body.anthropic_api_key,
        "LOCAL_MODEL": body.local_model,
        "LOCAL_MODEL_URL": body.local_model_url,
        "DISCOVER": body.discover,
        "VAPI_API_KEY": body.vapi_api_key,
        "VAPI_ASSISTANT_ID": body.vapi_assistant_id,
        "VAPI_PHONE_NUMBER_ID": body.vapi_phone_number_id,
        "SUPABASE_URL": body.supabase_url,
        "SUPABASE_KEY": body.supabase_key,
        "SMTP_HOST": body.smtp_host,
        "SMTP_PORT": body.smtp_port,
        "SMTP_USER": body.smtp_user,
        "SMTP_PASS": body.smtp_pass,
        "SMTP_FROM": body.smtp_from,
        "WHATSAPP_TOKEN": body.whatsapp_token,
        "WHATSAPP_PHONE_ID": body.whatsapp_phone_id,
        "WHATSAPP_VERIFY_TOKEN": body.whatsapp_verify_token,
        "WHATSAPP_APP_SECRET": body.whatsapp_app_secret,
        "AUTH_PASSWORD": body.auth_password,
        "META_ADS_TOKEN": body.meta_ads_token,
        "META_AD_ACCOUNT_ID": body.meta_ad_account_id,
    }
    # Dos pasadas: primero set_env() de TODO (así os.environ queda completo),
    # después save_secret() de TODO. Si se pasan SUPABASE_URL y SUPABASE_KEY
    # juntos (conectar Supabase por primera vez), save_secret(SUPABASE_URL, ...)
    # necesita que SUPABASE_KEY ya esté en os.environ para autenticar contra
    # Supabase — con una sola pasada en orden de dict, SUPABASE_URL se procesa
    # antes y su backup a la nube fallaba en silencio.
    to_save = []
    if body.outbox_live is not None:   # explicit on/off toggle for real sending
        val = "1" if body.outbox_live else "0"
        set_env("OUTBOX_LIVE", val)
        to_save.append(("OUTBOX_LIVE", val))
    for env_key, value in fields.items():
        if value:
            value = value.strip()
            set_env(env_key, value)
            to_save.append((env_key, value))

    cloud_ok = True   # ¿quedó todo respaldado en la nube? (para avisar si no)
    for env_key, value in to_save:
        cloud_ok &= save_secret(env_key, value)
        saved.append(env_key)
    # backed_up=True → sobrevive redeploys; si Supabase no está, queda solo en este server
    return {"ok": True, "saved": saved, "backed_up": bool(cloud_ok and saved)}


@app.get("/api/assistants")
def assistants():
    from zero.calls import list_assistants
    try:
        return {"assistants": list_assistants()}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/vapi/numbers")
def vapi_numbers():
    from zero.calls import list_phone_numbers
    try:
        return {"numbers": list_phone_numbers()}
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))


class CallBody(BaseModel):
    number: str
    name: Optional[str] = None
    assistant_id: Optional[str] = None
    phone_number_id: Optional[str] = None


@app.post("/api/call")
def call(body: CallBody):
    from zero.calls import place_call
    try:
        return place_call(body.number.strip(), body.name, body.assistant_id, body.phone_number_id)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
