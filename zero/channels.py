"""Outbound channels — the layer that actually SENDS what OUTREACH/TRACKER draft.

Mock-first, faithful to one contract so flipping to real = plugging credentials,
not rewriting. Mirrors the `store.make_crm` switch:

    msg    = {"channel", "to", "subject"|None, "body", "company",
              "whatsapp_send_type": "template"|None}
    result = {"channel", "to", "status": "sent"|"skipped"|"error",
              "id": str|None, "error": str|None, "via": "mock"|"email"|"whatsapp"}

`whatsapp_send_type="template"` marks a message as business-initiated contact to a
lead that hasn't replied (Meta requires a pre-approved template outside the 24h
customer-service window — a free-text message there is rejected by the real Graph
API). Omit it (or None) for a reply to something the lead just wrote — free text is
fine within that window. Set by the orchestrator, not by OUTREACH/TRACKER.

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
import time
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
        if msg.get("whatsapp_send_type") == "template":
            body = self._template_body(to, msg.get("body") or "")
        else:
            body = self._text_body(to, msg.get("body") or "")
        req = urllib.request.Request(
            f"{self.API}/{self.phone_id}/messages",
            data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            res = json.loads(r.read().decode("utf-8"))
        mid = (res.get("messages") or [{}])[0].get("id")
        return _result("whatsapp", to, "sent", id=mid, via="whatsapp")

    @staticmethod
    def _text_body(to: str, text: str) -> Dict[str, Any]:
        """Graph API payload for a free-text reply — only valid within the 24h
        customer-service window (replying to something the lead just wrote)."""
        return {"messaging_product": "whatsapp", "to": to, "type": "text",
                "text": {"body": text}}

    @staticmethod
    def _template_body(to: str, text: str) -> Dict[str, Any]:
        """Graph API payload for a business-initiated (cold) message — Meta
        requires a pre-approved template here, a free-text message is rejected.
        Raises (Outbox degrades it to an `error` result, same as any other send
        failure) if no template is configured yet — never silently falls back to
        free text, which Meta would reject anyway outside the 24h window."""
        from .config import WHATSAPP_TEMPLATE
        name = WHATSAPP_TEMPLATE.get("name")
        if not name:
            raise RuntimeError(
                "falta configurar WHATSAPP_TEMPLATE en zero/config.py (nombre de la "
                "plantilla aprobada en Meta Business Manager) — ver docs/GO-LIVE.md"
            )
        return {
            "messaging_product": "whatsapp", "to": to, "type": "template",
            "template": {
                "name": name,
                "language": {"code": WHATSAPP_TEMPLATE.get("language", "es")},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": text}]}],
            },
        }


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
    the LLM backends. Retries a few times first (config.OUTBOX_RETRY_ATTEMPTS) so
    a momentary network blip doesn't silently lose a send — only degrades to
    `error` once every attempt has failed.
    """

    def __init__(self, real_senders: Optional[Dict[str, Any]] = None,
                 wa_sender_factory: Optional[Any] = None,
                 retry_attempts: Optional[int] = None,
                 retry_delay: Optional[float] = None) -> None:
        from .config import OUTBOX_RETRY_ATTEMPTS, OUTBOX_RETRY_DELAY_SECONDS
        self.real = real_senders or {}
        self._mock = MockSender()
        # Builds a per-vendor WhatsApp sender from (phone_id, token) when live, so
        # each client sends from its assigned vendor's number. Cached by phone_id.
        self._wa_factory = wa_sender_factory
        self._wa_cache: Dict[str, Any] = {}
        self.log: List[Dict[str, Any]] = []
        self.retry_attempts = retry_attempts if retry_attempts is not None else OUTBOX_RETRY_ATTEMPTS
        self.retry_delay = retry_delay if retry_delay is not None else OUTBOX_RETRY_DELAY_SECONDS

    @property
    def live(self) -> bool:
        return bool(self.real)

    def _sender_for(self, channel: str, wa_creds: Optional[Any]) -> Any:
        if not self.real:
            return self._mock                       # mock mode: never real
        if channel == "whatsapp" and wa_creds and self._wa_factory:
            phone_id, token = wa_creds
            if phone_id and token:
                if phone_id not in self._wa_cache:
                    self._wa_cache[phone_id] = self._wa_factory(phone_id, token)
                return self._wa_cache[phone_id]
        return self.real.get(channel, self._mock)

    def send(self, msg: Dict[str, Any], wa_creds: Optional[Any] = None) -> Dict[str, Any]:
        channel = msg.get("channel") or "email"
        sender = self._sender_for(channel, wa_creds)
        last_error: Optional[Exception] = None
        for attempt in range(1, max(self.retry_attempts, 1) + 1):
            try:
                res = sender.send(msg)
                break
            except Exception as e:   # noqa: BLE001 — any failure degrades, never crashes
                last_error = e
                if attempt < self.retry_attempts:
                    time.sleep(self.retry_delay)
        else:
            res = _result(channel, msg.get("to"), "error", error=str(last_error),
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
    # Credenciales completas o nada: un SMTP_USER sin SMTP_PASS intentaría logins
    # vacíos (error en cada envío) — mejor seguir en mock hasta que esté la clave.
    if os.environ.get("SMTP_HOST") and (
        not os.environ.get("SMTP_USER") or os.environ.get("SMTP_PASS")
    ):
        real["email"] = EmailSender()
    if os.environ.get("WHATSAPP_TOKEN") and os.environ.get("WHATSAPP_PHONE_ID"):
        real["whatsapp"] = WhatsAppSender()              # global fallback sender
    # Per-vendor senders are built on demand from each vendor's (phone_id, token).
    return Outbox(real, wa_sender_factory=lambda pid, tok: WhatsAppSender(pid, tok))
