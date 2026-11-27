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

Egress: la fila se cachea en el proceso (ver `MEMORY_CLOUD_CACHE_TTL_S` en config.py).
`save()` escribe la fila ENTERA, así que una copia cacheada nunca se guarda a ciegas:
si otro proceso cambió la fila desde que se leyó, `save()` falla con 409 en vez de pisarlo.
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
_cache: Dict[str, Any] = {"data": None, "version": None, "at": 0.0}
_lock = threading.Lock()


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
        self._version: Optional[str] = None
        self._from_cache = False
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

    def _load_cloud(self, force: bool = False) -> None:
        with _lock:
            now = time.monotonic()
            hay = _cache["data"] is not None
            if hay and not force and now - _cache["at"] < MEMORY_CLOUD_CACHE_TTL_S:
                self._adopt(_cache["data"], _cache["version"], True)
                return
            try:
                if hay and not force and _same_version(self._remote_version(), _cache["version"]):
                    _cache["at"] = now
                    self._adopt(_cache["data"], _cache["version"], True)
                    return
                rows = self._req("GET", self._row_url("data,updated")) or []
            except (SupabaseError, OSError, ValueError) as e:
                if not hay or force:
                    raise
                # Nube caída con copia previa: se sirve la última (mejor que state.json
                # viejo). save() desde esta copia revalida y falla mientras siga caída.
                print(f"[zero] estado en la nube no responde ({e}); sirvo la última copia",
                      file=sys.stderr)
                _cache["at"] = now
                self._adopt(_cache["data"], _cache["version"], True)
                return
            data = (rows[0].get("data") if rows else None) or {}
            version = rows[0].get("updated") if rows else None
            _cache.update(data=data, version=version, at=now)
            self._adopt(data, version, False)

    def _adopt(self, data: Dict[str, Any], version: Optional[str], from_cache: bool) -> None:
        self._restore(copy.deepcopy(data))   # la caché no se comparte: cada instancia muta la suya
        self._version = version
        self._from_cache = from_cache

    def reload(self) -> None:
        self._load_cloud(force=True)

    def save(self) -> None:
        if self._from_cache and not _same_version(self._remote_version(), self._version):
            invalidate_cache()
            raise SupabaseError(
                "el estado en la nube cambió desde que se leyó; no se guarda para no "
                "pisar ese cambio, reintenta", code=409)
        snap = self.snapshot()
        version = datetime.now(timezone.utc).isoformat()
        self._req("POST", f"{self.TABLE}?on_conflict=id",
                  body=[{"id": self.ROW_ID, "data": snap, "updated": version}],
                  prefer="resolution=merge-duplicates,return=minimal")
        with _lock:
            _cache.update(data=copy.deepcopy(snap), version=version, at=time.monotonic())
        self._version = version
