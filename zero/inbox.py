"""Inbound channel — where replies get DETECTED (the mirror of channels.py).

Mock-first, faithful to one contract so flipping to real = plugging credentials,
not rewriting:

    message = {"channel": "email"|"whatsapp", "from": str (email|phone),
               "subject": str|None, "body": str, "received_at": iso|None}

`fetch()` consumes: each message is returned exactly once, so a lead's reply
closes its sequence one time and never re-triggers. Inboxes are interchangeable:
`MockInbox` (in-memory, for tests), `FileInbox` (a local JSON drop-box — write a
message into `inbox.json` and the next follow-up run picks it up), `ImapInbox`
(real IMAP, stdlib). Real reads only happen when **INBOX_LIVE=1** is set
explicitly — same discipline as OUTBOX_LIVE.
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import json
import os
from typing import Any, Dict, List, Optional

from ._env import load_env

load_env()


def _norm(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize to the contract; a message without sender or body is noise."""
    sender = str(raw.get("from") or "").strip()
    body = str(raw.get("body") or "").strip()
    if not sender or not body:
        return None
    return {
        "channel": raw.get("channel") or ("email" if "@" in sender else "whatsapp"),
        "from": sender,
        "subject": raw.get("subject"),
        "body": body,
        "received_at": raw.get("received_at"),
    }


class Inbox:
    """Interface: return the unread inbound messages, consuming them."""

    live = False

    def fetch(self) -> List[Dict[str, Any]]:
        raise NotImplementedError


class MockInbox(Inbox):
    """In-memory queue, no network. Faithful to the real contract."""

    def __init__(self, messages: Optional[List[Dict[str, Any]]] = None):
        self._queue: List[Dict[str, Any]] = list(messages or [])

    def add(self, msg: Dict[str, Any]) -> None:
        self._queue.append(msg)

    def fetch(self) -> List[Dict[str, Any]]:
        out = [m for m in (_norm(r) for r in self._queue) if m]
        self._queue = []
        return out


class FileInbox(Inbox):
    """A local JSON drop-box: the file holds a list of messages; fetching empties
    it. Lets a human (or another process) simulate/forward replies without IMAP.
    A corrupt file is left untouched and yields nothing — never overwrite blind."""

    def __init__(self, path: str = "inbox.json"):
        self.path = path

    def fetch(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, list):
                return []
        except Exception:
            return []
        out = [m for m in (_norm(r) for r in raw) if m]
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([], f)
        return out


class ImapInbox(Inbox):
    """Real IMAP read (stdlib). Needs IMAP_HOST, IMAP_USER, IMAP_PASS
    [, IMAP_PORT, IMAP_FOLDER]. Fetches UNSEEN and marks them seen, so the
    consume-once contract holds. Never raises: any failure degrades to an
    empty fetch — one bad poll can't crash a follow-up run."""

    live = True

    def __init__(self) -> None:
        self.host = os.environ["IMAP_HOST"]
        self.port = int(os.environ.get("IMAP_PORT", "993"))
        self.user = os.environ["IMAP_USER"]
        self.password = os.environ["IMAP_PASS"]
        self.folder = os.environ.get("IMAP_FOLDER", "INBOX")

    def fetch(self) -> List[Dict[str, Any]]:
        try:
            with imaplib.IMAP4_SSL(self.host, self.port) as imap:
                imap.login(self.user, self.password)
                imap.select(self.folder)
                _, data = imap.search(None, "UNSEEN")
                out: List[Dict[str, Any]] = []
                for num in (data[0] or b"").split():
                    _, parts = imap.fetch(num, "(RFC822)")
                    msg = email.message_from_bytes(parts[0][1])
                    norm = _norm({
                        "channel": "email",
                        "from": email.utils.parseaddr(msg.get("From", ""))[1],
                        "subject": msg.get("Subject"),
                        "body": self._body(msg),
                        "received_at": msg.get("Date"),
                    })
                    if norm:
                        out.append(norm)
                    imap.store(num, "+FLAGS", "\\Seen")
                return out
        except Exception:
            return []

    @staticmethod
    def _body(msg: email.message.Message) -> str:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode(part.get_content_charset() or "utf-8",
                                               errors="replace")
            return ""
        payload = msg.get_payload(decode=True)
        return payload.decode(msg.get_content_charset() or "utf-8",
                              errors="replace") if payload else ""


def make_inbox(path: str = "inbox.json") -> Inbox:
    """File drop-box by default — even with IMAP credentials present. Set
    INBOX_LIVE=1 to actually poll the configured mailbox."""
    if os.environ.get("INBOX_LIVE") == "1" and os.environ.get("IMAP_HOST"):
        return ImapInbox()
    return FileInbox(path)
