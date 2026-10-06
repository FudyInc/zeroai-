#!/usr/bin/env python3
"""Compara la ficha versionada con la que lee el agente; no escribe datos.

Uso: python3 scripts/verificar_ficha.py --empresa zeroai
"""
from __future__ import annotations

import argparse
import os

from cargar_empresa import EMPRESAS, STATE_PATH, leer_ficha
from zero.memory import SessionMemory
from zero.store import make_memory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--empresa", required=True, choices=sorted(EMPRESAS))
    args = parser.parse_args()

    ficha = leer_ficha(EMPRESAS[args.empresa]["ficha"])
    if len(ficha) > 4000:
        print(f"ERROR: ficha versionada de {len(ficha)} caracteres; el agente recibe solo 4000.")
        return 1

    memoria = make_memory(STATE_PATH)
    nube_configurada = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"))
    if nube_configurada and type(memoria) is SessionMemory:
        print("ERROR: Supabase está configurado, pero no se pudo leer; no se compara con el respaldo local.")
        return 2

    activa = memoria.get_client_knowledge(args.empresa)
    origen = "Supabase" if nube_configurada else f"archivo local {STATE_PATH}"
    print(f"empresa: {args.empresa} | almacén: {origen}")
    print(f"repositorio: {len(ficha)} caracteres | activa: {len(activa)} caracteres")
    print(f"versión activa: {memoria.get_client_knowledge_version(args.empresa)}")
    if not activa:
        print("DIFERENCIA: no hay ficha activa en este almacén.")
        return 1
    if len(activa) > 4000:
        print("DIFERENCIA: la ficha activa se trunca al llegar al agente.")
        return 1
    if ficha != activa:
        print("DIFERENCIA: revisa ambas versiones antes de cargar o editar.")
        return 1
    print("OK: ficha versionada y activa coinciden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
