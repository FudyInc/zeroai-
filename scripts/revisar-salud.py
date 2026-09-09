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
import time
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


# Cuánto atrás se mira para decidir si algo corrió en mock. El timer es de 30 min:
# una ventana un poco mayor evita que un evento caiga justo entre dos revisiones.
VENTANA_MOCK_MIN = 45

# Clientes que NO son producción. Sin excluirlos el detector gritaría por el trabajo
# de la propia casa, y un aviso que suena siempre se ignora justo el día que importa.
#
#   auditoria → scripts/auditar.py:99 corre el pipeline en mock contra este cliente en
#               CADA auditoría, o sea al menos una vez al día.
#   acme      → el cliente del comando canónico de CLAUDE.md, el que se teclea a mano
#               para probar algo.
#
# La suite ya no aparece acá: desde tests/__init__.py escribe su telemetría en un
# temporal, no en la de producción. Antes inventaba client_id propios (`listable`,
# `vocabulario`, `veloz`) y no había forma de excluirlos por nombre.
CLIENTES_NO_PRODUCCION = ("auditoria", "acme")


def _corrio_en_mock() -> list:
    """Agentes que corrieron con motor mock en la última ventana.

    Este es el detector, y la razón por la que existe: ZERO dejó de ser mock-first el
    2026-09-08 y ya no debería haber un solo agente respondiendo con plantillas. Pero
    apagar el mock en `api.py` cierra las puertas que conozco — no prueba que no quede
    otra. Esto mira el resultado en vez de la intención: si algo respondió en mock, se
    ve acá, venga de donde venga.

    Es distinto de comprobar que Ollama responde. Ollama puede estar arriba y un agente
    igual haber caído a mock por otro camino: una ruta que se saltó `_agents_best`, un
    proceso viejo levantado antes del cambio, o `ZERO_PIPELINE_MOCK_OK` filtrado a un
    .env. Los tres son silenciosos y los tres se ven en la telemetría.
    """
    try:
        from zero import telemetry
        eventos = telemetry.eventos(limit=200)
    except Exception as e:                       # noqa: BLE001
        # Un detector que se cae en silencio es peor que no tenerlo: se diría igual
        # que "todo bien". Que su propia falla sea una falla reportada.
        return [f"no se pudo leer la telemetría para detectar mocks: {e}"]

    corte = time.time() - VENTANA_MOCK_MIN * 60
    culpables = sorted({e.get("agent") or "?" for e in eventos
                        if (e.get("engine") or "") == "mock"
                        and (e.get("ts") or 0) >= corte
                        and (e.get("client_id") or "") not in CLIENTES_NO_PRODUCCION})
    if not culpables:
        return []
    return [f"corrieron en MOCK en los últimos {VENTANA_MOCK_MIN} min: "
            + ", ".join(culpables)
            + " — el motor real falló o algo se saltó la puerta de api.py"]


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
    fallas.extend(_corrio_en_mock())
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
