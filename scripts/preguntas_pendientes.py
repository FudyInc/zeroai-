#!/usr/bin/env python3
"""Preguntas que el agente no supo responder, y cómo enseñárselas.

El agente aprende de respuestas **aprobadas por una persona**, no de las
suyas. El historial tiene registradas respuestas que estuvieron mal —una
cantidad de piezas inventada el 2026-10-07, una revisión afirmada que nunca
ocurrió—, y guardarlas como aprendizaje las convertiría en doctrina. Por eso
acá solo se guarda la PREGUNTA; la respuesta la escribes tú.

Una vez respondida, entra a la ficha del cliente. El motor ya selecciona los
fragmentos pertinentes de la ficha en cada consulta (`whatsapp_context.
select_knowledge`), así que desde ese momento cualquiera que pregunte lo mismo
recibe tu respuesta, sin tocar código.

Uso:
    python3 scripts/preguntas_pendientes.py --listar
    python3 scripts/preguntas_pendientes.py --responder "realizan despacho" \\
        --texto "Sí, despachamos a todo Santiago. El valor depende de la comuna."
    python3 scripts/preguntas_pendientes.py --listar --todas
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zero.attention import (ENCABEZADO, LIMITE_FICHA,  # noqa: E402  (mismo mecanismo
                            agregar_respuesta, seccion_respuestas,  # que el dashboard)
                            teach_answer)


def _memoria(raiz: str):
    sys.path.insert(0, raiz)
    os.chdir(raiz)
    from zero.store import make_memory
    return make_memory("state.json")


def listar(memoria, client_id: str, todas: bool) -> int:
    huecos: List[Dict[str, Any]] = memoria.list_knowledge_gaps(client_id, incluir_resueltas=todas)
    if not huecos:
        print("No hay preguntas pendientes. El agente respondió todo lo que le llegó.")
        return 0
    print(f"{len(huecos)} pregunta(s), las más repetidas primero:\n")
    for hueco in huecos:
        estado = hueco.get("estado", "abierta")
        marca = "✓" if estado == "resuelta" else " "
        print(f" {marca} [{hueco.get('veces', 1)}x] {hueco.get('pregunta', '')!r}")
        print(f"     motivo: {hueco.get('reason', '')}")
        print(f"     clave : {hueco.get('clave', '')}")
        if hueco.get("respuesta"):
            print(f"     respuesta: {hueco['respuesta']}")
        print()
    print("Para responder una:")
    print('  python3 scripts/preguntas_pendientes.py --responder "<clave>" --texto "<respuesta>"')
    return 0


def responder(memoria, client_id: str, clave: str, texto: str) -> int:
    huecos = {h.get("clave"): h for h in memoria.list_knowledge_gaps(client_id, incluir_resueltas=True)}
    hueco = huecos.get(clave)
    if not hueco:
        print(f"No existe la clave {clave!r}. Córrela con --listar para ver las disponibles.",
              file=sys.stderr)
        return 1
    error = teach_answer(memoria, client_id, clave, texto)
    if error:
        print(error, file=sys.stderr)
        return 1
    memoria.save()
    print(f"Listo. La ficha quedó en {len(memoria.get_client_knowledge(client_id))} "
          f"de {LIMITE_FICHA} caracteres.")
    print("El motor ya la consulta en cada conversación: no hace falta reiniciar nada.")
    return 0


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cliente", default="losetaschile")
    parser.add_argument("--raiz", default="/home/diego/zeroai",
                        help="checkout cuyo almacén se consulta")
    parser.add_argument("--listar", action="store_true")
    parser.add_argument("--todas", action="store_true", help="incluye las ya respondidas")
    parser.add_argument("--responder", default="", metavar="CLAVE")
    parser.add_argument("--texto", default="", help="la respuesta aprobada")
    args = parser.parse_args(argv)

    memoria = _memoria(args.raiz)
    if args.responder:
        if not args.texto.strip():
            print("Falta --texto con la respuesta.", file=sys.stderr)
            return 1
        return responder(memoria, args.cliente, args.responder, args.texto)
    return listar(memoria, args.cliente, args.todas)


if __name__ == "__main__":
    raise SystemExit(main())
