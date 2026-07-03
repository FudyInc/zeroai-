"""Vendor catalog — ZeroAI's sales agents (Fernanda, Stéfano, ...).

ZeroAI no es un solo bot: cada CLIENTE tiene un vendedor humano-IA asignado
(Fernanda, Stéfano, ...) que lo atiende por WhatsApp con SU PROPIO número de
WhatsApp Business (su propio phone_id/token en Meta).

A `Vendor` is a plain dict — same shape in mock and real, and safe to store in
state.json / Supabase:

    {"id": str,            # slug, e.g. "fernanda"
     "name": str,          # display name
     "photo": str | None,  # url/path to an avatar
     "tone": str | None,   # short persona hint for the agent prompt
     "phone": str,         # display number, e.g. "+56 9 9876 5432"
     "whatsapp_phone_id": str}

The WhatsApp token is NEVER part of the record (secret, never committed to JSON).
It's resolved per-vendor from the environment by `credentials_for`.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from ._env import load_env

load_env()


def seed_vendors() -> List[Dict[str, Any]]:
    """Two offline vendors with fake phone_ids and no real token — run fully in
    mock, no network needed."""
    return [
        {
            "id": "fernanda",
            "name": "Fernanda",
            "photo": None,
            "tone": "cercana, cálida, directa",
            "phone": "+56 9 1111 1111",
            "whatsapp_phone_id": "000000000000001",
        },
        {
            "id": "stefano",
            "name": "Stéfano",
            "photo": None,
            "tone": "formal, técnico, al grano",
            "phone": "+56 9 2222 2222",
            "whatsapp_phone_id": "000000000000002",
        },
    ]


def clients_count_for(vendor_id: str, memory: Any) -> int:
    """How many known clients resolve to `vendor_id` as their assigned vendor.

    Uses `memory.get_client_vendor(client_id)`, which falls back to
    `DEFAULT_VENDOR_ID` when a client has no explicit assignment — so the
    default vendor's count includes unassigned clients. `memory` is duck-typed
    (anything exposing `.clients` and `.get_client_vendor`, i.e. SessionMemory)
    rather than imported by type, to avoid a circular import — zero.memory
    already imports this module. Presentation-only: does not touch the stored
    Vendor record or the contract credentials_for/Zero.vendor_for rely on."""
    return sum(1 for c in memory.clients if memory.get_client_vendor(c) == vendor_id)


def credentials_for(vendor: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """(phone_id, token) for sending as this vendor on WhatsApp.

    - phone_id: the vendor's own `whatsapp_phone_id`, or the global
      WHATSAPP_PHONE_ID if the vendor doesn't have one.
    - token: `WHATSAPP_TOKEN_<ID>` (vendor id uppercased) if set, else the global
      WHATSAPP_TOKEN. The token is never read from the vendor record itself —
      it's a secret and lives only in the environment.
    """
    phone_id = vendor.get("whatsapp_phone_id") or os.environ.get("WHATSAPP_PHONE_ID")
    vendor_id = str(vendor.get("id") or "").upper()
    token = os.environ.get(f"WHATSAPP_TOKEN_{vendor_id}") or os.environ.get("WHATSAPP_TOKEN")
    return phone_id, token
