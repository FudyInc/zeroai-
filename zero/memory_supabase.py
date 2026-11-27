"""Supabase-backed session memory — ICP, follow-up sequences and state in the cloud.

Same interface as SessionMemory; only persistence changes (a single JSON snapshot
row in `app_state`, keyed by the agency). So the ICP a client defines survives
restarts and multiple instances, instead of living in a local `state.json`.

Needs a table (run once in Supabase SQL editor):

    create table if not exists app_state (
      id text primary key,
      data jsonb not null default '{}'::jsonb,
      updated timestamptz default now()
    );

If the table is missing, `make_memory` falls back to the local file (nothing breaks).

Egress: la fila se cachea en el proceso y CADA carga valida la versión (`updated`, ~100 B)
antes de usarla; la fila completa se baja solo si otro la cambió. `save()` sigue siendo
"el último que escribe gana" (como siempre) y deja la caché al día.
"""
from __future__ import annotations

import copy
import os
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ._env import load_env
from ._supabase import SupabaseError, sb_request
from .config import MEMORY_CLOUD_CACHE_TTL_S, MEMORY_CLOUD_VALIDATE_TIMEOUT_S
from .memory import SessionMemory

load_env()

# Caché por proceso de la fila `app_state`. `data` None = vacía (nunca leída o invalidada).
# `_lock` protege SOLO el diccionario (nunca se sostiene durante E/S de red);
# `_refresh_lock` evita que varios hilos bajen la fila completa a la vez.
_cache: Dict[str, Any] = {"data": None, "version": None, "at": 0.0}
_lock = threading.Lock()
_refresh_lock = threading.Lock()


def invalidate_cache() -> None:
    with _lock:
        _cache.update(data=None, version=None, at=0.0)


def _same_version(a: Optional[str], b: Optional[str]) -> bool:
    """Compara los `updated` como instantes: Postgres puede devolver otro formato
    de fracción que el que se escribió."""
    if a is None or b is None:
        return a is b
    try:
        return datetime.fromisoformat(a) == datetime.fromisoformat(b)
    except ValueError:
        return a == b


def _is_newer(a: Optional[str], b: Optional[str]) -> bool:
    """¿`a` es estrictamente posterior a `b`? (sin versión = más viejo)."""
    if a is None:
        return False
    if b is None:
        return True
    try:
        return datetime.fromisoformat(a) > datetime.fromisoformat(b)
    except ValueError:
        return False


def _cache_read():
    with _lock:
        return _cache["data"], _cache["version"], _cache["at"]


def _cache_store(data, version, now: float, from_save: bool = False) -> None:
    """Una bajada manda siempre (es lo que hay en la DB). Un save() no retrocede la
    caché si otro save() concurrente ya dejó una versión más nueva."""
    with _lock:
        if not from_save or _cache["data"] is None or not _is_newer(_cache["version"], version):
            _cache.update(data=data, version=version, at=now)


class CloudStateUnavailable(SupabaseError):
    """Raised when Supabase is configured but the app_state table isn't reachable."""


class SupabaseMemory(SessionMemory):
    TABLE = "app_state"
    ROW_ID = "agency"

    def __init__(self, fresh: bool = False) -> None:
        """`fresh=True` salta la caché (y no sirve copia vieja si la nube falla): para
        decisiones que no pueden apoyarse en un dato de hace segundos."""
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not (url and key):
            raise CloudStateUnavailable("faltan SUPABASE_URL / SUPABASE_KEY")
        self.url = url.rstrip("/")
        self.key = key
        super().__init__(path=None)     # empty in-memory fields, no file
        self._load_cloud(force=fresh)   # may raise CloudStateUnavailable

    def _req(self, method: str, path: str, body=None, prefer=None, timeout: float = 20):
        # SupabaseError (incl. table-missing) propagates → make_memory falls back to local.
        return sb_request(self.url, self.key, method, path, body=body, prefer=prefer,
                          timeout=timeout)

    def _row_url(self, select: str) -> str:
        return f"{self.TABLE}?id=eq.{self.ROW_ID}&select={select}"

    def _remote_version(self) -> Optional[str]:
        rows = self._req("GET", self._row_url("updated"),
                         timeout=MEMORY_CLOUD_VALIDATE_TIMEOUT_S) or []
        return rows[0].get("updated") if rows else None

    def _download(self):
        rows = self._req("GET", self._row_url("data,updated")) or []
        data = (rows[0].get("data") if rows else None) or {}
        return data, (rows[0].get("updated") if rows else None)

    def _load_cloud(self, force: bool = False) -> None:
        data, version, at = _cache_read()
        hay = data is not None
        now = time.monotonic()
        if hay and not force and now - at < MEMORY_CLOUD_CACHE_TTL_S:
            self._adopt(data)           # ráfaga dentro del mismo request: sin red
            return
        try:
            if hay and not force:
                remote = self._remote_version()
                if _same_version(remote, version):
                    _cache_store(data, version, now)
                    self._adopt(data)
                    return
            with _refresh_lock:
                if hay and not force:   # otro hilo pudo refrescar mientras esperaba
                    data2, version2, _ = _cache_read()
                    if _same_version(version2, remote):
                        self._adopt(data2)
                        return
                data, version = self._download()
                _cache_store(data, version, time.monotonic())
        except (SupabaseError, OSError, ValueError) as e:
            if not hay or force:
                raise
            # Nube caída con copia previa: se sirve la última (mejor que un state.json
            # viejo). save() sigue intentando la nube y falla mientras siga caída.
            print(f"[zero] estado en la nube no responde ({e}); sirvo la copia de hace "
                  f"{now - at:.0f}s", file=sys.stderr)
        self._adopt(data)

    def _adopt(self, data: Dict[str, Any]) -> None:
        self._restore(copy.deepcopy(data))   # la caché no se comparte: cada instancia muta la suya

    def reload(self) -> None:
        self._load_cloud(force=True)

    def save(self) -> None:
        snap = self.snapshot()
        version = datetime.now(timezone.utc).isoformat()
        rows = self._req("POST", f"{self.TABLE}?on_conflict=id&select=updated",
                         body=[{"id": self.ROW_ID, "data": snap, "updated": version}],
                         prefer="resolution=merge-duplicates,return=representation")
        # La versión real la pone el trigger de la DB (supabase_schema.sql); sin trigger
        # (o sin `updated` en la respuesta) queda el sello local, como antes.
        real = rows[0].get("updated") if rows and isinstance(rows, list) else None
        _cache_store(copy.deepcopy(snap), real or version, time.monotonic(), from_save=True)
