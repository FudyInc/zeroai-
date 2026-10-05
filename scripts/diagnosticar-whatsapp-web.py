#!/usr/bin/env python3
"""Show safe, concise runtime diagnostics for ZeroAI's WhatsApp Web bridge."""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path('/home/diego/zeroai')


def settings() -> dict[str, str]:
    return dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines()
                if '=' in line and not line.startswith('#'))


def request(path: str, token: str) -> dict:
    req = urllib.request.Request('http://127.0.0.1:8810' + path,
                                 headers={'Authorization': f'Bearer {token}'})
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.load(response)


def scrub(value: object, token: str) -> str:
    result = str(value).replace(token, '[clave]') if token else str(value)
    return re.sub(r'(?<!\d)\+?\d{8,15}(?!\d)', '[telefono]', result)


def main() -> None:
    env = settings()
    token = env.get('WHATSAPP_WEB_BRIDGE_TOKEN', '')
    print('Hora UTC:', dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'))
    print('Configuracion:', {key: env.get(key) for key in
                            ('WHATSAPP_PROVIDER', 'OUTBOX_LIVE', 'OWNER_WHATSAPP_PAUSED')})
    try:
        pid = subprocess.check_output(
            ['systemctl', 'show', '-p', 'MainPID', '--value', 'zero-backend'],
            text=True, timeout=5).strip()
        print('Backend PID:', pid)
    except (OSError, subprocess.SubprocessError) as exc:
        print('Backend PID: error', scrub(exc, token))
    try:
        with urllib.request.urlopen('http://127.0.0.1:8800/api/health', timeout=5) as response:
            print('Backend HTTP:', response.status)
    except (OSError, ValueError) as exc:
        print('Backend HTTP: error', scrub(exc, token))
    for path in ('/status', '/diagnostics'):
        try:
            data = request(path, token)
            data.pop('qr', None)
            data.pop('account', None)
            data.pop('recentChats', None)
            print(path, scrub(json.dumps(data, ensure_ascii=False), token))
        except urllib.error.HTTPError as exc:
            print(path, 'HTTP', exc.code)
        except (OSError, ValueError) as exc:
            print(path, 'error', scrub(exc, token))
    db_path = ROOT / 'whatsapp-web-events.sqlite3'
    try:
        with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True) as db:
            count, last = db.execute('SELECT COUNT(*), MAX(created) FROM received').fetchone()
            print('Entrantes registrados:', count, 'ultimo UTC:', last)
    except sqlite3.Error as exc:
        print('Entrantes registrados: error', scrub(exc, token))
    try:
        entries = json.loads((ROOT / 'agent_activity.json').read_text())
        recent = [(dt.datetime.fromtimestamp(e['ts'], dt.timezone.utc).isoformat(timespec='seconds'),
                   e.get('agent'), e.get('status')) for e in entries[-3:]]
        print('Actividad agente:', recent)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('Actividad agente: error', scrub(exc, token))
    if env.get('SUPABASE_URL') and env.get('SUPABASE_KEY'):
        try:
            sys.path.insert(0, str(ROOT))
            from zero._supabase import sb_request
            rows = sb_request(env['SUPABASE_URL'].rstrip('/'), env['SUPABASE_KEY'],
                              'GET', 'crm_leads?client_id=eq.zeroai&select=history&limit=1000') or []
            cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=30)).isoformat()
            events = [event for row in rows for event in (row.get('history') or [])
                      if event.get('ts', '') >= cutoff and event.get('event') in
                      ('created', 'send', 'auto_reply', 'auto_reply_failed',
                       'auto_reply_accepted', 'reply', 'inbound_unmatched')]
            events.sort(key=lambda event: event.get('ts', ''))
            print('Eventos CRM recientes:')
            for event in events[-12:]:
                detail = event.get('detail', '') if event.get('event') == 'send' else ''
                print(' ', event.get('ts'), event.get('event'), scrub(detail, token))
        except Exception as exc:
            print('Eventos CRM: error', scrub(exc, token)[:250])
    try:
        logs = subprocess.check_output(
            ['journalctl', '-u', 'zero-backend', '--since', '-15 minutes',
             '--no-pager', '-o', 'cat'], text=True, timeout=8, stderr=subprocess.DEVNULL)
        lines = [line for line in logs.splitlines()
                 if re.search(r'error|exception|traceback|whatsapp|bridge|send failed|timeout',
                              line, flags=re.IGNORECASE)]
        print('Errores recientes del servicio:')
        for line in lines[-12:]:
            print(' ', scrub(line[:350], token))
    except (OSError, subprocess.SubprocessError) as exc:
        print('Errores del servicio: no disponibles', scrub(exc, token))


if __name__ == '__main__':
    main()
