"""Outbound channels — the layer that actually SENDS what OUTREACH/TRACKER draft.

Mock-first, faithful to one contract so flipping to real = plugging credentials,
not rewriting. Mirrors the `store.make_crm` switch:

    msg    = {"channel", "to", "subject"|None, "body", "company"}
    result = {"channel", "to", "status": "sent"|"skipped"|"error",
              "id": str|None, "error": str|None, "via": "mock"|"email"|"whatsapp"}

Senders are interchangeable. `MockSender` records without touching the network and
returns the same shape the real ones do (a mock that drifts from the contract gives
false confidence). Real sends only happen when **OUTBOX_LIVE=1** is set explicitly —
so credentials sitting in `.env` never cause an accidental real send (the safe
default is mock even in production until the switch is deliberately flipped).
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from email.message import EmailMessage
from typing import Any, Dict, List, Optional

from ._env import load_env

load_env()

# Channels that can be auto-sent. cold_call / linkedin / sdr_ai are drafted but
# handed to a human/other system — never "sent" by the outbox (stay mock).
SENDABLE = ("email", "whatsapp")


def _result(channel: str, to: Optional[str], status: str, *, id: Optional[str] = None,
            error: Optional[str] = None, via: str = "mock") -> Dict[str, Any]:
    return {"channel": channel, "to": to, "status": status, "id": id, "error": error, "via": via}


class MockSender:
    """Records a send without any network. Faithful to the real contract."""
    name = "mock"

    def send(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        channel = msg.get("channel") or "email"
        to = msg.get("to")
        if not to:
            return _result(channel, None, "skipped", error="sin destinatario (lead sin email/teléfono)")
        return _result(channel, to, "sent", id=f"mock-{uuid.uuid4().hex[:10]}", via="mock")


class EmailSender:
    """Real SMTP send (stdlib). Needs SMTP_HOST [, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM]."""
    name = "email"

    def __init__(self) -> None:
        self.host = os.environ["SMTP_HOST"]
        self.port = int(os.environ.get("SMTP_PORT", "587"))
        self.user = os.environ.get("SMTP_USER")
        self.password = os.environ.get("SMTP_PASS")
        self.sender = os.environ.get("SMTP_FROM") or self.user or "no-reply@localhost"

    def send(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        to = msg.get("to")
        if not to or "@" not in str(to):
            return _result("email", to, "skipped", error="destinatario no es un email", via="email")
        em = EmailMessage()
        em["From"] = self.sender
        em["To"] = to
        em["Subject"] = msg.get("subject") or "Hola"
        em.set_content(msg.get("body") or "")
        with smtplib.SMTP(self.host, self.port, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            if self.user:
                s.login(self.user, self.password or "")
            s.send_message(em)
        return _result("email", to, "sent", id=em.get("Message-ID") or "smtp", via="email")


class WhatsAppSender:
    """Real WhatsApp send via Meta Cloud API (stdlib urllib). Needs a phone_id +
    token — either passed in (per-vendor credentials, see `zero/vendors.py`) or,
    if omitted, the global WHATSAPP_TOKEN/WHATSAPP_PHONE_ID env vars. Swappable
    for Twilio/another provider — same `send` contract."""
    name = "whatsapp"
    API = "https://graph.facebook.com/v20.0"

    def __init__(self, phone_id: Optional[str] = None, token: Optional[str] = None) -> None:
        self.token = token or os.environ["WHATSAPP_TOKEN"]
        self.phone_id = phone_id or os.environ["WHATSAPP_PHONE_ID"]

    def send(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        to = "".join(ch for ch in str(msg.get("to") or "") if ch.isdigit())
        if not to:
            return _result("whatsapp", msg.get("to"), "skipped", error="sin número válido", via="whatsapp")
        body = {"messaging_product": "whatsapp", "to": to, "type": "text",
                "text": {"body": msg.get("body") or ""}}
        req = urllib.request.Request(
            f"{self.API}/{self.phone_id}/messages",
            data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode("utf-8"))
        mid = (res.get("messages") or [{}])[0].get("id")
        return _result("whatsapp", to, "sent", id=mid, via="whatsapp")


def whatsapp_status() -> Dict[str, Any]:
    """Pings the Graph API with WHATSAPP_TOKEN/WHATSAPP_PHONE_ID to confirm the
    WhatsApp Business number is really linked (not just that the env vars exist).
    Raises RuntimeError with Meta's own message on failure (or a clear message if
    the credentials aren't configured — never a bare KeyError)."""
    token = os.environ.get("WHATSAPP_TOKEN")
    phone_id = os.environ.get("WHATSAPP_PHONE_ID")
    if not (token and phone_id):
        raise RuntimeError("WhatsApp sin configurar: faltan WHATSAPP_TOKEN / WHATSAPP_PHONE_ID")
    q = urllib.parse.urlencode({"fields": "display_phone_number,verified_name", "access_token": token})
    url = f"{WhatsAppSender.API}/{phone_id}?{q}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(detail).get("error", {}).get("message", detail)
        except Exception:
            msg = detail
        raise RuntimeError(f"Meta: {msg[:200]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"no pude contactar a Meta: {e}") from e
    return {"display_phone_number": d.get("display_phone_number"), "verified_name": d.get("verified_name")}


class Outbox:
    """Routes each message to the right sender; falls back to mock per channel.

    Never raises: a sender failure (network/timeout/bad creds) degrades to an
    `error` result so one bad send can't crash the pipeline — same discipline as
    the LLM backends.
    """

    def __init__(self, real_senders: Optional[Dict[str, Any]] = None) -> None:
        self.real = real_senders or {}
        self._mock = MockSender()
        self.log: List[Dict[str, Any]] = []

    @property
    def live(self) -> bool:
        return bool(self.real)

    def send(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        channel = msg.get("channel") or "email"
        sender = self.real.get(channel, self._mock)
        try:
            res = sender.send(msg)
        except Exception as e:   # noqa: BLE001 — any failure degrades, never crashes
            res = _result(channel, msg.get("to"), "error", error=str(e),
                          via=getattr(sender, "name", "mock"))
        self.log.append(res)
        return res

    def send_all(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [self.send(m) for m in messages]


def make_outbox() -> Outbox:
    """Mock by default — even with real credentials present. Set OUTBOX_LIVE=1 to
    actually send through whatever channels are configured."""
    if os.environ.get("OUTBOX_LIVE") != "1":
        return Outbox()
    real: Dict[str, Any] = {}
    if os.environ.get("SMTP_HOST"):
        real["email"] = EmailSender()
    if os.environ.get("WHATSAPP_TOKEN") and os.environ.get("WHATSAPP_PHONE_ID"):
        real["whatsapp"] = WhatsAppSender()
    return Outbox(real)
