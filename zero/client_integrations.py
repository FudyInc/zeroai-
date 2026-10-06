"""Secretos de canales, separados por negocio. Ninguna lectura usa fallback global."""
from __future__ import annotations

import hashlib
import os

from ._env import set_env
from .cloud_env import save_secret

FIELDS = {
    "email": ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_FROM"),
    "vapi": ("VAPI_API_KEY", "VAPI_ASSISTANT_ID", "VAPI_PHONE_NUMBER_ID"),
    "whatsapp": ("WHATSAPP_TOKEN", "WHATSAPP_PHONE_ID", "WHATSAPP_PROVIDER",
                 "WHATSAPP_APP_SECRET", "WHATSAPP_VERIFY_TOKEN"),
}


def secret_key(client: str, field: str) -> str:
    if field not in {item for group in FIELDS.values() for item in group}:
        raise ValueError("campo de integración inválido")
    digest = hashlib.sha256(client.encode("utf-8")).hexdigest()[:20].upper()
    return f"{field}_CLIENT_{digest}"


def credentials(client: str, channel: str) -> dict[str, str]:
    if not client or channel not in FIELDS:
        return {}
    return {field: os.environ.get(secret_key(client, field), "") for field in FIELDS[channel]}


def configured(client: str, channel: str) -> bool:
    values = credentials(client, channel)
    if channel == "email":
        return bool(values.get("SMTP_HOST") and values.get("SMTP_FROM") and
                    (not values.get("SMTP_USER") or values.get("SMTP_PASS")))
    if channel == "vapi":
        return bool(values.get("VAPI_API_KEY"))
    if channel == "whatsapp":
        return bool(values.get("WHATSAPP_TOKEN") and values.get("WHATSAPP_PHONE_ID"))
    return False


def whatsapp_provider(client: str) -> str:
    value = credentials(client, "whatsapp").get("WHATSAPP_PROVIDER")
    if value in ("web", "meta"):
        return value
    from .config import DEFAULT_INBOUND_CLIENT_ID
    return "web" if client == DEFAULT_INBOUND_CLIENT_ID and os.environ.get("WHATSAPP_PROVIDER") == "web" else "meta"


def save_credentials(client: str, channel: str, updates: dict[str, str]) -> bool:
    if not client or channel not in FIELDS or not set(updates) <= set(FIELDS[channel]):
        raise ValueError("integración inválida")
    if "WHATSAPP_PROVIDER" in updates and updates["WHATSAPP_PROVIDER"] not in ("web", "meta"):
        raise ValueError("proveedor de WhatsApp inválido")
    backed_up = True
    for field, value in updates.items():
        clean = str(value).strip()
        if not clean:
            continue
        key = secret_key(client, field)
        set_env(key, clean)
        backed_up &= save_secret(key, clean)
    return backed_up
