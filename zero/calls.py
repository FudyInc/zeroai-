"""Outbound phone calls via Vapi — place a call with the Fernanda assistant.

Uses the system `curl` rather than urllib on purpose: Cloudflare (in front of Vapi)
intermittently blocks Python's TLS signature with a 403 / error 1010, while curl
passes reliably. Thin boundary; needs three values set from the dashboard's
Configuración (they land in .env):
  VAPI_API_KEY · VAPI_ASSISTANT_ID · VAPI_PHONE_NUMBER_ID
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict, Optional

from ._env import load_env

load_env()

_BASE = "https://api.vapi.ai"
_URL = f"{_BASE}/call"


def _curl(method: str, path: str, body: Optional[str] = None) -> Any:
    """Call the Vapi API via system curl (Cloudflare-resilient). Returns parsed JSON."""
    key = os.environ.get("VAPI_API_KEY")
    if not key:
        raise RuntimeError("Falta configurar la VAPI_API_KEY en el dashboard")
    if not shutil.which("curl"):
        raise RuntimeError("curl no está disponible en el sistema")
    args = ["curl", "-sS", "-X", method, f"{_BASE}/{path}",
            "-H", f"Authorization: Bearer {key}", "-w", "\n%{http_code}"]
    if body is not None:
        args += ["-H", "Content-Type: application/json", "--data-binary", body]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=40)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Vapi no respondió a tiempo")
    text = proc.stdout or ""
    payload_text, status = (text.rsplit("\n", 1) + [""])[:2] if "\n" in text else (text, "")
    status = status.strip()
    try:
        data: Any = json.loads(payload_text) if payload_text.strip() else None
    except Exception:
        data = {"raw": payload_text}
    if status not in ("200", "201"):
        msg = (data.get("message") if isinstance(data, dict) else None) or payload_text or proc.stderr or f"HTTP {status}"
        raise RuntimeError(f"Vapi {status}: {msg}")
    return data


def list_assistants() -> list:
    """Your Vapi assistants → [{id, name}]."""
    data = _curl("GET", "assistant") or []
    # Defensivo: si Vapi alguna vez envuelve la lista en un objeto (ej. un
    # cambio de API, un error 200 con otra forma), no reventar con
    # AttributeError iterando strings/keys de un dict — tratarlo como vacío.
    if not isinstance(data, list):
        return []
    return [{"id": a.get("id"), "name": a.get("name") or "(sin nombre)"}
            for a in data if isinstance(a, dict)]


def list_phone_numbers() -> list:
    """Your Vapi phone numbers → [{id, number}]."""
    data = _curl("GET", "phone-number") or []
    if not isinstance(data, list):
        return []
    return [{"id": n.get("id"), "number": n.get("number") or n.get("name") or n.get("id")}
            for n in data if isinstance(n, dict)]


# Contexto del lead que se inyecta al prompt del asistente en Vapi
# (assistantOverrides.variableValues). Cada par es (variable en Vapi, campo del CRM).
# Deliberadamente corto: lo que entra acá termina dentro del prompt de un tercero,
# así que NO se agregan email, teléfonos alternativos ni notas internas.
_LEAD_VARIABLES = (
    ("empresa", "company"),
    ("rubro", "activity"),
    ("etapa", "stage"),
    ("origen", "source"),
)


def _lead_variables(lead: Optional[Dict[str, Any]]) -> Dict[str, str]:
    """Map a CRM lead dict to Vapi variableValues, dropping anything empty.

    Un valor ausente se omite en vez de mandarse vacío: una variable con None
    adentro se la lee el asistente en voz alta ("...de la empresa None").
    """
    out: Dict[str, str] = {}
    if not isinstance(lead, dict):
        return out
    for variable, field in _LEAD_VARIABLES:
        value = lead.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out[variable] = text
    return out


def place_call(number: str, name: Optional[str] = None,
               assistant_id: Optional[str] = None, phone_number_id: Optional[str] = None,
               lead: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Start an outbound call. Agent/number can be chosen per call, else env defaults.

    `lead` es opcional: un registro del CRM para que el asistente sepa a quién
    llama. Si no viene (ej. una llamada manual desde el dashboard, que no tiene
    lead), el cuerpo enviado es exactamente el de siempre.

    Las variables que se inyectan vía assistantOverrides.variableValues, y que el
    prompt del asistente en el panel de Vapi debe referenciar con estos nombres
    exactos (dobles llaves):

        {{empresa}}   ← lead["company"]    nombre de la empresa
        {{rubro}}     ← lead["activity"]   a qué se dedica
        {{etapa}}     ← lead["stage"]      etapa del CRM
        {{origen}}    ← lead["source"]     de dónde salió el lead

    Una variable sin valor no se envía, así que el prompt en Vapi debe tolerar
    que falte (redáctalo de modo que la frase siga en pie sin ella)."""
    number = (number or "").strip()
    key = os.environ.get("VAPI_API_KEY")
    assistant = assistant_id or os.environ.get("VAPI_ASSISTANT_ID")
    phone_id = phone_number_id or os.environ.get("VAPI_PHONE_NUMBER_ID")
    missing = [n for n, v in (("VAPI_API_KEY", key),
                              ("número a llamar", number),
                              ("agente", assistant),
                              ("número de origen", phone_id)) if not v]
    if missing:
        raise RuntimeError("Falta: " + ", ".join(missing))
    if not shutil.which("curl"):
        raise RuntimeError("curl no está disponible en el sistema")

    customer: Dict[str, Any] = {"number": number}
    if name:
        customer["name"] = name
    payload: Dict[str, Any] = {"assistantId": assistant, "phoneNumberId": phone_id,
                               "customer": customer}
    variables = _lead_variables(lead)
    if variables:
        payload["assistantOverrides"] = {"variableValues": variables}
    body = json.dumps(payload)

    try:
        proc = subprocess.run(
            ["curl", "-sS", "-X", "POST", _URL,
             "-H", f"Authorization: Bearer {key}",
             "-H", "Content-Type: application/json",
             "--data-binary", body, "-w", "\n%{http_code}"],
            capture_output=True, text=True, timeout=40,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Vapi no respondió a tiempo")

    text = proc.stdout or ""
    payload_text, status = (text.rsplit("\n", 1) + [""])[:2] if "\n" in text else (text, "")
    status = status.strip()
    try:
        data: Any = json.loads(payload_text) if payload_text.strip() else {}
    except Exception:
        data = {"raw": payload_text}

    if status not in ("200", "201"):
        msg = (data.get("message") if isinstance(data, dict) else None) or payload_text or proc.stderr or f"HTTP {status}"
        raise RuntimeError(f"Vapi {status}: {msg}")
    return data if isinstance(data, dict) else {"result": data}
