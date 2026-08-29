"""La cola de trabajo: qué hay que hacer, en qué workspace y en qué estado.

Hoy una tarea existe en el portapapeles de Diego y se pierde ahí. Sin un lugar donde
vivan, "distribuir trabajo a los workspaces" es copiar y pegar a mano — y el trabajo que
no se anota se rehace, que es exactamente el origen de los duplicados de `/api/vendors`
y de Vercel.

Decisiones que sostienen el diseño:

- **Alcance cerrado.** Cada tarea declara los archivos que puede tocar (`archivos`). Un
  agente sin alcance explícito refactoriza lo que se le cruce y produce un diff que
  nadie quiere revisar. Es también la defensa contra dos tareas que se pisan.
- **Un workspace, una tarea en curso.** Dos agentes escribiendo en el mismo worktree se
  pisan los archivos entre sí, sin que ninguno se entere.
- **Los intentos se cuentan.** Una tarea que el juez rechaza dos veces no se reintenta
  para siempre: se marca `atascada` y espera a un humano. Un bucle que reintenta sin
  límite quema la cuota sin producir nada.
- **Nada se borra.** Una tarea rechazada queda con su veredicto: es el registro de qué
  intentó el sistema y por qué no pasó — sin eso, mañana se vuelve a intentar lo mismo.

Almacén: un JSON local (`tareas.json`, gitignored, mismo trato que `crm.json`). Local y
no Supabase a propósito — esto coordina procesos de UNA máquina, y una cola de trabajo
que depende de la red se cae justo cuando la red se cae.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# Los estados por los que pasa una tarea. El orden es el del ciclo real.
PENDIENTE = "pendiente"        # creada, nadie la tomó
EN_CURSO = "en_curso"          # un agente está trabajando en ella
EN_REVISION = "en_revision"    # terminó, espera veredicto del juez
APROBADA = "aprobada"          # el juez la aprobó (commiteada en su rama)
RECHAZADA = "rechazada"        # el juez la rechazó; vuelve a pendiente si quedan intentos
ATASCADA = "atascada"          # agotó los intentos: la ve un humano
CANCELADA = "cancelada"        # la bajó una persona

ESTADOS = (PENDIENTE, EN_CURSO, EN_REVISION, APROBADA, RECHAZADA, ATASCADA, CANCELADA)
ABIERTOS = (PENDIENTE, EN_CURSO, EN_REVISION, RECHAZADA)

# Los estados en los que una tarea "ya está cubierta" y encolarla otra vez es rehacer
# trabajo: en la cola, en manos de un agente, esperando al juez, o ya aprobada.
# `rechazada` y `atascada` quedan fuera a propósito (reintentar lo que el juez bajó es
# legítimo), y `cancelada` también (Diego la bajó, puede querer volver a pedirla).
VIVOS = (PENDIENTE, EN_CURSO, EN_REVISION, APROBADA)

# Workspaces válidos — los mismos que sincroniza scripts/sincronizar-workspaces.sh.
WORKSPACES = ("core", "dashboard", "landing", "motor-llamadas", "motor-whatsapp", "prompts")

# Cuántas veces se reintenta una tarea que el juez rechazó, antes de dejarla quieta.
MAX_INTENTOS = 2

# Rutas que ninguna tarea puede declarar en su alcance. No es una lista de "archivos
# delicados": es la frontera entre el código y los datos/credenciales de producción.
# `.env` tiene las llaves reales; state.json y crm.json son los datos del negocio;
# deploy/ define lo que corre en la máquina.
PROHIBIDOS = (".env", "state.json", "crm.json", "users.json", "finance.json",
              "activity.json", "deploy/", ".git/")

_lock = threading.RLock()


def _ruta() -> Path:
    return Path(os.environ.get("TAREAS_PATH") or "tareas.json")


def _leer() -> List[Dict[str, Any]]:
    try:
        datos = json.loads(_ruta().read_text(encoding="utf-8"))
        return datos if isinstance(datos, list) else []
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError) as e:
        # Un archivo corrupto NO se sobreescribe en silencio: son tareas que alguien
        # escribió. Mismo criterio que crm.json — el código avisa en vez de borrar.
        raise RuntimeError(f"{_ruta()} ilegible ({e}); revísalo a mano antes de seguir")


def _escribir(tareas: List[Dict[str, Any]]) -> None:
    # Escritura atómica: un corte de luz a mitad de un write deja el archivo truncado,
    # y ahí se pierde la cola entera.
    tmp = _ruta().with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tareas, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(_ruta())


def _valida_alcance(archivos: List[str]) -> None:
    for a in archivos:
        limpio = (a or "").strip()
        if not limpio:
            continue
        if limpio.startswith("/") or ".." in limpio:
            raise ValueError(f"ruta fuera del repo: {a!r}")
        for prohibido in PROHIBIDOS:
            if limpio == prohibido or limpio.startswith(prohibido):
                raise ValueError(
                    f"{a!r} está fuera de lo que una tarea automática puede tocar "
                    f"(datos de negocio, credenciales o despliegue)")


def _clave(workspace: str, titulo: str) -> str:
    """Cómo se decide que dos tareas son 'la misma'.

    Normalización deliberadamente tosca: minúsculas, espacios colapsados y sin
    puntuación final. No intenta entender el título — un planificador que reformula
    ("Agregar rubro..." vs "Añadir el rubro...") va a colar el duplicado igual, y eso
    es aceptable: esto ataja la repetición literal, que es la que se vio en la cola.
    """
    limpio = re.sub(r"\s+", " ", (titulo or "").strip().lower())
    return f"{workspace}\x00{limpio.rstrip('.,;:!?¡¿…').strip()}"


def duplicado_de(workspace: str, titulo: str) -> Optional[Dict[str, Any]]:
    """La tarea viva que ya cubre ese (workspace, título), o None.

    Vivas = abiertas o aprobadas. `cancelada` y `rechazada` NO cuentan: bajar una tarea
    a mano o que el juez la rechace son motivos legítimos para volver a intentarla, y
    bloquear eso convertiría un rechazo en una prohibición permanente. `atascada` es un
    rechazo sin intentos: mismo criterio.
    """
    clave = _clave(workspace, titulo)
    with _lock:
        for t in _leer():
            if t.get("estado") not in VIVOS:
                continue
            if _clave(t.get("workspace", ""), t.get("titulo", "")) == clave:
                return t
    return None


def duplicados() -> List[List[Dict[str, Any]]]:
    """Los grupos de tareas vivas que comparten (workspace, título normalizado).

    Solo informa: la limpieza la decide una persona. Borrar automáticamente una tarea
    porque "se parece" a otra es exactamente el tipo de decisión que no se puede
    revertir cuando el criterio se equivoca.
    """
    with _lock:
        tareas = _leer()
    grupos: Dict[str, List[Dict[str, Any]]] = {}
    for t in tareas:
        if t.get("estado") not in VIVOS:
            continue
        grupos.setdefault(_clave(t.get("workspace", ""), t.get("titulo", "")), []).append(t)
    return [sorted(g, key=lambda t: t.get("creada", 0))
            for g in grupos.values() if len(g) > 1]


def crear(workspace: str, titulo: str, prompt: str, *,
          archivos: Optional[List[str]] = None, origen: str = "diego",
          objetivo: str = "", permitir_duplicado: bool = False) -> Dict[str, Any]:
    """Encola una tarea. `origen` distingue lo que pediste tú de lo que dedujo el
    sistema: cuando hay que recortar, lo tuyo va primero.

    Si ya hay una tarea viva con el mismo (workspace, título), **no encola nada** y
    devuelve la existente. La guardia vive acá y no en el planificador porque esta es la
    frontera real: al planificador se le pasan las tareas abiertas como contexto, pero
    eso es una sugerencia a un modelo, y cada duplicado que se cuela se come una corrida
    del cupo diario rehaciendo trabajo ya hecho. No lanza excepción: el planificador
    corre desatendido de noche y no puede caerse por esto. `permitir_duplicado=True`
    para forzar una repetición a mano.
    """
    if workspace not in WORKSPACES:
        raise ValueError(f"workspace desconocido: {workspace!r} (válidos: {list(WORKSPACES)})")
    if not (titulo or "").strip() or not (prompt or "").strip():
        raise ValueError("una tarea necesita título y prompt")
    archivos = [a.strip() for a in (archivos or []) if (a or "").strip()]
    _valida_alcance(archivos)

    tarea = {
        "id": uuid.uuid4().hex[:12],
        "creada": time.time(),
        "origen": origen,
        "objetivo": objetivo,
        "workspace": workspace,
        "titulo": titulo.strip(),
        "prompt": prompt.strip(),
        "archivos": archivos,
        "estado": PENDIENTE,
        "intentos": 0,
        "rama": "",
        "commit": "",
        "veredicto": None,
        "historial": [{"ts": time.time(), "estado": PENDIENTE, "detalle": f"creada ({origen})"}],
    }
    clave = _clave(workspace, titulo)
    with _lock:
        tareas = _leer()
        if not permitir_duplicado:
            for t in tareas:
                if t.get("estado") in VIVOS and _clave(
                        t.get("workspace", ""), t.get("titulo", "")) == clave:
                    return t
        tareas.append(tarea)
        _escribir(tareas)
    return tarea


def listar(*, workspace: Optional[str] = None, estado: Optional[str] = None,
           abiertas: bool = False) -> List[Dict[str, Any]]:
    with _lock:
        tareas = _leer()
    if workspace:
        tareas = [t for t in tareas if t.get("workspace") == workspace]
    if estado:
        tareas = [t for t in tareas if t.get("estado") == estado]
    if abiertas:
        tareas = [t for t in tareas if t.get("estado") in ABIERTOS]
    # Lo tuyo antes que lo deducido; dentro de cada grupo, lo más viejo primero (una
    # tarea que lleva días esperando no puede quedar sepultada por las recién creadas).
    tareas.sort(key=lambda t: (t.get("origen") != "diego", t.get("creada", 0)))
    return tareas


def get(tarea_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        return next((t for t in _leer() if t.get("id") == tarea_id), None)


def _actualizar(tarea_id: str, cambios: Dict[str, Any], detalle: str = "") -> Optional[Dict[str, Any]]:
    with _lock:
        tareas = _leer()
        for t in tareas:
            if t.get("id") != tarea_id:
                continue
            t.update(cambios)
            t.setdefault("historial", []).append({
                "ts": time.time(), "estado": t.get("estado"), "detalle": detalle,
            })
            _escribir(tareas)
            return t
    return None


def tomar(workspace: str) -> Optional[Dict[str, Any]]:
    """La siguiente tarea de ese workspace, marcándola en curso. None si no hay.

    Devuelve None también si ese workspace YA tiene una tarea en curso: dos agentes
    escribiendo en el mismo worktree se pisan los archivos sin enterarse.
    """
    with _lock:
        tareas = _leer()
        ocupado = any(t.get("workspace") == workspace and t.get("estado") == EN_CURSO
                      for t in tareas)
        if ocupado:
            return None
        candidatas = [t for t in tareas
                      if t.get("workspace") == workspace
                      and t.get("estado") in (PENDIENTE, RECHAZADA)]
        if not candidatas:
            return None
        candidatas.sort(key=lambda t: (t.get("origen") != "diego", t.get("creada", 0)))
        elegida = candidatas[0]
        elegida["estado"] = EN_CURSO
        elegida["intentos"] = int(elegida.get("intentos", 0)) + 1
        elegida.setdefault("historial", []).append({
            "ts": time.time(), "estado": EN_CURSO,
            "detalle": f"intento {elegida['intentos']}",
        })
        _escribir(tareas)
        return elegida


def liberar_colgadas(minutos: float = 60.0) -> List[Dict[str, Any]]:
    """Devuelve a la cola las tareas que llevan demasiado `en_curso`.

    Una tarea queda tomada para siempre si el proceso que la tomó muere a mitad: se
    apagó el PC, se cortó la luz, el agente se colgó. Y como un workspace no entrega una
    segunda tarea mientras tenga una en curso, esa tarea zombi **bloquea el workspace
    entero**, en silencio y para siempre. Es el modo de falla clásico de cualquier cola
    de trabajo, y solo se nota cuando alguien pregunta por qué hace días que no avanza
    nada por ahí.

    No gasta intentos: nadie sabe si el trabajo llegó a hacerse, y castigar a la tarea
    por una caída de luz la marcaría como fallida sin que nadie la haya juzgado.
    """
    corte = time.time() - minutos * 60.0
    liberadas: List[Dict[str, Any]] = []
    with _lock:
        tareas = _leer()
        for t in tareas:
            if t.get("estado") != EN_CURSO:
                continue
            historial = t.get("historial") or []
            desde = historial[-1].get("ts", 0) if historial else t.get("creada", 0)
            if desde > corte:
                continue
            t["estado"] = PENDIENTE
            t["intentos"] = max(0, int(t.get("intentos", 0)) - 1)
            t.setdefault("historial", []).append({
                "ts": time.time(), "estado": PENDIENTE,
                "detalle": f"liberada: llevaba más de {minutos:.0f} min en curso",
            })
            liberadas.append(t)
        if liberadas:
            _escribir(tareas)
    return liberadas


def devolver(tarea_id: str, motivo: str = "") -> Optional[Dict[str, Any]]:
    """Devuelve una tarea a la cola SIN gastarle un intento.

    Para cuando no se pudo ni empezar por algo ajeno a la tarea: el workspace estaba
    ocupado por una persona, o atrasado, o la máquina se apagó. Gastar un intento ahí
    haría que dos noches con el worktree sucio dejaran la tarea `atascada` sin que nadie
    la hubiera intentado nunca — y el registro diría que falló dos veces, que es mentira.
    """
    tarea = get(tarea_id)
    if tarea is None:
        return None
    return _actualizar(tarea_id,
                       {"estado": PENDIENTE,
                        "intentos": max(0, int(tarea.get("intentos", 0)) - 1)},
                       motivo or "devuelta a la cola sin intentarse")


def a_revision(tarea_id: str, *, rama: str = "", commit: str = "",
               detalle: str = "") -> Optional[Dict[str, Any]]:
    """El agente terminó; ahora la mira el juez."""
    return _actualizar(tarea_id, {"estado": EN_REVISION, "rama": rama, "commit": commit},
                       detalle or "trabajo terminado, esperando al juez")


def juzgar(tarea_id: str, *, aprobada: bool, veredicto: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Aplica el veredicto del juez.

    Una tarea rechazada vuelve a la cola solo si le quedan intentos; si no, queda
    `atascada` esperando a una persona. Reintentar sin límite quema la cuota repitiendo
    el mismo error — el segundo rechazo casi nunca es por mala suerte, es por una tarea
    mal especificada.
    """
    tarea = get(tarea_id)
    if tarea is None:
        return None
    if aprobada:
        return _actualizar(tarea_id, {"estado": APROBADA, "veredicto": veredicto},
                           "aprobada por el juez")
    agotada = int(tarea.get("intentos", 0)) >= MAX_INTENTOS
    return _actualizar(
        tarea_id,
        {"estado": ATASCADA if agotada else RECHAZADA, "veredicto": veredicto},
        "rechazada; sin más intentos" if agotada else "rechazada, vuelve a la cola")


def cancelar(tarea_id: str, motivo: str = "") -> Optional[Dict[str, Any]]:
    return _actualizar(tarea_id, {"estado": CANCELADA}, motivo or "cancelada a mano")


def resumen() -> Dict[str, Any]:
    """Cuántas tareas hay por estado y por workspace — la vista de un vistazo."""
    with _lock:
        tareas = _leer()
    por_estado: Dict[str, int] = {}
    por_workspace: Dict[str, Dict[str, int]] = {}
    for t in tareas:
        estado = t.get("estado", "?")
        por_estado[estado] = por_estado.get(estado, 0) + 1
        fila = por_workspace.setdefault(t.get("workspace", "?"), {})
        fila[estado] = fila.get(estado, 0) + 1
    return {"total": len(tareas), "por_estado": por_estado, "por_workspace": por_workspace,
            "abiertas": sum(1 for t in tareas if t.get("estado") in ABIERTOS)}
