"""El avance de una corrida del pipeline, mientras corre.

`POST /api/pipeline` abre la request, corre discover → qualify → validate → outreach
entero y responde al final. Funciona, pero el dashboard solo puede decir "listo: 3
calificados de 12" cuando ya no hay nada que mirar: durante los minutos que de verdad
tarda la corrida, la pantalla no tiene qué mostrar. `zero/telemetry.py` tampoco sirve
para eso — registra por AGENTE (cuál corrió, cuánto tardó), nunca por empresa.

Esto es el registro que faltaba: qué empresa va en qué etapa, ahora mismo.

Decisiones que lo sostienen:

- **En memoria y por proceso.** Una corrida dura minutos y su progreso no le importa a
  nadie mañana; lo que sí perdura ya se guarda en el CRM. Persistirlo obligaría a
  escribir en disco varias veces por lead para pintar una animación, que es pagar
  almacenamiento permanente por información que caduca en cinco minutos.
- **Anillo acotado** (`MAX_CORRIDAS_RECORDADAS`), mismo criterio que telemetry: un
  registro que crece sin límite termina siendo un problema de memoria en la máquina
  que corre producción.
- **Nunca rompe lo que mide.** Anotar el progreso no puede tumbar el pipeline: si algo
  falla acá, se pierde una animación; si tumbara la corrida, se pierde el trabajo. Por
  eso el orquestador llama a esto detrás de un guardia que traga excepciones.
- **El orden de las etapas es dato, no adorno.** `ETAPAS` viaja en la respuesta para
  que el dashboard pinte la barra sin hardcodear el vocabulario del backend.
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from .config import MAX_CORRIDAS_RECORDADAS

# Por dónde pasa una empresa dentro de una corrida. En orden.
DESCUBIERTA = "descubierta"   # PROSPECTOR la encontró
CALIFICADA = "calificada"     # QUALIFIER le puso puntaje ICP
APROBADA = "aprobada"         # pasó el gate de lead calificado
DESCARTADA = "descartada"     # no pasó el gate (con sus motivos)
LISTA = "lista"               # tiene su primer mensaje escrito

ETAPAS = (DESCUBIERTA, CALIFICADA, APROBADA, DESCARTADA, LISTA)

# En qué anda la corrida entera, para el encabezado de la pantalla.
FASES = ("descubriendo", "calificando", "validando", "escribiendo", "listo")

CORRIENDO = "corriendo"
TERMINADA = "terminada"
ERROR = "error"

_lock = threading.RLock()
_corridas: Dict[str, Dict[str, Any]] = {}
_orden: List[str] = []          # ids del más viejo al más nuevo (el anillo)


def crear(client_id: str, query: str, tier: str = "") -> str:
    """Abre una corrida y devuelve su id. El id es lo único que necesita el
    dashboard para seguirla."""
    run_id = "r_" + uuid.uuid4().hex[:10]
    with _lock:
        _corridas[run_id] = {
            "run": run_id,
            "cliente": client_id,
            "consulta": query,
            "tier": tier,
            "estado": CORRIENDO,
            "fase": FASES[0],
            "empezada": time.time(),
            "terminada": None,
            "leads": {},            # empresa -> fila; se serializa como lista
            "error": None,
            "resumen": None,
        }
        _orden.append(run_id)
        # El anillo: se olvidan las corridas más viejas, nunca la que está corriendo.
        while len(_orden) > max(1, MAX_CORRIDAS_RECORDADAS):
            viejo = next((r for r in _orden
                          if _corridas.get(r, {}).get("estado") != CORRIENDO), None)
            if viejo is None:
                break
            _orden.remove(viejo)
            _corridas.pop(viejo, None)
    return run_id


def fase(run_id: str, nombre: str) -> None:
    with _lock:
        corrida = _corridas.get(run_id)
        if corrida is not None and corrida["estado"] == CORRIENDO:
            corrida["fase"] = nombre


def anotar(run_id: str, empresa: str, etapa: str, **extra: Any) -> None:
    """Mueve a una empresa de etapa. Idempotente por (corrida, empresa).

    Se guarda `desde` en cada cambio: el dashboard lo usa para animar la transición
    y para mostrar cuánto lleva una empresa atascada en la misma etapa.
    """
    nombre = (empresa or "").strip()
    if not nombre:
        return
    with _lock:
        corrida = _corridas.get(run_id)
        if corrida is None:
            return
        fila = corrida["leads"].get(nombre)
        if fila is None:
            fila = {"empresa": nombre, "etapa": etapa, "desde": time.time()}
            corrida["leads"][nombre] = fila
        elif fila["etapa"] != etapa:
            fila["etapa"] = etapa
            fila["desde"] = time.time()
        for k, v in extra.items():
            if v is not None:
                fila[k] = v


def terminar(run_id: str, *, resumen: Optional[Dict[str, Any]] = None,
             error: str = "") -> None:
    with _lock:
        corrida = _corridas.get(run_id)
        if corrida is None:
            return
        corrida["estado"] = ERROR if error else TERMINADA
        corrida["fase"] = corrida["fase"] if error else FASES[-1]
        corrida["terminada"] = time.time()
        corrida["error"] = error or None
        if resumen is not None:
            corrida["resumen"] = resumen


def progreso(run_id: str) -> Optional[Dict[str, Any]]:
    """La foto de la corrida, lista para serializar. None si no existe (o si el
    anillo ya la olvidó: para el dashboard es lo mismo)."""
    with _lock:
        corrida = _corridas.get(run_id)
        if corrida is None:
            return None
        leads = list(corrida["leads"].values())
    # Orden estable: primero lo que más avanzó, y a igualdad, lo más reciente. Una
    # lista que se reordena sola en cada refresco es imposible de leer mientras corre.
    leads.sort(key=lambda f: (ETAPAS.index(f["etapa"]) if f["etapa"] in ETAPAS else 0,
                              f.get("desde", 0)), reverse=True)
    cuenta = {e: sum(1 for f in leads if f["etapa"] == e) for e in ETAPAS}
    return {
        "run": corrida["run"],
        "cliente": corrida["cliente"],
        "consulta": corrida["consulta"],
        "estado": corrida["estado"],
        "fase": corrida["fase"],
        "empezada": corrida["empezada"],
        "terminada": corrida["terminada"],
        "segundos": round((corrida["terminada"] or time.time()) - corrida["empezada"], 1),
        "encontradas": len(leads),
        "calificadas": cuenta[APROBADA] + cuenta[LISTA],
        "descartadas": cuenta[DESCARTADA],
        "listas": cuenta[LISTA],
        "etapas": list(ETAPAS),
        "leads": leads,
        "error": corrida["error"],
        "resumen": corrida["resumen"],
    }


def ultimas(limit: int = 10) -> List[Dict[str, Any]]:
    """Las corridas que el proceso todavía recuerda, de la más nueva a la más vieja."""
    with _lock:
        ids = list(reversed(_orden))[:limit]
    return [p for p in (progreso(r) for r in ids) if p is not None]


def olvidar_todo() -> None:
    """Vacía el registro. Para los tests; en producción no se usa."""
    with _lock:
        _corridas.clear()
        _orden.clear()
