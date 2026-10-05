#!/usr/bin/env python3
"""Install the WhatsApp reply parser and bridge error diagnostics in ZeroAI."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path


ROOT = Path('/home/diego/zeroai')
SOURCE_ROOT = Path(__file__).resolve().parents[1]
API = ROOT / 'api.py'
CONTRACTS = ROOT / 'zero/contracts.py'
ORCHESTRATOR = ROOT / 'zero/orchestrator.py'
TRANSPORT = ROOT / 'zero/whatsapp_web.py'
BRIDGE = ROOT / 'whatsapp-web-bridge/index.js'
LOCAL_PROMPT = ROOT / 'prompts/concierge-whatsapp-local.md'

PATCHES = {
    API: [
        (
            '    return build_agents(backend=backend, mock=False, source=source), "local"\n',
            '    agents = build_agents(backend=backend, mock=False, source=source)\n'
            '    agents["CONCIERGE"].prompt_file = "concierge-whatsapp-local.md"\n'
            '    return agents, "local"\n',
        ),
    ],
    CONTRACTS: [
        (
            '        # Qwen a veces responde con `response` (texto o {message: texto}) aunque\n'
            '        # CONCIERGE pide `reply`. Aceptamos esas formas solo para este agente;\n'
            '        # en producción se observó que una respuesta útil se perdía como error.\n'
            '        if (agent or d.get("agent")) == "CONCIERGE" and not d.get("reply"):\n'
            '            candidate = d.get("response") or d.get("message")\n'
            '            if isinstance(candidate, dict):\n'
            '                candidate = candidate.get("reply") or candidate.get("message") or candidate.get("text")\n'
            '            if isinstance(candidate, str) and candidate.strip():\n'
            '                d = {**d, "reply": candidate.strip()}\n\n',
            '',
        ),
        (
            '        status = d.get("status")\n',
            '        # Accept alternate reply keys inside either response envelope.\n'
            '        if (agent or d.get("agent")) == "CONCIERGE" and not result.get("reply"):\n'
            '            candidate = (result.get("response") or result.get("message") or\n'
            '                         result.get("text") or d.get("response") or d.get("message"))\n'
            '            for _ in range(3):\n'
            '                if not isinstance(candidate, dict):\n'
            '                    break\n'
            '                candidate = (candidate.get("reply") or candidate.get("response") or\n'
            '                             candidate.get("message") or candidate.get("text"))\n'
            '            if isinstance(candidate, str) and candidate.strip():\n'
            '                result["reply"] = candidate.strip()\n\n'
            '        status = d.get("status")\n',
        ),
    ],
    ORCHESTRATOR: [
        ('import json\nimport re\n', 'import json\nimport logging\nimport re\n'),
        (
            '        if history is None and lead and lead.get("key") and client_id:\n'
            '            history = self.memory.get_conversation(client_id, lead["key"], limit=12)\n',
            '        if history is None and lead and lead.get("key") and client_id:\n'
            '            history = self.memory.get_conversation(client_id, lead["key"], limit=12)\n'
            '        # Keep the local WhatsApp task below Ollama\'s input context limit.\n'
            '        local_whatsapp = (getattr(getattr(self, "agents", {}).get("CONCIERGE"), "prompt_file", "") ==\n'
            '                          "concierge-whatsapp-local.md")\n'
            '        lead_context = lead or {}\n'
            '        if local_whatsapp:\n'
            '            lead_context = {key: lead_context[key] for key in ("name", "role", "company")\n'
            '                            if lead_context.get(key)}\n'
            '            knowledge = knowledge[:1600]\n'
            '            history = [{"role": turn.get("role"), "text": str(turn.get("text") or "")[:300]}\n'
            '                       for turn in (history or [])[-4:]]\n',
        ),
        (
            '            data={"message": message, "lead": lead or {}, "icp": _icp_para_outreach(icp), "vendor": persona,\n',
            '            data={"message": message, "lead": lead_context, "icp": _icp_para_outreach(icp), "vendor": persona,\n',
        ),
        (
            '        resp = self.dispatch("CONCIERGE", TaskPayload(\n'
            '            agent="CONCIERGE", client_id=client_id or "", client_tier="",\n'
            '            instructions=instructions,\n'
            '            data={"message": message, "lead": lead or {}, "icp": _icp_para_outreach(icp), "vendor": persona,\n'
            '                  "knowledge": knowledge, "history": history or [],\n'
            '                  "quote": quote or {}},\n'
            '            constraints=Constraints(channels=[channel]),\n'
            '        ))\n'
            '        result = dict(resp.result or {})\n',
            '        task = TaskPayload(\n'
            '            agent="CONCIERGE", client_id=client_id or "", client_tier="",\n'
            '            instructions=instructions,\n'
            '            data={"message": message, "lead": lead or {}, "icp": _icp_para_outreach(icp), "vendor": persona,\n'
            '                  "knowledge": knowledge, "history": history or [],\n'
            '                  "quote": quote or {}},\n'
            '            constraints=Constraints(channels=[channel]),\n'
            '        )\n'
            '        resp = self.dispatch("CONCIERGE", task)\n'
            '        result = dict(resp.result or {})\n'
            '        if not isinstance(result.get("reply"), str) or not result["reply"].strip():\n'
            '            retry = TaskPayload(\n'
            '                agent="CONCIERGE", client_id=client_id or "", client_tier="",\n'
            '                instructions=instructions +\n'
            '                " Devuelve JSON con una clave reply que contenga una respuesta no vacía.",\n'
            '                data=task.data, constraints=task.constraints,\n'
            '            )\n'
            '            resp = self.dispatch("CONCIERGE", retry)\n'
            '            result = dict(resp.result or {})\n'
            '            if not isinstance(result.get("reply"), str) or not result["reply"].strip():\n'
            '                logging.error("CONCIERGE no produjo reply tras dos intentos (status=%s, keys=%s)",\n'
            '                              resp.status, sorted(result))\n',
        ),
    ],
    TRANSPORT: [
        (
            '        ("updated", "TEXT DEFAULT CURRENT_TIMESTAMP"),\n',
            '        ("updated", "TEXT"),\n',
        ),
        (
            '        if name not in columns:\n'
            '            db.execute(f"ALTER TABLE received ADD COLUMN {name} {definition}")\n',
            '        if name not in columns:\n'
            '            db.execute(f"ALTER TABLE received ADD COLUMN {name} {definition}")\n'
            '            if name == "updated":\n'
            '                db.execute("UPDATE received SET updated=created WHERE updated IS NULL")\n',
        ),
        (
            '    except urllib.error.HTTPError as exc:\n'
            '        raise RuntimeError(f"Puente WhatsApp Web: HTTP {exc.code}") from exc\n',
            '    except urllib.error.HTTPError as exc:\n'
            '        try:\n'
            '            detail = str(json.load(exc).get("error") or "")[:300]\n'
            '        except (ValueError, OSError, AttributeError):\n'
            '            detail = ""\n'
            '        raise RuntimeError(f"Puente WhatsApp Web: HTTP {exc.code}" +\n'
            '                           (f" · {detail}" if detail else "")) from exc\n',
        ),
    ],
    BRIDGE: [
        (
            '    const sent = await client.sendMessage(`${number}@c.us`, text)\n',
            '    const sent = await client.sendMessage(`${number}@c.us`, text, { sendSeen: false })\n'
            "    if (!sent) return respond(res, 502, { error: 'WhatsApp Web no confirmó el envío' })\n",
        ),
        (
            "    return respond(res, 502, { error: 'WhatsApp Web send failed' })\n",
            "    return respond(res, 502, { error: `WhatsApp Web send failed: ${err.message}` })\n",
        ),
    ],
}


def patch_content(path: Path, content: str) -> tuple[str, bool]:
    changed = False
    for old, new in PATCHES[path]:
        if new and new in content:
            continue
        if old in content:
            if content.count(old) != 1:
                raise RuntimeError(f'Punto ambiguo en {path.name}')
            content = content.replace(old, new, 1)
            changed = True
        elif not new and '        # Accept alternate reply keys inside either response envelope.\n' in content:
            continue
        elif (path == ORCHESTRATOR and old.startswith('        resp = self.dispatch("CONCIERGE", TaskPayload(')
              and '        resp = self.dispatch("CONCIERGE", task)\n' in content):
            continue
        else:
            raise RuntimeError(f'No se encontró el punto de cambio en {path.name}')
    if path.suffix == '.py':
        compile(content, str(path), 'exec')
    return content, changed


def backend_pid() -> int:
    try:
        pid = int(subprocess.check_output(
            ['systemctl', 'show', '-p', 'MainPID', '--value', 'zero-backend'],
            text=True, stderr=subprocess.DEVNULL).strip())
        if pid > 1 and b'uvicorn api:app' in Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\x00', b' '):
            return pid
    except (OSError, ValueError, subprocess.CalledProcessError):
        pass
    return 0


def wait_backend(previous: int) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            current = backend_pid()
            if current and current != previous:
                with urllib.request.urlopen('http://127.0.0.1:8800/api/health', timeout=2) as response:
                    if response.status == 200:
                        print('Backend reiniciado y saludable.')
                        return
        except (OSError, ValueError, subprocess.CalledProcessError):
            pass
        time.sleep(1)
    raise RuntimeError('La corrección quedó instalada, pero el backend no volvió a estar saludable en 45 segundos')


def wait_bridge(token: str) -> None:
    request = urllib.request.Request('http://127.0.0.1:8810/status',
                                     headers={'Authorization': f'Bearer {token}'})
    deadline = time.monotonic() + 120
    state = 'sin conexión'
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                state = json.load(response).get('state', 'desconocido')
                if state == 'ready':
                    print('WhatsApp Web conectado.')
                    return
        except (OSError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError(f'Corrección instalada; WhatsApp Web quedó en estado {state}. Revisa el QR en el dashboard')


def retry_no_reply() -> None:
    """Reprocess one recent message that never reached the send stage."""
    db_path = ROOT / 'whatsapp-web-events.sqlite3'
    with sqlite3.connect(db_path, timeout=10) as db:
        row = db.execute(
            "SELECT id, payload FROM received WHERE status='needs_review' "
            "AND error='El agente no produjo una respuesta' "
            "AND created >= datetime('now', '-1 hour') ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        if row is None:
            print('No hay un mensaje fallido sin respuesta para recuperar.')
            return
        event_id, payload = row
        if not payload or json.loads(payload).get('text', '').strip().lower() != 'hola prueba 3':
            print('El último mensaje fallido es distinto; no se reenvió nada.')
            return
        db.execute(
            "UPDATE received SET status='pending', error=NULL, updated=CURRENT_TIMESTAMP "
            "WHERE id=? AND status='needs_review' AND error='El agente no produjo una respuesta'",
            (event_id,),
        )
    print('Reprocesando «Hola prueba 3» con el modelo local…', flush=True)
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        with sqlite3.connect(db_path, timeout=10) as db:
            status, error = db.execute('SELECT status, error FROM received WHERE id=?',
                                       (event_id,)).fetchone()
        if status in ('completed', 'needs_review'):
            print('Resultado del mensaje:', status, error or '')
            return
        time.sleep(2)
    print('El mensaje sigue en proceso; revisa su resultado en el dashboard.')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--retry', action='store_true',
                        help='reprocesar el mensaje de prueba identificado, con envío real')
    args = parser.parse_args()
    env = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines()
               if '=' in line and not line.startswith('#'))
    if env.get('WHATSAPP_PROVIDER') != 'web' or env.get('OUTBOX_LIVE') != '1':
        raise RuntimeError('WhatsApp Web y envío real deben estar activos')
    unit = Path('/etc/systemd/system/zero-backend.service').read_text()
    if ('WorkingDirectory=/home/diego/zeroai' not in unit or
            'ExecStart=/usr/bin/python3 -m uvicorn api:app' not in unit or
            'Restart=always' not in unit):
        raise RuntimeError('El servicio zero-backend ya no coincide con la instalación esperada')
    edits: dict[Path, tuple[str, str]] = {}
    for path in PATCHES:
        original = path.read_text()
        content, changed = patch_content(path, original)
        if changed:
            edits[path] = (original, content)
            print(path.relative_to(ROOT), 'listo')
        else:
            print(path.relative_to(ROOT), 'ya corregido')
    prompt_content = (SOURCE_ROOT / 'prompts/concierge-whatsapp-local.md').read_text()
    prompt_original = LOCAL_PROMPT.read_text() if LOCAL_PROMPT.exists() else ''
    if prompt_original != prompt_content:
        edits[LOCAL_PROMPT] = (prompt_original, prompt_content)
        print(LOCAL_PROMPT.relative_to(ROOT), 'listo')
    if not args.apply:
        print('Comprobación completada; falta --apply para instalar.')
        return
    if not edits:
        print('La corrección ya está instalada.')
        if args.retry:
            retry_no_reply()
        return
    if BRIDGE in edits:
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False) as handle:
            temp_js = Path(handle.name)
            handle.write(edits[BRIDGE][1])
        try:
            subprocess.run(['node', '--check', str(temp_js)], check=True, timeout=10)
        finally:
            temp_js.unlink(missing_ok=True)
    previous = backend_pid()
    if any((path.read_text() if path.exists() else '') != original
           for path, (original, _) in edits.items()):
        raise RuntimeError('Un archivo cambió durante la comprobación; ejecuta el comando de nuevo')
    backup = Path(tempfile.mkdtemp(prefix='zero-whatsapp-respuesta-'))
    os.chmod(backup, 0o700)
    for path, (_, content) in edits.items():
        target = backup / path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    print('Corrección instalada. Esperando ZeroAI…', flush=True)
    if previous:
        os.kill(previous, signal.SIGTERM)
    wait_backend(previous)
    print('Esperando reconexión de WhatsApp Web…', flush=True)
    wait_bridge(env.get('WHATSAPP_WEB_BRIDGE_TOKEN', ''))
    if args.retry:
        retry_no_reply()
    print('Envío real sigue activado. Copias de respaldo:', backup)


if __name__ == '__main__':
    main()
