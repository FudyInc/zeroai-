"""Revisión humana de eventos retenidos, sin reenviar ni enseñar respuestas."""
from contextlib import closing
import hashlib
import json
import re
import sqlite3


PREFIX = 'event:'


def _key(event_id):
    return PREFIX + hashlib.sha256(event_id.encode()).hexdigest()


def _accounts(memory):
    from .client_integrations import credentials
    result = {}
    for client in memory.clients:
        number = str(memory.get_client_agent_profile(client).get('whatsapp_number') or
                     credentials(client, 'whatsapp').get('WHATSAPP_PHONE_ID') or '')
        number = re.sub(r'\D', '', number)
        if number:
            result.setdefault(number, set()).add(client)
    return result


def _belongs(payload, client, memory, accounts):
    if client not in memory.clients:
        return False
    explicit = payload.get('client')
    owners = accounts.get(str(payload.get('to_phone_id') or ''), set())
    if explicit:
        return explicit == client and (not owners or client in owners)
    return owners == {client}


def _database():
    from .whatsapp_web import _event_db
    path = _event_db().resolve()
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) if path.exists() else None


def _payload(raw):
    try:
        item = json.loads(raw or '{}')
        return item if isinstance(item, dict) else {}
    except (ValueError, TypeError):
        return {}


def list_event_reviews(memory, client, include_resolved=False):
    db = _database()
    if db is None:
        return []
    accounts = _accounts(memory)
    statuses = ('needs_review', 'archived') if include_resolved else ('needs_review',)
    items = []
    with closing(db):
        columns = {row[1] for row in db.execute('PRAGMA table_info(received)')}
        if not {'payload', 'status', 'updated'} <= columns:
            return []
        placeholders = ','.join('?' for _ in statuses)
        for event_id, created, updated, raw, status in db.execute(
                f'SELECT id,created,updated,payload,status FROM received WHERE status IN ({placeholders}) ORDER BY created DESC', statuses):
            payload = _payload(raw)
            if not _belongs(payload, client, memory, accounts):
                continue
            chat = str(payload.get('chat_id') or '')
            if not re.fullmatch(r'\d{8,20}@(c\.us|lid)', chat):
                chat = ''
            items.append({'clave': _key(event_id), 'tipo': 'evento',
                          'estado': 'abierta' if status == 'needs_review' else 'descartada',
                          'pregunta': str(payload.get('text') or 'Mensaje pendiente de revisión')[:4096],
                          'reason': 'Revise la conversación antes de responder. Cerrar este caso no envía mensajes ni reactiva al agente.',
                          'chat_id': chat, 'veces': 1,
                          'ultima': (updated or created).replace(' ', 'T') + 'Z',
                          'source': 'event_queue'})
    return items


def dismiss_event_review(memory, client, key):
    """Cambio atómico y definitivo: nunca vuelve a pending ni libera el chat."""
    from .whatsapp_web import _event_db
    path = _event_db().resolve()
    if not path.exists() or not key.startswith(PREFIX):
        return False
    accounts = _accounts(memory)
    with closing(sqlite3.connect(path.as_uri() + '?mode=rw', uri=True)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        columns = {row[1] for row in db.execute('PRAGMA table_info(received)')}
        if not {'payload', 'status', 'updated'} <= columns:
            return False
        for event_id, raw in db.execute("SELECT id,payload FROM received WHERE status='needs_review'"):
            if _key(event_id) == key and _belongs(_payload(raw), client, memory, accounts):
                return db.execute("UPDATE received SET status='archived', updated=CURRENT_TIMESTAMP WHERE id=? AND status='needs_review'", (event_id,)).rowcount == 1
    return False
