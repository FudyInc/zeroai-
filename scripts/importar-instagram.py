#!/usr/bin/env python3
"""Importa los leads de Instagram (Lead Ads) de todos los clientes que tengan formularios.

Sin IA a propósito: es leer una API y escribir al CRM. Cada cliente corre aislado:
si uno falla (token vencido, formulario borrado) los demás siguen, y el fallo queda
en `lead_sync.error` de ese cliente, que es lo que ve su dashboard.

    python3 scripts/importar-instagram.py

Sale con código 1 si algún cliente falló. Lo dispara deploy/zero-instagram.timer
cada LEAD_ADS_SYNC_MINUTES minutos (zero/config.py).

Solo stdlib.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero._env import load_env      # noqa: E402
from zero.leadads import import_lead_ads  # noqa: E402
from zero.store import make_crm, make_memory  # noqa: E402

load_env()

CRM_PATH = os.environ.get("CRM_PATH", "crm.json")
STATE_PATH = os.environ.get("STATE_PATH", "state.json")


def importar() -> dict:
    """{cliente: resumen | {"error": motivo}} para cada cliente con formularios."""
    clientes = [c for c, data in make_memory(STATE_PATH).clients.items()
                if (data.get("meta") or {}).get("lead_form_ids")]
    resultados = {}
    for cliente in clientes:
        try:
            # Estado fresco por cliente: el backend también escribe state.json, y así
            # se acorta la ventana en que dos escritores se pisan.
            resultados[cliente] = import_lead_ads(
                cliente, make_memory(STATE_PATH), lambda: make_crm(CRM_PATH))
        except Exception as e:      # noqa: BLE001 — un cliente caído no frena al resto
            resultados[cliente] = {"error": str(e)}
    return resultados


def main() -> int:
    resultados = importar()
    if not resultados:
        print("ningún cliente tiene formularios de Instagram")
        return 0
    fallas = 0
    for cliente, r in resultados.items():
        if "error" in r:
            fallas += 1
            print(f"{cliente}: ERROR {r['error']}")
        else:
            print(f"{cliente}: leídos {r['read']}, nuevos {r['created']}, "
                  f"ya presentes {r['already_present']}, bloqueados {r['skipped_blocked']}")
    return 1 if fallas else 0


def _parse_args() -> argparse.Namespace:
    return argparse.ArgumentParser(
        description="Importa los leads de Instagram (Lead Ads) de todos los clientes con "
                    "formularios asignados. ESCRIBE DATOS REALES: crm.json y state.json "
                    "(o Supabase si está activo). Se ejecuta solo, cada "
                    "LEAD_ADS_SYNC_MINUTES minutos (zero/config.py), vía "
                    "deploy/zero-instagram.timer. Sale con código 1 si algún cliente falló.",
    ).parse_args()


if __name__ == "__main__":
    _parse_args()
    raise SystemExit(main())
