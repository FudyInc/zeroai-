#!/usr/bin/env python3
"""Activate ZeroAI's WhatsApp Web outbox while keeping owner alerts paused."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


ROOT = Path('/home/diego/zeroai')
ENV = ROOT / '.env'


def settings() -> dict[str, str]:
    return dict(line.split('=', 1) for line in ENV.read_text().splitlines()
                if '=' in line and not line.startswith('#'))


def set_outbox(value: str) -> None:
    lines = ENV.read_text().splitlines()
    matches = [i for i, line in enumerate(lines) if line.startswith('OUTBOX_LIVE=')]
    if len(matches) != 1:
        raise RuntimeError('OUTBOX_LIVE debe aparecer exactamente una vez')
    lines[matches[0]] = f'OUTBOX_LIVE={value}'
    with tempfile.NamedTemporaryFile('w', dir=ROOT, prefix='.env-whatsapp-',
                                     delete=False) as handle:
        tmp = Path(handle.name)
        os.fchmod(handle.fileno(), 0o600)
        handle.write('\n'.join(lines) + '\n')
    os.replace(tmp, ENV)


def backend_pid() -> int:
    raw = subprocess.check_output(
        ['systemctl', 'show', '-p', 'MainPID', '--value', 'zero-backend'], text=True).strip()
    pid = int(raw)
    if pid < 2 or b'uvicorn api:app' not in Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\x00', b' '):
        raise RuntimeError('No se pudo validar el proceso ZeroAI')
    return pid


def restart_and_wait() -> None:
    previous = backend_pid()
    os.kill(previous, signal.SIGTERM)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            current = backend_pid()
            if current != previous:
                with urllib.request.urlopen('http://127.0.0.1:8800/api/health', timeout=2) as response:
                    if json.load(response).get('ok'):
                        return
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
        time.sleep(1)
    raise RuntimeError('ZeroAI no volvió a estar saludable en 45 segundos')


def bridge_ready(secret: str) -> bool:
    request = urllib.request.Request('http://127.0.0.1:8810/status',
                                     headers={'Authorization': f'Bearer {secret}'})
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                if json.load(response).get('state') == 'ready':
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--activate', action='store_true', help='activar y reiniciar')
    args = parser.parse_args()
    current = settings()
    print('Estado:', {'provider': current.get('WHATSAPP_PROVIDER'),
                      'outbox_live': current.get('OUTBOX_LIVE'),
                      'owner_alerts_paused': current.get('OWNER_WHATSAPP_PAUSED')})
    if not args.activate:
        return
    if current.get('WHATSAPP_PROVIDER') != 'web' or current.get('OWNER_WHATSAPP_PAUSED') != '1':
        raise RuntimeError('No activar: proveedor Web o pausa de avisos no configurados')
    if len(current.get('WHATSAPP_WEB_BRIDGE_TOKEN', '')) < 32:
        raise RuntimeError('No activar: falta la clave del puente')
    if not (ROOT / 'whatsapp-web-bridge/index.js').exists():
        raise RuntimeError('No activar: falta el puente')
    if 'Qwen a veces responde' not in (ROOT / 'zero/contracts.py').read_text():
        raise RuntimeError('No activar: falta la corrección del formato del agente')
    if current.get('OUTBOX_LIVE') == '1':
        print('Ya estaba activo.')
        return
    set_outbox('1')
    try:
        restart_and_wait()
        if not bridge_ready(current['WHATSAPP_WEB_BRIDGE_TOKEN']):
            raise RuntimeError('El puente no reconectó el número')
    except Exception:
        set_outbox('0')
        try:
            restart_and_wait()
        except Exception:
            pass
        raise
    print('Activado: backend sano, WhatsApp Web conectado, avisos al dueño pausados.')


if __name__ == '__main__':
    main()
