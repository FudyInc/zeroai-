"""Parse + verify inbound WhatsApp webhooks from Twilio (plan B vía BSP).

Espejo de `whatsapp_inbound.py` (Meta): puro y stdlib-only para poder probarlo
offline con un payload capturado — el endpoint HTTP queda como una cáscara
delgada. A diferencia de Meta (JSON firmado con HMAC-SHA256 del body), Twilio
manda `application/x-www-form-urlencoded` (From, To, Body, MessageSid, ...) y
firma con HMAC-SHA1 sobre la URL completa + los parámetros ordenados.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Any, Dict, List, Optional


def verify_twilio_signature(url: str, params: Dict[str, str],
                            signature_header: Optional[str],
                            auth_token: Optional[str] = None) -> bool:
    """True only if the request is signed with TWILIO_AUTH_TOKEN following
    Twilio's scheme: base64(HMAC-SHA1(token, url + params sorted by key, each
    key immediately followed by its value)) — the value Twilio sends in the
    `X-Twilio-Signature` header on every webhook call.

    Mismo criterio que `verify_meta_signature`: sin token configurado, sin
    header, o una firma que no cuadra — todos devuelven False y el caller
    rechaza con 403 sin procesar nada. Sin esto, cualquiera que encuentre la
    URL puede inyectar "mensajes de leads" y (con OUTBOX_LIVE=1) gatillar
    respuestas reales con texto controlado por el atacante. `compare_digest`
    evita el timing attack de comparar byte a byte.

    OJO: `url` debe ser la URL PÚBLICA exacta que Twilio llamó — con proxy o
    túnel delante, la URL que ve el server difiere y la firma nunca cuadra;
    en ese caso se fija con TWILIO_WEBHOOK_URL (ver el endpoint en api.py)."""
    token = auth_token or os.environ.get("TWILIO_AUTH_TOKEN")
    if not token or not signature_header:
        return False
    signed = url + "".join(k + v for k, v in sorted(params.items()))
    expected = base64.b64encode(
        hmac.new(token.encode("utf-8"), signed.encode("utf-8"), hashlib.sha1).digest()
    ).decode("ascii")
    return hmac.compare_digest(expected, signature_header)


def parse_inbound(params: Dict[str, Any]) -> List[Dict[str, str]]:
    """Flatten a Twilio webhook form to [{"from": <dígitos>, "text": <body>,
    "to": <dígitos>}] — same shape the Meta parser produces, minus `to_phone_id`
    (Twilio no tiene phone_ids de Meta; el número receptor va en `to`).

    Twilio manda UN mensaje por request. Un mensaje sin texto pero con adjuntos
    (NumMedia > 0) se registra como "[media]" para que el loop igual sepa que el
    lead respondió. Payload malformado → [] (nunca levanta)."""
    if not isinstance(params, dict):
        return []
    frm = "".join(ch for ch in str(params.get("From") or "") if ch.isdigit())
    if not frm:
        return []
    text = str(params.get("Body") or "").strip()
    if not text:
        try:
            n_media = int(params.get("NumMedia") or 0)
        except (TypeError, ValueError):
            n_media = 0
        text = "[media]" if n_media > 0 else "[mensaje]"
    to = "".join(ch for ch in str(params.get("To") or "") if ch.isdigit())
    return [{"from": frm, "text": text, "to": to}]
