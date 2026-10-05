"""Archive signed Meta coexistence webhooks until the CRM can import them.

Meta's Business App onboarding sends contact, history, and app-sent-message
events in addition to ordinary inbound ``messages``. Retaining those events is
necessary before starting the one-time history sync; acknowledging and dropping
them would permanently lose the data Meta only sends once.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


FIELDS = frozenset({"account_update", "history", "smb_app_state_sync", "smb_message_echoes"})


def archive_events(payload: Any, path: str | None = None) -> int:
    """Append coexistence changes from a signature-verified webhook to JSONL.

    Raises on disk errors so Meta retries rather than losing a one-time sync.
    The caller must verify ``X-Hub-Signature-256`` before invoking this function.
    """
    if not isinstance(payload, dict):
        return 0
    records = []
    entries = payload.get("entry") or []
    if not isinstance(entries, list):
        return 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes") or []
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict) or change.get("field") not in FIELDS:
                continue
            records.append({"waba_id": entry.get("id"), "field": change["field"],
                            "value": change.get("value")})
    if not records:
        return 0
    target = Path(path or os.environ.get("WHATSAPP_COEXISTENCE_EVENTS_PATH") or
                  "whatsapp-coexistence-events.jsonl")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as out:
        for record in records:
            out.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    return len(records)
