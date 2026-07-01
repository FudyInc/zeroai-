"""Parse inbound WhatsApp webhooks (Meta Cloud API) into a simple message list.

Pure and stdlib-only so it's testable offline with a captured payload — the
webhook endpoint stays a thin shell around this. The actual receiving needs a
public URL (Meta calls it), which is the external piece; this logic is not.
"""
from __future__ import annotations

from typing import Any, Dict, List


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
