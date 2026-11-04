#!/usr/bin/env python3
"""Revisa que ZERO esté vivo y avisa al celular si algo se cayó.

Sin IA a propósito: comprobar si un puerto responde no requiere criterio. La
cuota de un modelo es lo escaso; gastarla acá sería quemar lo caro en lo barato.

Solo avisa cuando algo URGENTE falla (ver SALUD_REPETIR_MISMO_AVISO_HORAS en
zero/config.py) — un aviso por cada revisión buena entrena a
ignorarlos, y el día que importe no lo vas a mirar. El antirrebote de
`zero.alerts` evita además 48 avisos seguidos por una misma caída.

    python3 scripts/revisar-salud.py           # revisa y avisa si hay falla
    python3 scripts/revisar-salud.py --probar  # fuerza un aviso, para verificar el canal

Solo stdlib.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero._env import load_env      # noqa: E402
from zero.alerts import notify_owner  # noqa: E402
from zero.config import SALUD_REPETIR_MISMO_AVISO_HORAS  # noqa: E402

load_env()

# Marca lo que espera a una persona pero no es una caída: se informa en consola
# y en el dashboard (Atención), nunca por correo ni WhatsApp.
NO_URGENTE = "[no urgente] "

TUNEL = (os.environ.get("WHATSAPP_WEBHOOK_URL") or "https://handpick-monogamy-spiny.ngrok-free.dev/api/webhooks/whatsapp").strip()


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


def _modelo_a_probar() -> str:
    """El modelo que atiende WhatsApp, con la misma regla que api.py::_whatsapp_local_model.

    Probar otro modelo era peor que no probar: cada 30 min cargaba qwen2.5 en la GPU,
    sacaba de ahí a qwen3 (el de WhatsApp) y el siguiente cliente esperaba la recarga
    de 8,6 GB pasando por la RAM (registro de Ollama, 2026-11-03)."""
    from zero.config import WHATSAPP_ENGINE
    return ((os.environ.get("WHATSAPP_MODEL") or "").strip() or
            (os.environ.get("LOCAL_MODEL") or "").strip() or
            WHATSAPP_ENGINE["model"])


def _ollama_responde() -> bool:
    """No basta con que el puerto abra: el modelo tiene que contestar de verdad.
    Un Ollama arriba con el modelo descargado de VRAM deja al agente colgado."""
    try:
        cuerpo = json.dumps({
            "model": _modelo_a_probar(),
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


# --- prueba diaria del agente (zero-golden) -----------------------------------
# El timer de las 04:30 tiene Persistent=true, y eso no basta: en WSL la máquina a
# veces arranca, se apaga sola ~19 s después y vuelve a arrancar. La corrida atrasada
# se dispara en ese arranque efímero, muere con 'signal', y el timer la da por hecha.
# Así pasaron 6 días (10-28 → 11-03) sin una sola prueba completa. Esto mira el
# RESULTADO —la última corrida que terminó— y no si el timer disparó.
GOLDEN_UNIT = "zero-golden.service"
GOLDEN_MAX_HORAS = 26          # una al día + margen; pasado esto se relanza sola
GOLDEN_URGENTE_HORAS = 50      # dos días sin prueba ya no es un atraso: es una falla
GOLDEN_REINTENTO_MIN = 120     # no relanzar en cada revisión si la anterior sigue fallando


# Lo que probar-agente.py imprime SOLO cuando corrió los casos contra el motor (exit 0
# o 1). Con el motor caído sale con 2 sin imprimirlo, y systemd igual registra
# "Finished" (SuccessExitStatus=0 1 2): esa corrida terminó, pero no probó nada.
_GOLDEN_PROBO = ("casos dentro de las reglas", "regla(s) rota(s)")


def _journal(*args: str) -> str:
    r = subprocess.run(["journalctl", "--user", "--no-pager", *args],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "journalctl falló").strip()[:200])
    return r.stdout


def _ultima_prueba_completa():
    """Epoch (s) de la última corrida de zero-golden que PROBÓ al agente, o None.

    Completa = systemd la registró como terminada (JOB_RESULT=done; las que mataron con
    'signal' no) Y su propia salida dice que corrió los casos (`_GOLDEN_PROBO`).
    Levanta si el journal no se puede leer: un detector mudo diría "todo bien"."""
    salida = _journal(f"USER_UNIT={GOLDEN_UNIT}", "JOB_TYPE=start", "JOB_RESULT=done",
                      "-o", "json", "-r", "-n", "20")
    for linea in salida.splitlines():
        if not linea.strip():
            continue
        d = json.loads(linea)
        inv = d.get("USER_INVOCATION_ID") or d.get("INVOCATION_ID")
        if inv and any(m in _journal(f"_SYSTEMD_INVOCATION_ID={inv}", "-o", "cat")
                       for m in _GOLDEN_PROBO):
            return int(d["__REALTIME_TIMESTAMP"]) / 1e6
    return None


def _estado_golden():
    """(ActiveState, epoch del último arranque o None) de la unidad."""
    r = subprocess.run(["systemctl", "--user", "show", GOLDEN_UNIT, "--timestamp=unix",
                        "-p", "ActiveState", "-p", "InactiveExitTimestamp"],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "systemctl show falló").strip()[:200])
    props = dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l)
    ts = props.get("InactiveExitTimestamp", "").lstrip("@")
    return props.get("ActiveState", ""), (float(ts) if ts.replace(".", "").isdigit() else None)


def _prueba_diaria() -> list:
    """Si la última prueba completa del agente es más vieja que GOLDEN_MAX_HORAS, la relanza.

    Corre desde zero-salud (cada 30 min, primera vez 5 min después del arranque), o
    sea ya pasado el arranque efímero que mata a la del timer."""
    try:
        ultima = _ultima_prueba_completa()
    except Exception as e:                       # noqa: BLE001
        return [f"no se pudo leer en el journal la última prueba diaria del agente: {e}"]
    ahora = time.time()
    horas = None if ultima is None else (ahora - ultima) / 3600
    if horas is not None and horas <= GOLDEN_MAX_HORAS:
        return []
    desde = ("nunca completó una corrida que probara al agente" if ultima is None else
             "sin corrida completa desde " + datetime.fromtimestamp(ultima).strftime("%Y-%m-%d %H:%M"))
    # Lo urgente va con texto ESTABLE: main() agrupa los avisos por su texto, y uno que
    # cambia en cada revisión (horas, estado) saltaría el antirrebote cada 30 min.
    # El detalle de qué se hizo va aparte, como no urgente (se imprime, no avisa).
    fallas = [] if horas is not None and horas <= GOLDEN_URGENTE_HORAS else \
        [f"prueba diaria del agente {desde}"]
    try:
        estado, arranque = _estado_golden()
    except Exception as e:                       # noqa: BLE001
        return fallas + [f"prueba diaria del agente: no se pudo consultar su unidad: {e}"]
    if estado in ("active", "activating", "deactivating"):
        accion = "hay una corriendo ahora"
    elif arranque is not None and ahora - arranque < GOLDEN_REINTENTO_MIN * 60:
        accion = f"se relanzó hace menos de {GOLDEN_REINTENTO_MIN} min y no terminó"
    else:
        r = subprocess.run(["systemctl", "--user", "start", "--no-block", GOLDEN_UNIT],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return fallas + ["prueba diaria del agente: no se pudo relanzar: "
                             + (r.stderr or "").strip()[:200]]
        accion = "relanzada ahora"
    horas_txt = "nunca" if horas is None else f"hace {horas:.0f} h"
    return fallas + [NO_URGENTE + f"prueba diaria del agente {desde} ({horas_txt}); {accion}"]


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
    if TUNEL and not _http(TUNEL, (200, 401, 403, 405)):
        fallas.append("el túnel público no responde (WhatsApp entrante caído)")
    if not _ollama_responde():
        fallas.append("el motor local no contesta (WhatsApp caería a la API paga)")
    if os.environ.get("WHATSAPP_PROVIDER", "meta").lower() == "web":
        try:
            from zero.whatsapp_web import bridge_request, inbox_stats
            bridge = bridge_request("/status")
            if bridge.get("state") != "ready":
                fallas.append(f"puente WhatsApp Web sin conexión ({bridge.get('state') or '?'})")
            if bridge.get("pendingInbound", 0):
                fallas.append(f"puente WhatsApp Web: {bridge['pendingInbound']} mensajes aún no aceptados por el backend")
            stats = inbox_stats()
            counts = stats["counts"]
            if counts.get("needs_review", 0):
                fallas.append(NO_URGENTE + f"WhatsApp: {counts['needs_review']} mensajes requieren revisión")
            oldest = stats.get("oldest_unfinished")
            if oldest and (datetime.now(timezone.utc) -
                           datetime.fromisoformat(oldest).replace(tzinfo=timezone.utc)).total_seconds() > 300:
                fallas.append(f"WhatsApp: {counts.get('pending', 0) + counts.get('processing', 0)} mensajes llevan más de 5 minutos sin completar")
        except Exception as e:
            fallas.append(f"no se pudo verificar el puente WhatsApp Web: {e}")
    fallas.extend(_corrio_en_mock())
    fallas.extend(_prueba_diaria())
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

    urgentes = [f for f in fallas if not f.startswith(NO_URGENTE)]
    for f in fallas:
        if f.startswith(NO_URGENTE):
            print("pendiente (sin aviso):", f[len(NO_URGENTE):])
    if not urgentes:
        return 0

    texto = "ZERO tiene problemas:\n· " + "\n· ".join(urgentes)
    print(texto)
    # Una ventana por cada conjunto de problemas: el mismo se repite cada
    # SALUD_REPETIR_MISMO_AVISO_HORAS; uno distinto sale de inmediato.
    firma = hashlib.sha1("\n".join(sorted(urgentes)).encode()).hexdigest()[:10]
    res = notify_owner(texto, kind=f"salud:{firma}",
                       throttle_minutes=SALUD_REPETIR_MISMO_AVISO_HORAS * 60)
    print("aviso →", res["status"], f"({res.get('reason')})" if res.get("reason") else "")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
