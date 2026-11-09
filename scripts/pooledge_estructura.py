"""Crea la estructura operativa de la planilla de Pooledge (pestañas nuevas + columnas de INFO).

  --preview                    solo lectura: guarda el plan en un HTML privado y muestra su huella.
  --apply --fingerprint HUELLA aplica el plan SOLO si la huella coincide con el plan recalculado;
                               antes guarda un respaldo privado de todas las pestañas.

No toca el histórico. La consola muestra únicamente conteos, rutas y huella.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from zero import config as C
from zero import pooledge_layout as layout
from zero import sheets
from scripts.pooledge_reordenar import _save_private

_AUDIT_FILE = "pooledge-auditoria.log"


def _safe_error(exc):
    if isinstance(exc, layout.LayoutError):
        # Los mensajes de LayoutError solo citan nombres de config, nunca celdas.
        return f"El plan no se puede construir: {exc}"
    # Solo la clase: el mensaje puede traer texto de la API o de la hoja.
    return ("No se pudo completar la operación sobre la planilla "
            f"({type(exc).__name__}; detalle omitido por seguridad).")


def _last_row(rows) -> int:
    """Última fila (1-based) con cualquier celda no vacía."""
    last = 0
    for i, row in enumerate(rows, start=1):
        if any(str(c).strip() for c in row):
            last = i
    return last


def _nonempty_count(rows) -> int:
    return sum(1 for row in rows for c in row if str(c).strip())


def _audit(directory: Path, entry: dict) -> None:
    """Registro append-only (0600): fecha, huella, conteos y ruta del respaldo; nunca datos."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(directory / _AUDIT_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as out:
        out.write(json.dumps(entry, sort_keys=True) + "\n")


def run(argv=None, *, token_provider=None, meta_reader=None, values_reader=None,
        batch_updater=None, grid_reader=None, env_loader=None, directory=None,
        output=print):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="plan en HTML privado, solo lectura")
    parser.add_argument("--apply", action="store_true", help="aplica el plan a la planilla real")
    parser.add_argument("--fingerprint", help="huella del plan revisado (obligatoria con --apply)")
    args = parser.parse_args(argv)
    if not args.preview and not args.apply:
        parser.error("indica --preview o --apply")
    if args.preview and args.apply:
        parser.error("--preview y --apply son excluyentes")
    if args.apply and not args.fingerprint:
        parser.error("--apply requiere --fingerprint")

    try:
        if env_loader is None:
            from zero._env import load_env
            load_env(os.environ.get("ZERO_ENV_PATH") or None)
        else:
            env_loader()
        spreadsheet_id = os.environ.get(C.POOLEDGE_ORDERS_SHEET_ENV)
        if not spreadsheet_id:
            raise ValueError("falta identificador específico de Pooledge")
        provider = token_provider or sheets.get_access_token
        token = provider(scope=sheets._READONLY_SCOPE) if args.preview else provider()
        if not token:
            raise ValueError("sin autorización")
        read_values = values_reader or sheets.read_values
        meta = (meta_reader or sheets.get_sheet_meta)(spreadsheet_id, token)
        info = sheets.quote_tab(C.POOLEDGE_TAB_INFO)
        info_rows = read_values(spreadsheet_id, f"{info}!A:I", token)
        j_rows = read_values(spreadsheet_id, f"{info}!J:J", token, render="FORMULA")
        plan = layout.build_plan(meta, _last_row(info_rows), _nonempty_count(j_rows))
        fingerprint = layout.plan_fingerprint(plan)
        n_requests = len(plan["requests"])
        directory = directory or Path.home() / C.POOLEDGE_PREVIEW_DIR_NAME

        if args.preview:
            path = _save_private(layout.render_plan_html(plan), directory, prefix="pooledge-estructura")
            output(f"Plan privado listo: requests={n_requests}; archivo={path}; fingerprint={fingerprint}")
            return 0

        if fingerprint != args.fingerprint:
            output("La huella no coincide: genera una nueva vista previa. No se escribió nada.")
            return 1
        backup = {"values": {}}
        for sheet in meta.get("sheets", []):
            props = sheet["properties"]
            last_col = layout.col_letter(max(props.get("gridProperties", {}).get("columnCount", 26), 1) - 1)
            backup["values"][props["title"]] = read_values(
                spreadsheet_id, f"{sheets.quote_tab(props['title'])}!A:{last_col}", token, render="FORMULA")
        summ = plan["summary"]
        grid_range = f"{info}!G{summ['first_new_row']}:J{summ['info_end_row']}"
        backup["info_format_grid"] = (grid_reader or sheets.read_grid_data)(spreadsheet_id, grid_range, token)
        backup_path = _save_private(json.dumps(backup, ensure_ascii=False), directory,
                                    prefix="pooledge-respaldo", ext="json")
        entry = {"fecha": datetime.now().isoformat(timespec="seconds"), "fingerprint": fingerprint,
                 "requests": n_requests, "respaldo": str(backup_path)}
        _audit(directory, {**entry, "estado": "aplicando"})
        try:
            (batch_updater or sheets.batch_update)(spreadsheet_id, plan["requests"], token)
        except Exception as exc:
            try:
                _audit(directory, {**entry, "estado": "fallido"})
            except Exception:
                pass
            output(_safe_error(exc))
            return 1
        try:
            _audit(directory, {**entry, "estado": "aplicado"})
            audit_note = ""
        except Exception:
            audit_note = "; el registro de auditoría falló"
        output(f"Estructura aplicada{audit_note}: requests={n_requests}; "
               f"respaldo={backup_path} (pestañas={len(backup['values'])}, más valores y color de INFO G:J filas nuevas; validaciones y formato numérico no); "
               f"fingerprint={fingerprint}")
        return 0
    except Exception as exc:
        output(_safe_error(exc))
        return 1


if __name__ == "__main__":
    sys.exit(run())
