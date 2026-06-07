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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from zero._env import load_env, set_env
from zero.agents import build_agents

load_env()   # load secrets from .env (ELEVENLABS_API_KEY, ANTHROPIC_API_KEY, …)
from zero.config import AVG_DEAL_VALUE_USD, CRM_OPEN_STAGES, CRM_STAGES
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


@app.get("/")
def index():
    return FileResponse("web/index.html")   # the dashboard frontend (talks to /api/*)


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
    zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
    try:
        return zero.run_pipeline(req.client, req.tier, req.query, count=req.count, icp=req.icp)
    except ValueError as e:   # e.g. unknown tier
        raise HTTPException(status_code=400, detail=str(e))


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
    }


class ConfigBody(BaseModel):
    elevenlabs_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    vapi_api_key: Optional[str] = None
    vapi_assistant_id: Optional[str] = None
    vapi_phone_number_id: Optional[str] = None
    supabase_url: Optional[str] = None
    supabase_key: Optional[str] = None


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
    }
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
