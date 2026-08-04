"""Conductor — lanza y monitorea sesiones del CLI real `claude` desde el
dashboard, una por rol de trabajo del proyecto (mismos 6 roles que hoy usan
los scripts `*-terminal.sh`: AGENTS, WORKER, DEBUG, DESIGN, PROMPTS,
CONSULTAS). Es la versión integrada de lo que hoy se hace a mano abriendo
pestañas de Ptyxis con `zero-terminals.sh` — mismos roles, mismos prompts,
mismos modelos, pero visibles y controlables desde el dashboard.

Diseño: cada sesión es UN proceso `claude -p` real, lanzado con
`--input-format stream-json --output-format stream-json --verbose` (NO pty,
NO terminal emulada) — se mantiene vivo entre turnos escribiendo una línea
JSON a stdin por turno y leyendo eventos JSON estructurados de stdout. Mismo
criterio que zero/sandbox.py: invocar el binario real vía subprocess, sin SDK
de por medio.

**Honestidad sobre la "zona de escritura" de cada rol**: es SOLO una
instrucción en el system-prompt (`write_zone_hint` abajo, informativo). No
hay sandboxing de filesystem — ni acá ni en los `.sh` que ya existen hoy. Un
rol podría, en teoría, tocar cualquier archivo del worktree si el modelo
decide ignorar la instrucción. No se finge una barrera que no existe.

**Por qué `acceptEdits`**: en modo headless no hay TTY para que Claude Code
muestre un prompt interactivo de "¿permito esto?" — cualquier permission-mode
que dependa de una respuesta humana en vivo se cuelga para siempre. Por
diseño, toda sesión corre con `--permission-mode acceptEdits` salvo que el rol
traiga su propio modo (CONSULTAS ya usa `plan`, solo lectura). Es un cambio de
comportamiento real frente a la terminal interactiva a mano: las ediciones se
auto-aceptan.

Registro de sesiones: en memoria, efímero — muere si se reinicia el backend,
igual que las pestañas de terminal hoy. Nada de esto se persiste a disco.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

# El backend carga zero/_env.py::load_env() al arrancar, que mete el .env del
# proyecto (ANTHROPIC_API_KEY entre otras, para el modo --live del pipeline
# de leads) en os.environ del proceso de api.py. asyncio.create_subprocess_exec
# hereda ESE entorno completo por defecto — confirmado en vivo, 2026-08-04:
# con un ANTHROPIC_API_KEY de prueba en .env, el CLI `claude` la prefiere por
# sobre su login normal (OAuth) y falla con "Invalid API key". Se excluyen acá
# para que la sesión headless se autentique exactamente igual que cuando un
# humano corre `claude` a mano en una terminal (donde el .env de este proyecto
# nunca llega al shell).
_STRIP_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def _subprocess_env() -> Dict[str, str]:
    env = dict(os.environ)
    for key in _STRIP_ENV_VARS:
        env.pop(key, None)
    return env


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- catálogo de roles ---------------------------------------------------
# Copiado literal de los `*-terminal.sh` (no parseado en runtime — más simple
# y robusto para v1; si el texto de un `.sh` cambia, hay que actualizar acá
# también a mano). `uso-terminal.sh` queda fuera: es un panel de métricas
# (btop + ccusage), no un agente lanzable.

# Modelos elegibles al lanzar una sesión. El criterio es el de siempre en este
# repo: el más barato que alcance (ver la política de selección de modelo —
# mecánico -> haiku, implementación -> sonnet, arquitectura -> el potente).
# Cada rol trae un `default_model` sugerido, pero quien lanza puede cambiarlo:
# el rol define QUÉ toca, el modelo cuánto piensa. Son ejes distintos.
#
# Todos corren contra la suscripción de Claude Code ya pagada (costo marginal
# cero), NO contra el modelo local de Ollama: el CLI `claude` habla con
# Anthropic. El motor local mueve el pipeline de leads (zero/backends.py::
# LocalBackend), que es otra ruta de ejecución — no se mezclan acá para no
# ofrecer como equivalentes dos cosas que no lo son (un 14B no maneja de forma
# confiable el bucle de herramientas de Claude Code).
MODELS: List[Dict[str, Any]] = [
    {"id": "opus", "label": "Opus", "engine": "claude", "tools": True,
     "hint": "Arquitectura y decisiones difíciles"},
    {"id": "sonnet", "label": "Sonnet", "engine": "claude", "tools": True,
     "hint": "Implementación y refactors"},
    {"id": "haiku", "label": "Haiku", "engine": "claude", "tools": True,
     "hint": "Tareas mecánicas y repetitivas"},
]

LOCAL_MODEL_ID = "local"


def _local_config() -> Optional[Dict[str, str]]:
    """El modelo local se configura con las MISMAS variables que usa el
    pipeline de leads (LOCAL_MODEL / LOCAL_MODEL_URL, ver main.py y
    zero/backends.py) — una sola fuente de verdad para "cuál es el modelo
    local de esta máquina". Sin LOCAL_MODEL configurado, no se ofrece."""
    name = (os.environ.get("LOCAL_MODEL") or "").strip()
    if not name:
        return None
    base = (os.environ.get("LOCAL_MODEL_URL") or "http://localhost:11434/v1").strip().rstrip("/")
    return {"model": name, "endpoint": f"{base}/chat/completions", "base": base}


_LOCAL_PROBE: Dict[str, Any] = {"at": 0.0, "ok": False}
_LOCAL_PROBE_TTL = 30.0


def _local_reachable(force: bool = False) -> bool:
    """Sonda cacheada al endpoint local. Barata (es localhost) pero no gratis,
    así que no se repite en cada carga de la página. Nunca lanza: si el
    servidor de modelos está caído, la opción simplemente no se ofrece en vez
    de romper el catálogo entero."""
    cfg = _local_config()
    if cfg is None:
        return False
    now = time.time()
    if not force and now - _LOCAL_PROBE["at"] < _LOCAL_PROBE_TTL:
        return bool(_LOCAL_PROBE["ok"])
    ok = False
    try:
        with urllib.request.urlopen(f"{cfg['base']}/models", timeout=1.5) as r:
            ok = r.status == 200
    except Exception:
        ok = False
    _LOCAL_PROBE.update({"at": now, "ok": ok})
    return ok


def models_catalog() -> List[Dict[str, Any]]:
    """Los tres de Claude Code (suscripción ya pagada, con herramientas) más,
    si esta máquina lo tiene levantado, el modelo local (gratis, sin
    herramientas). Van en la misma lista a propósito: la elección real es "qué
    cerebro mueve esta terminal", y el `tools: False` es lo que evita que se
    lean como equivalentes."""
    models = [dict(m) for m in MODELS]
    cfg = _local_config()
    if cfg and _local_reachable():
        models.append({
            "id": LOCAL_MODEL_ID,
            "label": f"{cfg['model'].split(':')[0]} · local",
            "engine": "local",
            "tools": False,
            "hint": "Gratis en tu GPU — conversa, pero no toca archivos",
        })
    return models


def _model_ids() -> Set[str]:
    return {m["id"] for m in models_catalog()}


@dataclass
class RoleDef:
    id: str
    label: str
    default_model: Optional[str]    # sugerido; None = default del CLI. Overridable al lanzar.
    permission_mode: Optional[str]  # None -> se resuelve a "acceptEdits" al lanzar
    system_prompt: str
    write_zone_hint: str            # informativo, no enforced
    relaunch_on_exit: bool = False  # True solo en DEBUG (mismo loop que su .sh)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "default_model": self.default_model,
            "permission_mode": self.permission_mode or "acceptEdits",
            "write_zone_hint": self.write_zone_hint,
            "relaunch_on_exit": self.relaunch_on_exit,
        }


_ROLE_LIST: List[RoleDef] = [
    RoleDef(
        id="agents", label="AGENTS", default_model="sonnet", permission_mode=None,
        write_zone_hint="zero/agents/",
        system_prompt=(
            "Eres la terminal 🤖 AGENTS del proyecto ZERO. Implementas y afinas los "
            "sub-agentes en zero/agents/. Tu zona de escritura es zero/agents/. Respeta "
            "los contratos de salida JSON en zero/contracts.py. NO toques api.py, "
            "main.py, tests/ ni prompts/. Responde en español, conciso."
        ),
    ),
    RoleDef(
        id="worker", label="WORKER", default_model="sonnet", permission_mode=None,
        write_zone_hint="api.py, main.py, zero/ (excepto zero/agents/)",
        system_prompt=(
            "Eres la terminal 🔨 WORKER del proyecto ZERO. Implementas y modificas la "
            "API y el core: api.py, main.py y el paquete zero/ (excepto zero/agents/, "
            "que lleva la terminal AGENTS). NO toques tests/ (eso es DEBUG), prompts/ "
            "(eso es PROMPTS) ni frontend/web/ (eso va en Claude Design). Respeta los "
            "contratos de zero/contracts.py. Responde en español, conciso."
        ),
    ),
    RoleDef(
        id="debug", label="DEBUG", default_model="sonnet", permission_mode=None,
        write_zone_hint="tests/",
        relaunch_on_exit=True,
        system_prompt=(
            "Eres la terminal 🔍 DEBUG del proyecto ZERO. Escribes y corres tests y "
            "diagnosticas fallos. Tu zona de escritura es tests/. Puedes LEER cualquier "
            "archivo del repo para entender el fallo, pero solo MODIFICAS tests/ (si el "
            "arreglo es de código, propónselo a WORKER en vez de editar tú zero/ o "
            "api.py). Responde en español, conciso."
        ),
    ),
    RoleDef(
        id="design", label="DESIGN", default_model="sonnet", permission_mode=None,
        write_zone_hint="frontend/, web/",
        system_prompt=(
            "Eres la terminal 🎨 DESIGN del proyecto ZERO. Diseñas e implementas el "
            "frontend del dashboard: tu zona de escritura es frontend/ y web/. Consumes "
            "la API de api.py — el contrato de la sección Agentes WhatsApp está en "
            "docs/contrato-api-agentes.md (léelo antes de construir esa sección). La UI "
            "es para trabajadores que NO saben de IA: simple, en español, sin jerga. NO "
            "toques api.py, main.py, zero/, tests/ ni prompts/. Responde en español, "
            "conciso."
        ),
    ),
    RoleDef(
        id="prompts", label="PROMPTS", default_model="haiku", permission_mode=None,
        write_zone_hint="prompts/*.md, PROMPTS_*.md",
        system_prompt=(
            "Eres la terminal 📝 PROMPTS del proyecto ZERO. Tu único trabajo es "
            "escribir, revisar y afinar prompts. SOLO tocas: prompts/*.md y los "
            "archivos PROMPTS_*.md. NO toques zero/, tests/, frontend/, api.py ni "
            "main.py. Cada prompt debe ser fiel al contrato de salida JSON del agente "
            "correspondiente (mira zero/contracts.py y la clase del agente en "
            "zero/agents/ antes de editar su prompt, pero sin modificarlos). Responde "
            "en español, conciso."
        ),
    ),
    RoleDef(
        id="consultas", label="CONSULTAS", default_model="sonnet", permission_mode="plan",
        write_zone_hint="solo lectura (--permission-mode plan)",
        system_prompt=(
            "Eres la terminal 🔎 CONSULTAS del proyecto ZERO. Tu trabajo es responder "
            "preguntas sobre el código y la arquitectura: explicar, ubicar "
            "(archivo:línea), comparar opciones y proponer planes. NO edites archivos "
            "ni corras comandos que cambien estado; estás en modo plan. Responde en "
            "español, conciso, con referencias a archivo:línea."
        ),
    ),
]

ROLES: Dict[str, RoleDef] = {r.id: r for r in _ROLE_LIST}


def roles_catalog() -> List[Dict[str, Any]]:
    return [r.to_dict() for r in _ROLE_LIST]


# --- disponibilidad + worktrees --------------------------------------------

def is_available() -> Tuple[bool, Optional[str]]:
    """False en cualquier entorno sin filesystem/proceso real (ej. Render) —
    nunca lanza, el caller lo usa como gate antes de ofrecer la función."""
    if shutil.which("claude") is None:
        return False, "el CLI `claude` no está instalado en este servidor"
    try:
        subprocess.run(["git", "worktree", "list"], cwd=REPO_ROOT,
                       capture_output=True, timeout=5, check=True)
    except Exception:
        return False, "no se pudo listar los worktrees de git en este servidor"
    return True, None


def list_worktrees() -> List[Dict[str, str]]:
    """Worktrees reales del repo (`git worktree list --porcelain`), corrido en
    runtime — nunca hardcodeado, para que escale solo cuando se agreguen más
    worktrees/motores. Nunca lanza: cualquier fallo -> lista vacía."""
    try:
        out = subprocess.run(
            ["git", "worktree", "list", "--porcelain"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
    except Exception:
        return []
    worktrees: List[Dict[str, str]] = []
    path: Optional[str] = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):].strip()
        elif line.startswith("branch ") and path:
            branch = line[len("branch "):].strip().removeprefix("refs/heads/")
            worktrees.append({"path": path, "branch": branch})
            path = None
    return worktrees


def _branch_for(path: str) -> Optional[str]:
    for wt in list_worktrees():
        if wt["path"] == path:
            return wt["branch"]
    return None


# --- guard: un solo lanzamiento activo por (rol, worktree) -----------------

class SessionGuard:
    """Mismo criterio que zero/functions.py::RunGuard, con clave compuesta
    (role_id, worktree_path) en vez de function_id."""

    def __init__(self) -> None:
        self._active: Dict[Tuple[str, str], str] = {}

    def try_start(self, key: Tuple[str, str], session_id: str) -> bool:
        if key in self._active:
            return False
        self._active[key] = session_id
        return True

    def finish(self, key: Tuple[str, str]) -> None:
        self._active.pop(key, None)

    def existing(self, key: Tuple[str, str]) -> Optional[str]:
        return self._active.get(key)


class SessionAlreadyRunning(Exception):
    """Ya hay una sesión activa para ese (rol, worktree) — el caller debe
    'adjuntarse' a existing_session_id en vez de lanzar una segunda."""

    def __init__(self, existing_session_id: str):
        super().__init__(f"ya hay una sesión corriendo: {existing_session_id}")
        self.existing_session_id = existing_session_id


_GUARD = SessionGuard()
_LOCK = asyncio.Lock()


# --- sesión ------------------------------------------------------------------

class BaseSession:
    """Lo común a los dos motores: identidad, estado, buffer de replay y
    suscriptores. Las dos subclases emiten EXACTAMENTE el mismo contrato de
    eventos (`user`, `stream_event`, `assistant`, `result`, `status`) — por eso
    el WebSocket, el replay y toda la UI del chat funcionan igual con
    cualquiera de los dos sin saber cuál es."""

    engine = "claude"
    tools = True

    def __init__(self, session_id: str, role_id: str, worktree_path: str,
                 worktree_branch: Optional[str],
                 started_by: Optional[Dict[str, Any]], model: Optional[str] = None) -> None:
        self.id = session_id
        self.role_id = role_id
        self.model = model
        self.worktree_path = worktree_path
        self.worktree_branch = worktree_branch
        self.started_by = started_by
        self.status = "running"
        self.started_at = _now_iso()
        self.ended_at: Optional[str] = None
        # Id de sesión del CLI. Vive en la base (no en Session) porque
        # _record_event es compartido por los dos motores; en el local se queda
        # en None para siempre, que es exactamente la verdad.
        self.claude_session_id: Optional[str] = None
        self.turn_in_flight = False
        self.messages: Deque[Dict[str, Any]] = deque(maxlen=500)
        self.stderr_tail: Deque[str] = deque(maxlen=50)
        self.subscribers: Set["asyncio.Queue[Dict[str, Any]]"] = set()
        self.stop_requested = False

    def summary(self) -> Dict[str, Any]:
        role = ROLES.get(self.role_id)
        return {
            "id": self.id,
            "role_id": self.role_id,
            "role_label": role.label if role else self.role_id,
            "engine": self.engine,
            "tools": self.tools,
            "model": self.model,
            "worktree_path": self.worktree_path,
            "worktree_branch": self.worktree_branch,
            "pid": getattr(self, "pid", None),
            "status": self.status,
            "started_at": self.started_at,
            "started_by": self.started_by,
            "ended_at": self.ended_at,
            "exit_code": getattr(self, "exit_code", None),
            "turn_in_flight": self.turn_in_flight,
            "claude_session_id": getattr(self, "claude_session_id", None),
        }


class Session(BaseSession):
    """Motor `claude`: un proceso real del CLI, con herramientas (lee, edita,
    corre comandos). Efímera: no se persiste a disco, muere con el backend."""

    engine = "claude"
    tools = True

    def __init__(self, session_id: str, role_id: str, worktree_path: str,
                 worktree_branch: Optional[str], process: "asyncio.subprocess.Process",
                 started_by: Optional[Dict[str, Any]], model: Optional[str] = None) -> None:
        super().__init__(session_id, role_id, worktree_path, worktree_branch,
                         started_by, model=model)
        self.process = process
        self.pid = process.pid
        self.exit_code: Optional[int] = None
        self.reader_task: Optional[asyncio.Task] = None
        self.stderr_task: Optional[asyncio.Task] = None


class LocalSession(BaseSession):
    """Motor local (Ollama, GPU de esta máquina): gratis e ilimitado, pero
    SIN herramientas — no lee ni edita archivos, no corre comandos. Solo
    conversa sobre lo que le pegues en el mensaje.

    Es una diferencia real, no un matiz: un 14B no sostiene de forma confiable
    el bucle de herramientas de Claude Code, y fingir que sí haría que el
    modelo dijera "ya revisé api.py" sin haberlo abierto nunca. Por eso `tools`
    es False, la UI lo muestra, y el system prompt se lo dice explícitamente
    (ver _local_system_prompt).

    No hay proceso: la conversación vive en `history` y cada turno es una
    llamada HTTP en streaming al endpoint OpenAI-compatible."""

    engine = "local"
    tools = False

    def __init__(self, session_id: str, role_id: str, worktree_path: str,
                 worktree_branch: Optional[str],
                 started_by: Optional[Dict[str, Any]], model: Optional[str] = None,
                 endpoint: str = "", model_name: str = "") -> None:
        super().__init__(session_id, role_id, worktree_path, worktree_branch,
                         started_by, model=model)
        self.endpoint = endpoint
        self.model_name = model_name
        self.history: List[Dict[str, str]] = []
        self.turn_task: Optional[asyncio.Task] = None


_SESSIONS: Dict[str, BaseSession] = {}


def list_sessions() -> List[Dict[str, Any]]:
    return [s.summary() for s in _SESSIONS.values()]


def get_session(session_id: str) -> Optional[Session]:
    return _SESSIONS.get(session_id)


def delete_session(session_id: str) -> bool:
    session = _SESSIONS.get(session_id)
    if session is None:
        return False
    if session.status in ("running", "starting"):
        raise RuntimeError("no se puede borrar una sesión corriendo — deténla primero")
    del _SESSIONS[session_id]
    return True


# --- ciclo de vida del proceso ------------------------------------------------

def _record_event(session: Session, event: Dict[str, Any], *, store: bool = True) -> None:
    """`store=False` reparte el evento a los suscriptores vivos pero NO lo deja
    en el buffer de replay. Es lo que se hace con los `stream_event` (los
    deltas token a token de --include-partial-messages): son miles por turno y
    llenarían los 500 slots del deque en un par de frases, tirando afuera el
    historial de verdad. El texto completo llega igual en el evento
    `assistant` que cierra cada bloque — ESE sí se guarda, y es el que se
    reproduce al reabrir la sesión."""
    if event.get("type") == "system" and event.get("subtype") == "init" and not session.claude_session_id:
        session.claude_session_id = event.get("session_id")
    if event.get("type") == "result":
        session.turn_in_flight = False
    if store:
        session.messages.append(event)
    dead = []
    for q in session.subscribers:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        session.subscribers.discard(q)


async def _drain_stderr(session: Session) -> None:
    proc = session.process
    assert proc.stderr is not None
    while True:
        raw = await proc.stderr.readline()
        if not raw:
            return
        line = raw.decode("utf-8", errors="replace").rstrip()
        if line:
            session.stderr_tail.append(line)


async def _reader_loop(session: Session) -> None:
    proc = session.process
    assert proc.stdout is not None
    try:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                event = {"type": "raw", "text": line}
            _record_event(session, event, store=event.get("type") != "stream_event")
    finally:
        await proc.wait()
        session.ended_at = _now_iso()
        session.exit_code = proc.returncode
        session.turn_in_flight = False
        if session.stop_requested:
            session.status = "killed"
        elif proc.returncode == 0:
            session.status = "exited"
        else:
            session.status = "crashed"
        _record_event(session, {
            "type": "status", "status": session.status, "exit_code": session.exit_code,
            "stderr_tail": list(session.stderr_tail) if session.status == "crashed" else [],
        })
        _GUARD.finish((session.role_id, session.worktree_path))

        role = ROLES.get(session.role_id)
        if role and role.relaunch_on_exit and not session.stop_requested:
            try:
                await start_session(role.id, started_by=session.started_by,
                                    model=session.model)
            except Exception:
                pass   # un relanzamiento fallido no debe tumbar nada más


async def start_session(role_id: str, started_by: Optional[Dict[str, Any]] = None,
                        model: Optional[str] = None) -> Session:
    """`model` sobreescribe el sugerido del rol (ver MODELS). El guard sigue
    siendo por (rol, worktree) a propósito, SIN el modelo en la clave: un rol,
    una sesión, sin importar con qué modelo se lanzó — si el modelo entrara en
    la clave, el mismo rol podría abrir tres terminales en paralelo sobre el
    mismo worktree y el panel dejaría de leerse de un vistazo."""
    role = ROLES.get(role_id)
    if role is None:
        raise KeyError(f"rol desconocido: {role_id!r}")
    if model is not None and model not in _model_ids():
        raise ValueError(f"modelo desconocido: {model!r}")
    chosen_model = model or role.default_model

    worktree_path = str(REPO_ROOT)
    key = (role_id, worktree_path)
    session_id = str(uuid.uuid4())

    async with _LOCK:
        if not _GUARD.try_start(key, session_id):
            raise SessionAlreadyRunning(_GUARD.existing(key))  # type: ignore[arg-type]

    # Motor local: no hay subproceso que lanzar — la sesión queda lista y cada
    # turno es una llamada HTTP. Se valida acá (no al primer turno) para que un
    # Ollama caído se vea al apretar Iniciar y no después de escribir.
    if chosen_model == LOCAL_MODEL_ID:
        cfg = _local_config()
        if cfg is None or not _local_reachable(force=True):
            async with _LOCK:
                _GUARD.finish(key)
            raise RuntimeError(
                "el modelo local no responde — revisa que Ollama esté corriendo "
                "y que LOCAL_MODEL esté configurado")
        try:
            session = LocalSession(
                session_id, role_id, worktree_path, _branch_for(worktree_path),
                started_by, model=chosen_model,
                endpoint=cfg["endpoint"], model_name=cfg["model"],
            )
            _SESSIONS[session_id] = session
            _record_event(session, {
                "type": "system", "subtype": "init",
                "engine": "local", "model": cfg["model"], "tools": False,
            })
        except Exception:
            # Sin esto, cualquier fallo después de tomar el guard deja el rol
            # bloqueado para siempre: la sesión rota queda en _SESSIONS y todo
            # intento posterior recibe un 409 "ya hay una sesión corriendo".
            _SESSIONS.pop(session_id, None)
            async with _LOCK:
                _GUARD.finish(key)
            raise
        return session

    cmd = [
        "claude", "-p",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        # Deltas token a token: sin esto el turno entero aparece de golpe al
        # terminar (un log que se refresca, no un chat). Ver _record_event
        # para por qué estos eventos no entran al buffer de replay.
        "--include-partial-messages",
        "--permission-mode", role.permission_mode or "acceptEdits",
        "--append-system-prompt", role.system_prompt,
    ]
    if chosen_model:
        cmd += ["--model", chosen_model]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=worktree_path, env=_subprocess_env(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except Exception:
        async with _LOCK:
            _GUARD.finish(key)
        raise

    session = Session(session_id, role_id, worktree_path, _branch_for(worktree_path),
                      proc, started_by, model=chosen_model)
    _SESSIONS[session_id] = session
    session.reader_task = asyncio.create_task(_reader_loop(session))
    session.stderr_task = asyncio.create_task(_drain_stderr(session))
    return session


# --- motor local (Ollama) ----------------------------------------------------

# Cuántos turnos previos se le reenvían al modelo local. No hay compactación de
# contexto como en Claude Code: la ventana es finita y la conversación entera
# viaja en cada llamada, así que se acota a mano. 20 mensajes ≈ 10 turnos.
_LOCAL_HISTORY_MAX = 20


def _local_system_prompt(role: Optional[RoleDef]) -> str:
    """El prompt del rol MÁS el aviso de que no hay herramientas. Sin esto, un
    modelo con un system prompt que dice "tu zona de escritura es zero/agents/"
    responde como si hubiera abierto los archivos — inventando su contenido.
    Decírselo explícitamente es la diferencia entre una respuesta honesta
    ("pégame el archivo") y una alucinación con forma de trabajo hecho."""
    base = role.system_prompt if role else "Eres una terminal del proyecto ZERO."
    return (
        base
        + "\n\nIMPORTANTE — en esta sesión NO tienes herramientas: no puedes leer "
          "ni editar archivos, ni ejecutar comandos, ni buscar en el repositorio. "
          "Trabaja solo con lo que el usuario escriba en el mensaje. Si necesitas "
          "ver un archivo, pídele que te lo pegue; nunca afirmes que lo revisaste."
    )


def _stream_local_chat(endpoint: str, payload: Dict[str, Any], on_delta, timeout: float = 300.0) -> None:
    """Lee la respuesta SSE del endpoint OpenAI-compatible y va entregando el
    texto por trozos. Síncrono a propósito (urllib, stdlib) — el caller lo corre
    en un hilo aparte para no bloquear el event loop."""
    req = urllib.request.Request(
        endpoint, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            delta = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")
            if delta:
                on_delta(delta)


async def _run_local_turn(session: "LocalSession", text: str) -> None:
    """Un turno contra el modelo local, traducido al MISMO contrato de eventos
    que emite el CLI (`stream_event` con text_delta, luego `assistant`, luego
    `result`). Por eso el frontend no distingue motores: recibe lo mismo."""
    role = ROLES.get(session.role_id)
    messages = [{"role": "system", "content": _local_system_prompt(role)}]
    messages += session.history[-_LOCAL_HISTORY_MAX:]
    messages.append({"role": "user", "content": text})
    payload = {"model": session.model_name, "messages": messages,
               "stream": True, "temperature": 0.2}

    loop = asyncio.get_running_loop()
    queue: "asyncio.Queue[Tuple[str, Optional[str]]]" = asyncio.Queue()

    def worker() -> None:
        try:
            _stream_local_chat(
                session.endpoint, payload,
                lambda d: loop.call_soon_threadsafe(queue.put_nowait, ("delta", d)),
            )
            loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
        except Exception as e:   # noqa: BLE001 — cualquier fallo se reporta al chat
            loop.call_soon_threadsafe(queue.put_nowait, ("error", str(e)))

    threading.Thread(target=worker, daemon=True).start()

    parts: List[str] = []
    try:
        while True:
            kind, value = await queue.get()
            if kind == "delta" and value:
                parts.append(value)
                _record_event(session, {
                    "type": "stream_event",
                    "event": {"type": "content_block_delta",
                              "delta": {"type": "text_delta", "text": value}},
                }, store=False)
            elif kind == "error":
                _record_event(session, {
                    "type": "result", "subtype": "error",
                    "error": f"el modelo local falló: {value}",
                })
                return
            else:
                break
    except asyncio.CancelledError:
        session.turn_in_flight = False
        raise

    full = "".join(parts)
    session.history.append({"role": "user", "content": text})
    session.history.append({"role": "assistant", "content": full})
    _record_event(session, {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": full}]},
    })
    _record_event(session, {"type": "result", "subtype": "success"})


async def send_turn(session_id: str, text: str) -> None:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise KeyError(session_id)
    if session.status != "running":
        raise RuntimeError(f"la sesión no está corriendo (status={session.status})")
    if session.turn_in_flight:
        raise RuntimeError("ya hay un turno en curso en esta sesión")

    # El turno del humano se registra igual en los dos motores, y ANTES de
    # despachar, para que aparezca en el chat apenas se envía.
    def _record_user_turn() -> None:
        _record_event(session, {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            "at": _now_iso(),
        })

    if isinstance(session, LocalSession):
        session.turn_in_flight = True
        _record_user_turn()
        session.turn_task = asyncio.create_task(_run_local_turn(session, text))
        return

    assert session.process.stdin is not None
    payload = json.dumps({"type": "user", "message": {"role": "user", "content": text}},
                         ensure_ascii=False)
    session.turn_in_flight = True
    try:
        session.process.stdin.write((payload + "\n").encode("utf-8"))
        await session.process.stdin.drain()
    except (BrokenPipeError, ConnectionResetError) as e:
        # El proceso murió entre el chequeo de status y la escritura. Sin este
        # rescate, turn_in_flight queda en True para siempre y la sesión no
        # vuelve a aceptar un turno ni aunque el reader_loop la marque muerta.
        session.turn_in_flight = False
        raise RuntimeError("la sesión murió antes de recibir el turno") from e
    # El CLI no devuelve el turno del usuario en su stdout — solo responde. Si
    # no lo registramos acá, lo que escribe el humano no existe en ninguna
    # parte: no se dibuja en el chat y desaparece del historial al reabrir la
    # sesión (quedaba un monólogo del asistente). Se guarda con la MISMA forma
    # que un evento `assistant` (content = lista de bloques) para que el
    # frontend recorra ambos con el mismo código.
    _record_user_turn()


async def stop_session(session_id: str) -> BaseSession:
    session = _SESSIONS.get(session_id)
    if session is None:
        raise KeyError(session_id)
    session.stop_requested = True

    # Motor local: no hay proceso que matar. Se cancela el turno en vuelo (si
    # lo hay) y se cierra la sesión a mano — el _reader_loop, que es quien hace
    # esto en el motor `claude`, acá no existe.
    if isinstance(session, LocalSession):
        if session.turn_task is not None and not session.turn_task.done():
            session.turn_task.cancel()
            try:
                await session.turn_task
            except (asyncio.CancelledError, Exception):   # noqa: B014
                pass
        session.status = "killed"
        session.ended_at = _now_iso()
        session.turn_in_flight = False
        _record_event(session, {
            "type": "status", "status": "killed", "exit_code": None, "stderr_tail": [],
        })
        _GUARD.finish((session.role_id, session.worktree_path))
        return session

    if session.process.returncode is None:
        session.process.terminate()
        try:
            await asyncio.wait_for(session.process.wait(), timeout=5)
        except asyncio.TimeoutError:
            session.process.kill()
            await session.process.wait()
    # El proceso ya salió, pero es _reader_loop (una task aparte, también
    # esperando proc.wait() en su finally) quien de verdad marca
    # status/ended_at/exit_code y libera el guard — sin este await, el
    # caller HTTP puede recibir el summary viejo ("running") por una carrera
    # entre ambas tasks despertando después del mismo proc.wait().
    if session.reader_task is not None and not session.reader_task.done():
        try:
            await asyncio.wait_for(session.reader_task, timeout=5)
        except asyncio.TimeoutError:
            pass
    return session


# --- pub/sub para el WebSocket ------------------------------------------------

def subscribe(session_id: str) -> Optional["asyncio.Queue[Dict[str, Any]]"]:
    session = _SESSIONS.get(session_id)
    if session is None:
        return None
    q: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue(maxsize=1000)
    session.subscribers.add(q)
    return q


def unsubscribe(session_id: str, q: "asyncio.Queue[Dict[str, Any]]") -> None:
    session = _SESSIONS.get(session_id)
    if session is not None:
        session.subscribers.discard(q)
