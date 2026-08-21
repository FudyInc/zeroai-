#!/usr/bin/env python3
"""Revisa que ZERO esté vivo y avisa al celular si algo se cayó.

Sin IA a propósito: comprobar si un puerto responde no requiere criterio. La
cuota de un modelo es lo escaso; gastarla acá sería quemar lo caro en lo barato.

Solo avisa cuando algo FALLA — un aviso por cada revisión buena entrena a
ignorarlos, y el día que importe no lo vas a mirar. El antirrebote de
`zero.alerts` evita además 48 avisos seguidos por una misma caída.

    python3 scripts/revisar-salud.py           # revisa y avisa si hay falla
    python3 scripts/revisar-salud.py --probar  # fuerza un aviso, para verificar el canal

Solo stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero._env import load_env      # noqa: E402
from zero.alerts import notify_owner  # noqa: E402

load_env()

TUNEL = (os.environ.get("TWILIO_WEBHOOK_URL") or "").strip()


def _servicio(nombre: str, usuario: bool = False) -> bool:
    cmd = ["systemctl"] + (["--user"] if usuario else []) + ["is-active", "--quiet", nombre]
    return subprocess.run(cmd).returncode == 0


def _http(url: str, esperados: tuple, timeout: float = 12.0) -> bool:
    """True si responde alguno de los códigos esperados. Un 401 en una ruta con
    login es señal de SALUD, no de falla: el servicio está y está protegido."""
    req = urllib.request.Request(url, headers={"ngrok-skip-browser-warning": "true"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status in esperados
    except urllib.error.HTTPError as e:
        return e.code in esperados
    except Exception:
        return False


def _ollama_responde() -> bool:
    """No basta con que el puerto abra: el modelo tiene que contestar de verdad.
    Un Ollama arriba con el modelo descargado de VRAM deja al agente colgado."""
    try:
        cuerpo = json.dumps({
            "model": os.environ.get("LOCAL_MODEL", "qwen2.5:14b-instruct-q4_K_M"),
            "messages": [{"role": "user", "content": "di ok"}],
            "max_tokens": 5,
        }).encode()
        req = urllib.request.Request(
            "http://localhost:11434/v1/chat/completions", data=cuerpo,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:
            return bool(json.loads(r.read())["choices"][0]["message"]["content"])
    except Exception:
        return False


def revisar() -> list:
    fallas = []
    for s in ("zero-backend", "zero-tunnel", "ollama"):
        if not _servicio(s):
            fallas.append(f"el servicio {s} está caído")
    if not _servicio("zero-dashboard", usuario=True):
        fallas.append("el dashboard está caído")
    # 401 = vivo y pidiendo login. Solo un fallo de conexión es problema.
    if not _http("http://localhost:8800/api/config", (200, 401)):
        fallas.append("el backend no responde en :8800")
    if TUNEL and not _http(TUNEL, (200, 401, 405)):
        fallas.append("el túnel público no responde (WhatsApp entrante caído)")
    if not _ollama_responde():
        fallas.append("el motor local no contesta (WhatsApp caería a la API paga)")
    return fallas


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probar", action="store_true",
                    help="manda un aviso de prueba y sale (para verificar el canal)")
    args = ap.parse_args()

    if args.probar:
        res = notify_owner("ZERO: aviso de prueba. Si te llegó, el canal funciona.",
                           kind="prueba", throttle_minutes=0)
        print("aviso de prueba →", res["status"],
              "" if res["status"] == "sent" else f"({res.get('reason')})")
        return 0

    fallas = revisar()
    if not fallas:
        print("todo en orden")
        return 0

    texto = "ZERO tiene problemas:\n· " + "\n· ".join(fallas)
    print(texto)
    res = notify_owner(texto, kind="salud")
    print("aviso →", res["status"], f"({res.get('reason')})" if res.get("reason") else "")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
