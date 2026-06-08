"""HTTP API for ZERO — exposes the pipeline + CRM over JSON (FastAPI).

The foundation a web frontend plugs into. It reuses the exact same core the CLI
uses (orchestrator, CRM, agents) — the API is just a thin HTTP layer, no business
logic of its own. Mock backend by default. Run:

    uvicorn api:app --reload --port 8800

Then the frontend (or http://localhost:8800/docs) talks to it.
"""
from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel

from zero._env import load_env, set_env
from zero.agents import build_agents

load_env()   # load secrets from .env (ELEVENLABS_API_KEY, ANTHROPIC_API_KEY, …)
from zero.config import AVG_DEAL_VALUE_USD, CRM_OPEN_STAGES, CRM_STAGES
from zero.channels import make_outbox
from zero.icp import normalize_icp
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.store import make_crm

CRM_PATH = "crm.json"
STATE_PATH = "state.json"

app = FastAPI(title="ZERO API", version="0.1.0",
              description="Lead-gen B2B — pipeline y CRM por HTTP")

# Open CORS so a frontend on another port (Vite, etc.) can call it during dev.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


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
    crm = _crm()
    return {"clients": sorted({r["client_id"] for r in crm.leads.values()})}


@app.get("/api/kpis")
def kpis(client: Optional[str] = None):
    leads = [r for r in _crm().leads.values() if client is None or r["client_id"] == client]
    won = sum(1 for r in leads if r["stage"] == "won")
    return {
        "total": len(leads),
        "in_pipeline": sum(1 for r in leads if r["stage"] in CRM_OPEN_STAGES),
        "won": won,
        "pipeline_usd": won * AVG_DEAL_VALUE_USD,
    }


@app.get("/api/board")
def board(client: str):
    crm = _crm()
    return {
        "client": client,
        "stages": [{"stage": s, "leads": crm.list(client, s)} for s in CRM_STAGES],
    }


@app.get("/api/leads")
def leads(client: str, stage: Optional[str] = None):
    return {"leads": _crm().list(client, stage)}


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
    memory = SessionMemory(STATE_PATH)
    if crm.get(client, key.lower()) is None:
        raise HTTPException(status_code=404, detail="lead no encontrado")
    zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
    zero.register_reply(client, key.lower(), text=body.text, channel=body.channel)
    return crm.get(client, key.lower())


# --- WhatsApp conversational agent (CONCIERGE) -------------------------------
def _agents_best():
    """Live Anthropic backend if a key is set (real agent reactions), else mock."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            from zero.backends import AnthropicBackend
            return build_agents(backend=AnthropicBackend(api_key=key), mock=False), "live"
        except Exception:
            pass
    return build_agents(mock=True), "mock"


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
    from zero.whatsapp_inbound import parse_inbound
    payload = await req.json()
    msgs = parse_inbound(payload)
    crm = make_crm(CRM_PATH)
    memory = SessionMemory(STATE_PATH)
    agents, _ = _agents_best()
    zero = Zero(agents, memory=memory, crm=crm, outbox=make_outbox())
    results = [zero.handle_inbound(m["from"], m["text"]) for m in msgs]
    return {"received": len(msgs), "results": results}


class Simulate(BaseModel):
    message: str
    client: Optional[str] = None
    lead: Optional[dict] = None


@app.post("/api/whatsapp/simulate")
def whatsapp_simulate(body: Simulate):
    """Try the agent without WhatsApp: draft (don't send) a reply to a message, to
    evaluate how it answers business questions. Uses the client's saved ICP."""
    memory = SessionMemory(STATE_PATH)
    agents, mode = _agents_best()
    zero = Zero(agents, memory=memory)
    try:
        reply = zero.converse(body.client or "", body.message, lead=body.lead or {})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"el agente falló: {e}")
    return {"reply": reply, "mode": mode}


class RunRequest(BaseModel):
    client: str
    query: str
    tier: str = "GROWTH"
    count: int = 8
    icp: Optional[dict] = None   # perfil del cliente ideal (adaptación por cliente)


@app.post("/api/pipeline")
def run_pipeline(req: RunRequest):
    crm = make_crm(CRM_PATH)
    memory = SessionMemory(STATE_PATH)
    memory.register_client(req.client, req.tier)
    zero = Zero(build_agents(mock=True), memory=memory, crm=crm, outbox=make_outbox())
    try:
        return zero.run_pipeline(req.client, req.tier, req.query, count=req.count, icp=req.icp)
    except ValueError as e:   # e.g. unknown tier
        raise HTTPException(status_code=400, detail=str(e))


# --- sales pitch (offer the service by email, demo included) ------------------
class PitchCompose(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None


@app.post("/api/pitch/compose")
def pitch_compose(body: PitchCompose):
    """Generate an editable sales pitch (subject + body) with a demo sample."""
    from zero.sales import compose_pitch
    return compose_pitch(name=body.name, company=body.company)


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
    return res


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
    memory = SessionMemory(STATE_PATH)
    return {"client": client, "icp": normalize_icp(memory.get_client_icp(client))}


@app.get("/api/forecast")
def forecast(client: str):
    crm = make_crm(CRM_PATH)
    memory = SessionMemory(STATE_PATH)
    tier = memory.clients.get(client, {}).get("tier", "GROWTH")
    memory.register_client(client, tier)
    zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
    return zero.forecast(client)


# --- config (secrets stored in .env, set once from the dashboard) -------------
@app.get("/api/config")
def get_config():
    """Report which keys are configured — never returns the secret itself."""
    return {
        "elevenlabs": bool(os.environ.get("ELEVENLABS_API_KEY")),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "vapi": all(os.environ.get(k) for k in
                    ("VAPI_API_KEY", "VAPI_ASSISTANT_ID", "VAPI_PHONE_NUMBER_ID")),
        "supabase": bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY")),
        "email": bool(os.environ.get("SMTP_HOST")),
        "whatsapp": bool(os.environ.get("WHATSAPP_TOKEN") and os.environ.get("WHATSAPP_PHONE_ID")),
        # whether drafted messages are actually sent (vs mock-recorded)
        "outbox_live": os.environ.get("OUTBOX_LIVE") == "1",
    }


class ConfigBody(BaseModel):
    elevenlabs_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
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
    outbox_live: Optional[bool] = None


@app.post("/api/config")
def set_config(body: ConfigBody):
    saved = []
    fields = {
        "ELEVENLABS_API_KEY": body.elevenlabs_api_key,
        "ANTHROPIC_API_KEY": body.anthropic_api_key,
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
    }
    if body.outbox_live is not None:   # explicit on/off toggle for real sending
        set_env("OUTBOX_LIVE", "1" if body.outbox_live else "0")
        saved.append("OUTBOX_LIVE")
    for env_key, value in fields.items():
        if value:
            set_env(env_key, value.strip())
            saved.append(env_key)
    return {"ok": True, "saved": saved}


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
