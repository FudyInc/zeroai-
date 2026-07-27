"""Funciones programadas — disparo automático por intervalo (2026-07-23).

El registro en sí vive en zero/memory.py (list_functions/get_function/
upsert_function/delete_function — mismo patrón que el catálogo de vendors).
Este módulo es la lógica de negocio *pura* de correr una función (manual o
automática): arma el ctx curado que se le pasa a zero/sandbox.py::
run_sandboxed a partir del lookup_scope de la función, la ejecuta, y resume
lo que run_sandboxed devolvió para guardarlo en last_run. api.py solo conecta
esto con las peticiones HTTP y el hilo del scheduler — sin lógica propia,
según el principio del proyecto (política/mecanismo separados de la
presentación/transporte).

Disparo automático: una función con `schedule: {"interval_minutes": N}`
guarda un `next_run` (ISO UTC); cuando vence, el scheduler en proceso (ver
api.py) la corre sola, sin que nadie apriete "/run" — inspirado en el panel
"Scheduled Functions" de Nexor (competidor, ver
docs/research/mercado-competencia.md:124), con un preset simple de intervalo
en vez de sintaxis cron completa. Disparo por EVENTOS del CRM (ej. "cuando un
lead cambia de etapa") queda deliberadamente fuera — decisión aparte, todavía
no existe.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

# Campos del lead que una función puede ver — SOLO estos, nunca el registro
# completo del CRM. Deliberadamente NO incluye `key` (la identidad interna de
# dedup que usa zero/crm.py): ese nombre de campo chocaría con el filtro de
# nombres-de-credencial de run_sandboxed::_assert_ctx_is_safe (contiene "key"
# como substring) y, de todas formas, una función no necesita el
# identificador interno del CRM — solo los datos del lead en sí.
_LEAD_FIELDS = ("company", "name", "role", "email", "phone", "stage", "score")


def lead_view(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Proyección curada de un registro de CRM para el ctx de una función."""
    return {f: rec.get(f) for f in _LEAD_FIELDS}


def build_ctx(leads: List[Dict[str, Any]], client_id: str, event: str = "manual") -> Dict[str, Any]:
    """El ctx que se le pasa a run_sandboxed para correr una función: leads
    curados (ver lead_view) + el client_id de su lookup_scope + `event`
    ("manual" | "schedule.tick") — mismo nombre de campo que usa Nexor en su
    ctx, para que el código de la función pueda distinguir por qué se
    disparó si le importa (no es obligatorio que lo use)."""
    return {"leads": [lead_view(r) for r in leads], "client_id": client_id, "event": event}


def compute_next_run(interval_minutes: int, from_time: Optional[datetime] = None) -> str:
    """Próxima corrida automática, `interval_minutes` desde `from_time` (o
    ahora). Se llama SIEMPRE desde el momento real de ejecución/guardado —
    nunca desde el `next_run` vencido — así un proceso caído un rato no deja
    una cola de corridas atrasadas esperando: al volver, calcula el próximo
    tick desde YA, no desde donde se quedó."""
    base = from_time or datetime.now(timezone.utc)
    return (base + timedelta(minutes=interval_minutes)).isoformat()


def is_due(fn: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """¿Esta función debe dispararse sola ahora mismo? Habilitada, con
    schedule configurado, y next_run ya vencido. Nunca lanza — un next_run
    mal formado simplemente no está vencido (fail-safe: mejor saltarse un
    tick que reventar el scheduler)."""
    if not fn.get("enabled", True):
        return False
    schedule = fn.get("schedule") or {}
    if not schedule.get("interval_minutes"):
        return False
    next_run = fn.get("next_run")
    if not next_run:
        return False
    now = now or datetime.now(timezone.utc)
    try:
        nr = datetime.fromisoformat(next_run)
    except (TypeError, ValueError):
        return False
    if nr.tzinfo is None:
        nr = nr.replace(tzinfo=timezone.utc)
    return nr <= now


def due_functions(functions: List[Dict[str, Any]], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Subconjunto de `functions` que debe dispararse sola ahora — pura y
    testable sin hilos ni reloj real (se le puede inyectar `now`)."""
    now = now or datetime.now(timezone.utc)
    return [fn for fn in functions if is_due(fn, now)]


class RunGuard:
    """Lleva la cuenta de qué function_ids están corriendo ahora mismo — así
    el scheduler (api.py) nunca dispara dos corridas en paralelo de la MISMA
    función: si sigue corriendo cuando toca el próximo tick, ese tick se
    salta, nunca se encola. Pura y sin threading propio — un `set` común;
    quien la use desde varios hilos (el scheduler) es responsable de
    sincronizar el acceso con su propio lock. Separada así (en vez de vivir
    dentro del hilo del scheduler en api.py) para poder probar la lógica de
    "¿ya está corriendo?" sin hilos ni sleeps reales."""

    def __init__(self) -> None:
        self._running: set = set()

    def try_start(self, function_id: str) -> bool:
        """True y la marca como corriendo si NO estaba corriendo ya; False
        (sin efecto) si ya estaba — la llamada que recibe False no debe
        arrancar una segunda corrida."""
        if function_id in self._running:
            return False
        self._running.add(function_id)
        return True

    def finish(self, function_id: str) -> None:
        self._running.discard(function_id)

    def is_running(self, function_id: str) -> bool:
        return function_id in self._running


class MissingScopeError(ValueError):
    """La función no tiene lookup_scope.client_id — no se puede correr
    (ni manual ni automática)."""


def execute(fn: Dict[str, Any], crm: Any, *, event: str = "manual",
           timeout: int = 12, zero: Any = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Corre `fn` de verdad (manual o disparada por el scheduler) contra su
    lookup_scope real, y devuelve (función_actualizada, resultado_crudo) —
    el llamador (api.py::run_function o el scheduler) decide cómo persistir
    y qué responder; este módulo no toca memory/HTTP.

    ÚNICO camino de ejecución real — tanto el endpoint manual POST
    /api/functions/{id}/run como el scheduler automático llaman a esto, nunca
    hay una segunda implementación que pueda desalinearse.

    Recalcula `next_run` desde AHORA si la función tiene schedule — pasa
    tanto en una corrida manual como automática, para no disparar dos veces
    seguidas por accidente (una prueba manual justo antes de que tocara el
    tick automático).

    Si la función pidió acciones (ver zero/function_actions.py), se validan y
    ejecutan ACÁ — fuera del sandbox, del lado confiable — y el reporte queda
    en out["actions"] y resumido en last_run. `zero` (el orquestador,
    duck-typed) hace falta solo para las acciones de envío; sin él, las de CRM
    igual corren y las de envío se rechazan con motivo.

    Lanza MissingScopeError si falta lookup_scope.client_id, o ValueError si
    el ctx no pasa la validación de seguridad del sandbox (no debería pasar
    nunca) — el llamador decide cómo reportar cada uno."""
    from .function_actions import apply_actions
    from .sandbox import run_sandboxed
    scope = fn.get("lookup_scope") or {}
    client_id = scope.get("client_id")
    if not client_id:
        raise MissingScopeError("la función no tiene lookup_scope.client_id")
    ctx = build_ctx(crm.list(client_id, scope.get("stage")), client_id, event=event)
    out = run_sandboxed(fn["code"], ctx, timeout=timeout)
    # Solo se procesan acciones de una corrida que terminó bien: si el código
    # reventó a mitad de camino, su `result` es basura (o de una ejecución
    # parcial) y no se actúa sobre eso.
    if out.get("error") is None:
        out["actions"] = apply_actions(out.get("result"), fn, crm=crm, zero=zero)
        if out["actions"]["requested"]:
            crm.save()   # las acciones tocaron el CRM (etapas/notas/historial)
    updated = dict(fn)
    updated["last_run"] = summarize_run(out)
    schedule = updated.get("schedule") or {}
    if schedule.get("interval_minutes"):
        updated["next_run"] = compute_next_run(schedule["interval_minutes"])
    return updated, out


def summarize_run(out: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte lo que devolvió run_sandboxed en el registro que se guarda en
    last_run — prioriza mostrar el error si lo hay, si no el resultado, si no
    lo que se imprimió, si no dice explícitamente que no hubo salida.

    Si la corrida ejecutó acciones, eso encabeza el resumen: "mandó 3 WhatsApp"
    es lo que un humano necesita ver de un vistazo en el dashboard, mucho más
    que el valor crudo que devolvió el código. `actions` (cuántas se aplicaron
    y cuántas se rechazaron) va aparte, para poder mostrarlo distinto."""
    if out.get("error"):
        summary = out["error"]
    elif out.get("result") is not None:
        summary = str(out["result"])
    else:
        summary = out.get("stdout") or "(sin salida)"

    actions = out.get("actions") or {}
    applied, rejected = actions.get("applied", 0), len(actions.get("rejected") or [])
    if applied or rejected:
        parts = []
        if applied:
            parts.append(f"{applied} acci{'ón' if applied == 1 else 'ones'} aplicada"
                        f"{'' if applied == 1 else 's'}")
        if rejected:
            parts.append(f"{rejected} rechazada{'' if rejected == 1 else 's'}")
        summary = f"{', '.join(parts)} · {summary}"

    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "ok": out.get("error") is None,
        "result_summary": summary[:500],
        "error": out.get("error"),
        "actions": {"applied": applied, "rejected": rejected} if (applied or rejected) else None,
    }
