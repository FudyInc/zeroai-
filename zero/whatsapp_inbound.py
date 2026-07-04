"""Parse inbound WhatsApp webhooks (Meta Cloud API) into a simple message list.

Pure and stdlib-only so it's testable offline with a captured payload — the
webhook endpoint stays a thin shell around this. The actual receiving needs a
public URL (Meta calls it), which is the external piece; this logic is not.
"""
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any, Dict, List, Optional


def verify_meta_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """True only if `raw_body` is signed by WHATSAPP_APP_SECRET, matching the
    `X-Hub-Signature-256` header Meta sends on every real webhook call.

    Without this, `POST /api/webhooks/whatsapp` accepts ANY payload from ANYONE
    who finds the URL — they could impersonate a lead, close follow-up
    sequences, or (with OUTBOX_LIVE=1) trigger a real reply to a real lead using
    attacker-controlled text. WHATSAPP_APP_SECRET is Meta's "App Secret" (Business
    Settings → App → Basic), a different value from WHATSAPP_TOKEN (the access
    token used to SEND messages) — both are needed, for different directions.

    No secret configured, missing header, or a mismatch — all return False;
    the caller rejects the request. `hmac.compare_digest` avoids a timing attack
    that could otherwise leak the correct signature byte by byte."""
    secret = os.environ.get("WHATSAPP_APP_SECRET")
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature_header)


def parse_inbound(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """Flatten a Meta webhook body to
    [{"from": <phone>, "text": <body>, "to_phone_id": <phone_number_id>}, ...].

    `to_phone_id` is the WhatsApp Business number that received the message
    (value.metadata.phone_number_id) — used to reply from the right vendor's
    number. Non-text messages (image/audio/…) become a "[type]" placeholder so the
    loop still registers that the lead replied. Malformed payloads yield [] (never raise).
    """
    out: List[Dict[str, str]] = []
    if not isinstance(payload, dict):
        return out
    for entry in payload.get("entry", []) or []:
        for change in (entry.get("changes", []) or []):
            value = change.get("value", {}) or {}
            to_phone_id = str((value.get("metadata") or {}).get("phone_number_id") or "")
            for m in (value.get("messages", []) or []):
                frm = str(m.get("from") or "")
                if not frm:
                    continue
                mtype = m.get("type")
                if mtype == "text":
                    text = ((m.get("text") or {}).get("body")) or ""
                else:
                    text = f"[{mtype or 'mensaje'}]"
                out.append({"from": frm, "text": text, "to_phone_id": to_phone_id})
    return out
