#!/usr/bin/env python3
"""Patch production WhatsApp Web sends to one attempt and restart ZeroAI."""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


ROOT = Path('/home/diego/zeroai')
PATCHES = {
    ROOT / 'zero/channels.py': (
        '    return Outbox(real, wa_sender_factory=wa_factory)\n',
        '    # WhatsApp Web can deliver even if its HTTP acknowledgement times out.\n'
        '    # Retrying that send creates duplicate messages for the customer.\n'
        '    return Outbox(real, wa_sender_factory=wa_factory,\n'
        '                  retry_attempts=1 if provider == "web" else None)\n',
    ),
    ROOT / 'zero/whatsapp_web.py': (
        'with urllib.request.urlopen(req, timeout=25 if data is not None else 5) as res:',
        'with urllib.request.urlopen(req, timeout=90 if data is not None else 5) as res:',
    ),
}


def backend_pid() -> int:
    raw = subprocess.check_output(
        ['systemctl', 'show', '-p', 'MainPID', '--value', 'zero-backend'], text=True).strip()
    pid = int(raw)
    command = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\x00', b' ')
    if pid < 2 or b'uvicorn api:app' not in command:
        raise RuntimeError('No se pudo validar el proceso ZeroAI')
    return pid


def wait_for_backend(previous: int) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            current = backend_pid()
            if current != previous:
                with urllib.request.urlopen('http://127.0.0.1:8800/api/health', timeout=2) as response:
                    if response.status == 200:
                        print('Backend reiniciado y saludable.')
                        return
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
        time.sleep(1)
    raise RuntimeError('La actualización quedó instalada, pero el backend no volvió a estar saludable en 45 segundos')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='instalar y reiniciar')
    args = parser.parse_args()
    env = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines()
               if '=' in line and not line.startswith('#'))
    if (env.get('WHATSAPP_PROVIDER') != 'web' or
            env.get('OWNER_WHATSAPP_PAUSED') != '1' or
            env.get('OUTBOX_LIVE') != '1'):
        raise RuntimeError('WhatsApp Web, envío real o pausa de avisos internos no configurados')

    edits: dict[Path, str] = {}
    for path, (old, new) in PATCHES.items():
        content = path.read_text()
        if new in content:
            print(path.name, 'ya corregido')
            continue
        if content.count(old) != 1:
            raise RuntimeError(f'No se encontró el punto exacto de cambio en {path.name}')
        edited = content.replace(old, new, 1)
        compile(edited, str(path), 'exec')
        edits[path] = edited
        print(path.name, 'listo para corregir')
    if not args.apply:
        print('Comprobación completada; falta --apply para instalar.')
        return
    if not edits:
        print('La corrección ya está instalada; no se reinició el servicio.')
        return

    previous = backend_pid()
    backup = Path(tempfile.mkdtemp(prefix='zero-whatsapp-duplicados-'))
    os.chmod(backup, 0o700)
    for path, edited in edits.items():
        shutil.copy2(path, backup / path.name)
        path.write_text(edited)
    print('Archivos actualizados. Reiniciando ZeroAI…', flush=True)
    os.kill(previous, signal.SIGTERM)
    wait_for_backend(previous)
    print('WhatsApp Web: un solo intento por respuesta. Envío real sigue activado.')


if __name__ == '__main__':
    main()
