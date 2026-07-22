"""Funciones programadas — fase 2 de 3 (registro + ctx curado + ejecución manual).

El registro en sí vive en zero/memory.py (list_functions/get_function/
upsert_function/delete_function — mismo patrón que el catálogo de vendors).
Este módulo es la lógica de negocio *pura* de "correr una función ahora":
arma el ctx curado que se le pasa a zero/sandbox.py::run_sandboxed a partir
del lookup_scope de la función, y resume lo que run_sandboxed devolvió para
guardarlo en last_run. api.py solo conecta esto con las peticiones HTTP — sin
lógica propia, según el principio del proyecto (política/mecanismo separados
de la presentación/transporte).

Fase 3 (todavía no existe) es la pantalla del dashboard. El disparo automático
por horario es una decisión aparte, tampoco existe todavía — hoy la única
forma de correr una función es "ahora", a pedido.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

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


def build_ctx(leads: List[Dict[str, Any]], client_id: str) -> Dict[str, Any]:
    """El ctx que se le pasa a run_sandboxed para correr una función: SOLO
    leads curados (ver lead_view) + el client_id de su lookup_scope."""
    return {"leads": [lead_view(r) for r in leads], "client_id": client_id}


def summarize_run(out: Dict[str, Any]) -> Dict[str, Any]:
    """Convierte lo que devolvió run_sandboxed en el registro que se guarda en
    last_run — prioriza mostrar el error si lo hay, si no el resultado, si no
    lo que se imprimió, si no dice explícitamente que no hubo salida."""
    if out.get("error"):
        summary = out["error"]
    elif out.get("result") is not None:
        summary = str(out["result"])
    else:
        summary = out.get("stdout") or "(sin salida)"
    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "ok": out.get("error") is None,
        "result_summary": summary[:500],
        "error": out.get("error"),
    }
