"""Local WhatsApp Web bridge transport. The bridge never exposes a public port."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import subprocess
import threading
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Optional


_bridge_stop = threading.Event()
_bridge_thread: Optional[threading.Thread] = None
_bridge_process: Optional[subprocess.Popen] = None
_extra_bridge_threads: list[threading.Thread] = []
_inbox_stop = threading.Event()
_inbox_wake = threading.Event()
_inbox_thread: Optional[threading.Thread] = None


def start_bridge() -> None:
    """Keep the local bridge alive with the existing backend service."""
    global _bridge_thread
    if os.environ.get("WHATSAPP_PROVIDER", "meta").lower() != "web":
        return
    if _bridge_thread and _bridge_thread.is_alive():
        return
    _bridge_stop.clear()
    _bridge_thread = threading.Thread(target=_bridge_loop, name="whatsapp-web-bridge", daemon=True)
    _bridge_thread.start()
    for client_id, port in _client_ports().items():
        thread = threading.Thread(target=_extra_bridge_loop, args=(client_id, port),
                                  name=f"whatsapp-web-{client_id}", daemon=True)
        _extra_bridge_threads.append(thread)
        thread.start()


def _client_ports() -> Dict[str, int]:
    """Explicit local bridge ports, one session per client. Never infer a port."""
    raw = os.environ.get("WHATSAPP_WEB_CLIENT_PORTS", "{}")
    try:
        values = json.loads(raw)
        if not isinstance(values, dict):
            raise ValueError("expected object")
        ports = {str(client): int(port) for client, port in values.items()}
        if any(not client.isalnum() or not 1024 <= port <= 65535 for client, port in ports.items()):
            raise ValueError("invalid client or port")
        if len(set(ports.values())) != len(ports) or 8810 in ports.values():
            raise ValueError("bridge ports must be unique")
        return ports
    except (TypeError, ValueError) as exc:
        raise RuntimeError("WHATSAPP_WEB_CLIENT_PORTS inválido") from exc


def _extra_bridge_loop(client_id: str, port: int) -> None:
    root = Path(__file__).resolve().parents[1] / "whatsapp-web-bridge"
    session_dir = root / f".session-{client_id}"
    env = dict(os.environ, WHATSAPP_WEB_BRIDGE_PORT=str(port),
               WHATSAPP_WEB_SESSION_DIR=str(session_dir),
               WHATSAPP_WEB_CLIENT_ID=client_id)
    while not _bridge_stop.is_set():
        try:
            process = subprocess.Popen(["node", str(root / "index.js")], cwd=root, env=env)
            while not _bridge_stop.is_set():
                try:
                    process.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    pass
            if _bridge_stop.is_set() and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        except OSError:
            logging.exception("Could not start WhatsApp bridge for %s", client_id)
        _bridge_stop.wait(5)


def _bridge_loop() -> None:
    global _bridge_process
    root = Path(__file__).resolve().parents[1] / "whatsapp-web-bridge"
    while not _bridge_stop.is_set():
        try:
            _bridge_process = subprocess.Popen(["node", str(root / "index.js")], cwd=root)
            while not _bridge_stop.is_set():
                try:
                    _bridge_process.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    pass
            if _bridge_stop.is_set() and _bridge_process.poll() is None:
                _bridge_process.terminate()
                try:
                    _bridge_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _bridge_process.kill()
                    _bridge_process.wait()
        except OSError:
            logging.exception("Could not start WhatsApp Web bridge")
        finally:
            _bridge_process = None
        _bridge_stop.wait(5)


def stop_bridge() -> None:
    _bridge_stop.set()
    if _bridge_thread:
        _bridge_thread.join(timeout=12)
    for thread in _extra_bridge_threads:
        thread.join(timeout=12)
    _extra_bridge_threads.clear()


def verify_signature(raw: bytes, header: Optional[str]) -> bool:
    secret = os.environ.get("WHATSAPP_WEB_BRIDGE_TOKEN", "")
    if len(secret) < 32 or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header, f"sha256={expected}")


def parse_message(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if not isinstance(payload, dict):
        return None
    event_id = str(payload.get("id") or "")
    phone = str(payload.get("from") or "")
    destination = str(payload.get("to_phone_id") or "")
    chat_id = str(payload.get("chat_id") or "")
    if (not event_id or not phone.isdigit() or not 8 <= len(phone) <= 15
            or not destination.isdigit() or not 8 <= len(destination) <= 15):
        return None
    if chat_id and not re.fullmatch(r"\d{8,20}@(c\.us|lid)", chat_id):
        return None
    return {
        "id": event_id,
        "from": phone,
        "text": str(payload.get("text") or "")[:4096],
        "to_phone_id": destination,
        "chat_id": chat_id,
    }


def _event_db() -> Path:
    return Path(os.environ.get("WHATSAPP_WEB_EVENT_DB", "whatsapp-web-events.sqlite3"))


def _connect_events() -> sqlite3.Connection:
    """Upgrade the old ID-only table without replaying previously claimed IDs."""
    target = _event_db()
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS received (id TEXT PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP)")
    columns = {row[1] for row in db.execute("PRAGMA table_info(received)")}
    for name, definition in (
        ("payload", "TEXT"),
        ("status", "TEXT NOT NULL DEFAULT 'completed'"),
        ("updated", "TEXT"),
        ("error", "TEXT"),
    ):
        if name not in columns:
            db.execute(f"ALTER TABLE received ADD COLUMN {name} {definition}")
            if name == "updated":
                db.execute("UPDATE received SET updated=created WHERE updated IS NULL")
    db.commit()
    return db


def claim_event(event_id: str, message: Optional[Dict[str, str]] = None) -> bool:
    """Durably queue a new message before acknowledging it to the bridge."""
    with closing(_connect_events()) as db, db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO received(id, payload, status) VALUES (?, ?, ?)",
            (event_id, json.dumps(message) if message is not None else None,
             "pending" if message is not None else "completed"),
        )
    if cursor.rowcount and message is not None:
        _inbox_wake.set()
    return cursor.rowcount == 1


def inbox_stats() -> Dict[str, Any]:
    with closing(_connect_events()) as db, db:
        rows = db.execute("SELECT status, count(*) FROM received GROUP BY status").fetchall()
        oldest = db.execute("SELECT min(created) FROM received WHERE status IN ('pending', 'processing')").fetchone()[0]
    return {"counts": dict(rows), "oldest_unfinished": oldest}


def _next_pending() -> Optional[Dict[str, str]]:
    with closing(_connect_events()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT id, payload FROM received WHERE status='pending' ORDER BY created, rowid LIMIT 1").fetchone()
        if row is None:
            return None
        db.execute("UPDATE received SET status='processing', updated=CURRENT_TIMESTAMP WHERE id=? AND status='pending'", (row[0],))
    return json.loads(row[1])


def _finish_event(event_id: str, status: str, error: str = "") -> None:
    with closing(_connect_events()) as db, db:
        db.execute("UPDATE received SET status=?, error=?, updated=CURRENT_TIMESTAMP WHERE id=?",
                   (status, error[:500], event_id))


def _inbox_loop(processor) -> None:
    while not _inbox_stop.is_set():
        try:
            message = _next_pending()
            if message is None:
                _inbox_wake.wait(2)
                _inbox_wake.clear()
                continue
            try:
                results = processor([message])
                outcome = results[0] if results else {}
                delivery = outcome.get("delivery") or {}
                if (outcome.get("matched") and delivery.get("status") == "sent"
                        and delivery.get("via") == "whatsapp_web"):
                    _finish_event(message["id"], "completed")
                elif outcome.get("matched") and outcome.get("manual_review"):
                    _finish_event(message["id"], "completed")
                else:
                    _finish_event(message["id"], "needs_review",
                                  delivery.get("error") or "No se confirmó el envío de respuesta")
            except Exception as exc:
                # The process may have sent before failing. Never send again blindly.
                _finish_event(message["id"], "needs_review", str(exc))
        except Exception:
            logging.exception("WhatsApp inbox worker failed")
            _inbox_stop.wait(2)


def start_inbox_worker(processor) -> None:
    global _inbox_thread
    if os.environ.get("WHATSAPP_PROVIDER", "meta").lower() != "web":
        return
    if _inbox_thread and _inbox_thread.is_alive():
        return
    # An interrupted send has an unknown outcome: expose it for review, not replay.
    with closing(_connect_events()) as db, db:
        db.execute("UPDATE received SET status='needs_review', error='Proceso interrumpido: revisar antes de reenviar', updated=CURRENT_TIMESTAMP WHERE status='processing'")
    _inbox_stop.clear()
    _inbox_thread = threading.Thread(target=_inbox_loop, args=(processor,), name="whatsapp-web-inbox", daemon=True)
    _inbox_thread.start()


def stop_inbox_worker() -> None:
    _inbox_stop.set()
    _inbox_wake.set()
    if _inbox_thread:
        _inbox_thread.join(timeout=3)


def bridge_request(path: str, body: Optional[Dict[str, Any]] = None,
                   client_id: Optional[str] = None) -> Dict[str, Any]:
    secret = os.environ.get("WHATSAPP_WEB_BRIDGE_TOKEN", "")
    if len(secret) < 32:
        raise RuntimeError("Falta configurar WHATSAPP_WEB_BRIDGE_TOKEN")
    from .config import DEFAULT_INBOUND_CLIENT_ID
    if client_id and client_id != DEFAULT_INBOUND_CLIENT_ID:
        port = _client_ports().get(client_id)
        if not port:
            raise RuntimeError(f"No hay puente WhatsApp configurado para {client_id}")
        base = f"http://127.0.0.1:{port}"
    else:
        base = os.environ.get("WHATSAPP_WEB_BRIDGE_URL", "http://127.0.0.1:8810").rstrip("/")
    if not base.startswith("http://127.0.0.1:") and not base.startswith("http://localhost:"):
        raise RuntimeError("El puente de WhatsApp Web debe usar localhost")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        base + path, data=data,
        headers={"Authorization": f"Bearer {secret}", "Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=90 if data is not None else 5) as res:
            return json.load(res)
    except urllib.error.HTTPError as exc:
        try:
            detail = str(json.load(exc).get("error") or "")[:300]
        except (ValueError, OSError, AttributeError):
            detail = ""
        raise RuntimeError(f"Puente WhatsApp Web: HTTP {exc.code}" +
                           (f" · {detail}" if detail else "")) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Puente WhatsApp Web sin conexión") from exc


class WhatsAppWebSender:
    name = "whatsapp_web"

    def send(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        from .channels import _result
        to = "".join(c for c in str(msg.get("to") or "") if c.isdigit())
        if msg.get("whatsapp_send_type") == "template":
            return _result("whatsapp", to, "skipped", error="solo respuestas entrantes; campañas desactivadas", via=self.name)
        if not to or not str(msg.get("body") or "").strip():
            return _result("whatsapp", to or None, "skipped", error="falta destinatario o texto", via=self.name)
        client_id = msg.get("client_id")
        expected = "".join(c for c in str(msg.get("whatsapp_from") or "") if c.isdigit())
        if client_id and not expected:
            return _result("whatsapp", to, "error", error="Falta número receptor del cliente", via=self.name)
        if expected:
            status = bridge_request("/status", client_id=client_id)
            actual = "".join(c for c in str(status.get("account") or "") if c.isdigit())
            if status.get("state") != "ready" or actual != expected:
                return _result("whatsapp", to, "error",
                               error="El número conectado no coincide con el asignado al cliente", via=self.name)
        result = bridge_request("/send", {"to": to, "text": msg["body"],
                                          "chat_id": msg.get("whatsapp_chat_id") or ""}, client_id=client_id)
        if not result.get("id") or result.get("ack") == -1:
            return _result("whatsapp", to, "error", error="El puente no confirmó la aceptación del mensaje", via=self.name)
        outcome = _result("whatsapp", to, "sent", id=result["id"], via=self.name)
        outcome["delivery_status"] = "accepted"  # no equivale a entrega al teléfono
        outcome["ack"] = result.get("ack")
        return outcome
