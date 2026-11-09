"""Genera una vista histórica privada de Pooledge, sin modificar la planilla."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys
from datetime import date

from zero import config as C
from zero import pooledge_sheet as historical
from zero import sheets


def _safe_error(exc):
    # Solo la clase: el mensaje puede traer texto de la API o de la hoja.
    return ("No se pudo consultar la planilla histórica "
            f"({type(exc).__name__}; detalle omitido por seguridad). "
            f"Pestañas esperadas: {C.POOLEDGE_TAB_INFO!r}, {C.POOLEDGE_TAB_PLATAS!r}.")


def _save_private(page: str, directory: Path) -> Path:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    base = f"pooledge-historico-{date.today().isoformat()}-{os.getpid()}"
    suffix = 0
    while True:
        path = directory / f"{base}-{suffix}.html"
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            suffix += 1
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(page)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)
    return path


def run(argv=None, *, token_provider=None, grid_reader=None, values_reader=None,
        env_loader=None, output=print):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="consulta real, solo lectura")
    parser.add_argument("--apply", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.apply:
        parser.error("--apply no existe: esta herramienta es exclusivamente de lectura")
    if not args.preview:
        parser.error("indica --preview para habilitar explícitamente la consulta real de solo lectura")

    try:
        if env_loader is None:
            # El .env de producción vive fuera de este checkout: se indica con
            # ZERO_ENV_PATH. Sin ella, el .env de la raíz del repo (si existe).
            from zero._env import load_env
            load_env(os.environ.get("ZERO_ENV_PATH") or None)
        else:
            env_loader()
        # No usar el ID genérico: es posible que apunte a otro spreadsheet.
        # La consulta histórica requiere que Diego configure el ID exacto de Pooledge.
        spreadsheet_id = os.environ.get(C.POOLEDGE_ORDERS_SHEET_ENV)
        if not spreadsheet_id:
            raise ValueError("falta identificador específico de Pooledge")
        token = (token_provider or sheets.get_access_token)(scope=sheets._READONLY_SCOPE)
        if not token:
            raise ValueError("sin autorización")
        read_values = values_reader or sheets.read_values
        read_grid = grid_reader or sheets.read_grid_data
        info_range = f"{sheets.quote_tab(C.POOLEDGE_TAB_INFO)}!A:I"
        platas_range = f"{sheets.quote_tab(C.POOLEDGE_TAB_PLATAS)}!A:G"
        info = read_values(spreadsheet_id, info_range, token)
        platas = read_values(spreadsheet_id, platas_range, token)
        grids = {
            C.POOLEDGE_TAB_INFO: read_grid(spreadsheet_id, info_range, token),
            C.POOLEDGE_TAB_PLATAS: read_grid(spreadsheet_id, platas_range, token),
        }
        view = historical.historical_view_from_grid(
            info, platas, grids[C.POOLEDGE_TAB_INFO], grids[C.POOLEDGE_TAB_PLATAS], date.today())
        page = historical.render_preview_html(view)
        directory = Path.home() / C.POOLEDGE_PREVIEW_DIR_NAME
        path = _save_private(page, directory)
        fingerprint = hashlib.sha256(page.encode("utf-8")).hexdigest()[:16]
        output(f"Vista histórica privada lista: filas INFO={view.stats['filas_info']}, "
               f"PLATAS={view.stats['filas_platas']}; archivo={path}; fingerprint={fingerprint}")
        return 0
    except Exception as exc:
        output(_safe_error(exc))
        return 1


if __name__ == "__main__":
    sys.exit(run())
