"""Atomic JSON persistence with automatic rollback backup.

`crm.json` y `state.json` comparten el mismo riesgo: una escritura interrumpida a
mitad de camino (crash, corte de luz, disco lleno) puede dejar el archivo corrupto,
y sin ningún respaldo eso significa perder todos los leads o toda la memoria de
sesión de un saque. `save_json` escribe atómico (archivo temporal + `os.replace`,
así un crash nunca deja un archivo a medio escribir) y antes rota la versión buena
anterior a `<path>.bak` — así siempre queda una generación de respaldo por si el
*contenido* de hoy resulta malo (no solo si la escritura se corta). `load_json`
lee `path` y, solo si eso falla, intenta `<path>.bak` con un aviso claro por
stderr, antes de finalmente rendirse — nunca arranca vacío en silencio (regla de
la casa: nunca sobrescribir/perder datos locales sin avisar).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak")


def save_json(path: Path, data: Any) -> None:
    """Escritura atómica con una generación de respaldo.

    1. Escribe el contenido nuevo en un archivo temporal (si esto se corta a
       mitad de camino, `path` ni se toca — queda como estaba).
    2. Si `path` ya existía, lo rota a `path.bak` (la última versión buena
       conocida antes de esta escritura).
    3. Mueve el temporal a `path` con `os.replace` (atómico a nivel de SO: nunca
       queda un estado intermedio a medio escribir).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    if path.exists():
        os.replace(path, _backup_path(path))
    os.replace(tmp, path)


def load_json(path: Path) -> Any:
    """Lee `path`; si está corrupto/falla, intenta `<path>.bak` (con aviso por
    stderr) antes de levantar `RuntimeError`. El caller decide qué hacer con el
    error — este módulo nunca empieza vacío por su cuenta."""
    try:
        return json.loads(path.read_text("utf-8"))
    except (ValueError, OSError) as e:
        backup = _backup_path(path)
        if backup.exists():
            try:
                data = json.loads(backup.read_text("utf-8"))
                print(f"[zero] {path} corrupto o ilegible ({e}); restaurado desde {backup}",
                      file=sys.stderr)
                return data
            except (ValueError, OSError):
                pass
        raise RuntimeError(
            f"{path} corrupto o ilegible ({e}), y no hay backup usable en {backup}. "
            f"Revisá o restaurá el archivo (no lo sobrescribo para no perder datos)."
        ) from e
