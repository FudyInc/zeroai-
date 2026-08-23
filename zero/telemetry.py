"""Qué agente corrió, con qué motor, cuánto tardó y cómo le fue.

`Zero.dispatch` ya dejaba constancia de agente/estado/notas, pero no de tiempo ni de
motor — así que no había forma de responder preguntas básicas sin adivinar: ¿está
haciendo algo el sistema ahora mismo?, ¿por qué esa respuesta demoró?, ¿está entrando el
respaldo pagado sin que nadie lo pida?

Deliberadamente chico:

- **Anillo acotado.** Se guardan los últimos `MAX_EVENTOS` y nada más. Un registro que
  crece sin límite se convierte en un archivo de cientos de MB que nadie mira y que
  algún día llena el disco de la máquina que corre producción.
- **Sin texto de mensajes.** Se guarda el TAMAÑO de la entrada y la salida, nunca su
  contenido: acá pasan mensajes de leads reales, y un log con datos personales es un
  problema legal esperando, no una métrica.
- **Nunca rompe lo que mide.** Cualquier fallo al registrar se traga: la telemetría es
  secundaria frente a responderle a un lead.
- **Caracteres, no tokens.** Contar tokens de verdad exige el tokenizador del modelo;
  para "esta llamada fue 10x más grande que aquella" los caracteres alcanzan, y no
  mienten sobre su precisión (~4 caracteres por token en español, como referencia).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_EVENTOS = 200

_lock = threading.Lock()
_eventos: List[Dict[str, Any]] = []
# Si el disco ya se leyó. Sin esta bandera, un registro vacío (arranque limpio, o un
# reset en los tests) volvería a leer el archivo en cada llamada — y en los tests
# reaparecerían los eventos de la máquina real.
_cargado = False


def _ruta() -> Path:
    return Path(os.environ.get("AGENT_TELEMETRY_PATH") or "agent_activity.json")


def _cargar() -> None:
    """Lee lo guardado una vez, al primer uso. Un archivo corrupto se ignora (esto es
    telemetría: perderla no puede romper el arranque del backend)."""
    global _cargado
    if _cargado:
        return
    _cargado = True
    try:
        datos = json.loads(_ruta().read_text(encoding="utf-8"))
        if isinstance(datos, list):
            _eventos.extend(datos[-MAX_EVENTOS:])
    except Exception:   # noqa: BLE001
        pass


def registrar(agent: str, *, status: str, ms: float, engine: str = "",
              client_id: str = "", task_id: str = "",
              in_chars: int = 0, out_chars: int = 0,
              persistir: bool = True) -> Dict[str, Any]:
    """Anota una corrida de agente y devuelve el evento. Nunca levanta."""
    evento = {
        "ts": time.time(),
        "agent": agent,
        "status": status,
        "ms": round(float(ms), 1),
        "engine": engine,
        "client_id": client_id,
        "task_id": task_id,
        "in_chars": int(in_chars),
        "out_chars": int(out_chars),
    }
    try:
        with _lock:
            _cargar()
            _eventos.append(evento)
            del _eventos[:-MAX_EVENTOS]     # el anillo: solo los últimos
            if persistir:
                try:
                    _ruta().write_text(json.dumps(_eventos, ensure_ascii=False),
                                       encoding="utf-8")
                except Exception:   # noqa: BLE001 — disco lleno / permisos
                    pass
    except Exception:   # noqa: BLE001
        pass
    return evento


def eventos(limit: int = 50, agent: Optional[str] = None) -> List[Dict[str, Any]]:
    """Los más recientes primero."""
    with _lock:
        _cargar()
        datos = list(_eventos)
    if agent:
        datos = [e for e in datos if e.get("agent") == agent]
    return list(reversed(datos))[:max(0, limit)]


def resumen() -> Dict[str, Any]:
    """Una línea por agente: cuántas corridas, cuántos errores, mediana de duración.

    Mediana y no promedio: una sola corrida lenta (el modelo cargándose en VRAM) mueve
    el promedio lo suficiente como para hacerlo inútil.
    """
    with _lock:
        _cargar()
        datos = list(_eventos)

    por_agente: Dict[str, Dict[str, Any]] = {}
    for e in datos:
        fila = por_agente.setdefault(e.get("agent") or "?", {
            "agent": e.get("agent") or "?", "corridas": 0, "errores": 0,
            "engines": set(), "ultimo": 0.0, "_ms": [],
        })
        fila["corridas"] += 1
        fila["errores"] += 1 if e.get("status") == "error" else 0
        fila["ultimo"] = max(fila["ultimo"], float(e.get("ts") or 0))
        fila["_ms"].append(float(e.get("ms") or 0))
        if e.get("engine"):
            fila["engines"].add(e["engine"])

    salida = []
    for fila in por_agente.values():
        ms = sorted(fila.pop("_ms"))
        fila["ms_mediana"] = round(ms[len(ms) // 2], 1) if ms else 0.0
        fila["ms_max"] = round(ms[-1], 1) if ms else 0.0
        fila["engines"] = sorted(fila["engines"])
        salida.append(fila)
    salida.sort(key=lambda f: f["ultimo"], reverse=True)
    return {"agentes": salida, "eventos": len(datos), "max_eventos": MAX_EVENTOS}


def reset() -> None:
    """Limpia el registro y corta la relectura del disco. Para los tests; en producción
    no se usa. Sin marcar `_cargado`, el siguiente registro volvería a traerse los
    eventos del archivo real y el test mediría la máquina, no su propio caso."""
    global _cargado
    with _lock:
        _eventos.clear()
        _cargado = True
