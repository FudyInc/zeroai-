#!/usr/bin/env python3
"""Carga la ficha de una empresa (knowledge + ICP) en la memoria de ZERO.

Por qué existe: ZERO se despliega en distintas empresas y cada una necesita su
propia base de conocimiento. El dashboard permite cargarla a mano, pero eso vive
solo en `state.json` — local y gitignorado. Este script hace el camino inverso:
toma la ficha **versionada** del repo y la carga, así una empresa se puede
reconstruir desde cero sin depender de que alguien recuerde qué escribió.

Seguro por defecto: NO escribe nada sin `--write`. Sin esa bandera muestra qué
cambiaría y termina. Con `--write` respalda `state.json` antes de tocarlo.

    python3 scripts/cargar_empresa.py --empresa zeroai            # simulacro
    python3 scripts/cargar_empresa.py --empresa zeroai --write    # aplica

Solo stdlib.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero._env import load_env      # noqa: E402
from zero.icp import normalize_icp   # noqa: E402
from zero.store import make_memory   # noqa: E402

# Mismo .env que lee el backend: sin esto el script escribiría en el archivo local
# aunque el sistema en marcha esté guardando en Supabase — dos verdades distintas.
load_env()
STATE_PATH = os.environ.get("STATE_PATH", "state.json")

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Qué empresa se puede cargar y de dónde sale su ficha. Registro explícito y no
# un glob de docs/: cargar la empresa equivocada en producción sería peor que el
# trabajo de agregar una línea acá.
EMPRESAS = {
    "zeroai": {
        "ficha": "docs/ficha-zeroai.md",
        # SOLO los campos que queremos corregir. El resto del ICP se PRESERVA:
        # el de `zeroai` ya trae una segmentación real (empresas de mudanzas en la
        # RM, con sus must_have y exclude) que costó pensarse y que un genérico
        # escrito de memoria empeoraría. `sells` sí estaba incompleto: decía solo
        # generación de leads y son cuatro líneas de servicio.
        "icp_parcial": {
            "sells": ("generación de leads B2B calificados, agentes de WhatsApp, "
                      "automatización de procesos y agentic marketing"),
        },
    },
}

# La ficha real es lo que va entre estas marcas — el resto del .md son notas para
# nosotros y no tienen por qué gastar el presupuesto de contexto del modelo.
_MARCAS = re.compile(r"<!--\s*INICIO FICHA.*?-->\n(.*?)<!--\s*FIN FICHA\s*-->", re.S)

# Mismo corte que aplica orchestrator.reply_to_inbound al pasar la ficha al agente.
LIMITE_FICHA = 4000


def leer_ficha(ruta_rel: str) -> str:
    ruta = os.path.join(RAIZ, ruta_rel)
    texto = open(ruta, encoding="utf-8").read()
    m = _MARCAS.search(texto)
    if not m:
        raise SystemExit(f"{ruta_rel}: faltan las marcas INICIO FICHA / FIN FICHA")
    return m.group(1).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--empresa", required=True, choices=sorted(EMPRESAS))
    ap.add_argument("--write", action="store_true",
                    help="aplica los cambios (sin esto, solo simulacro)")
    args = ap.parse_args()

    ap.add_argument("--solo-ficha", action="store_true",
                    help="no toca el ICP, solo carga la ficha de conocimiento")
    args = ap.parse_args()

    cfg = EMPRESAS[args.empresa]
    ficha = leer_ficha(cfg["ficha"])

    if len(ficha) > LIMITE_FICHA:
        print(f"AVISO: la ficha tiene {len(ficha)} caracteres y el agente solo recibe "
              f"{LIMITE_FICHA}. Se cortaría — acórtala en {cfg['ficha']}.")

    mem = make_memory(STATE_PATH)
    # Dónde va a quedar esto: con Supabase configurado el estado vive en la nube,
    # y escribir sin saberlo es exactamente cómo se tocan datos de producción sin querer.
    destino_txt = type(mem).__name__
    print(f"almacén:  {destino_txt}"
          + ("  (NUBE — Supabase)" if destino_txt != "SessionMemory" else f"  ({STATE_PATH} local)"))
    ficha_antes = mem.get_client_knowledge(args.empresa)
    icp_antes = mem.get_client_icp(args.empresa)

    # Merge, no reemplazo: se parte del ICP que ya está y se pisan solo los campos
    # declarados. Reemplazar borraría segmentación real sin que nadie lo note.
    icp = normalize_icp({**icp_antes, **(cfg.get("icp_parcial") or {})})

    print(f"empresa:  {args.empresa}")
    print(f"ficha:    {len(ficha_antes)} → {len(ficha)} caracteres")
    if args.solo_ficha:
        print("icp:      sin cambios (--solo-ficha)")
    else:
        for campo in sorted(set(cfg.get("icp_parcial") or {})):
            print(f"icp.{campo}:")
            print(f"    antes:   {icp_antes.get(campo) or '(vacío)'}")
            print(f"    después: {icp[campo]}")
        preservados = [k for k, v in icp_antes.items()
                       if v and k not in (cfg.get("icp_parcial") or {})]
        print(f"icp:      se preservan {len(preservados)} campos → {', '.join(preservados)}")

    if not args.write:
        print("\nsimulacro: no se escribió nada. Repite con --write para aplicar.")
        return 0

    # `save()` ya hace escritura atómica con .bak rotado (persistence.py). Este
    # respaldo extra es con fecha y no se rota: sobrevive a varias corridas seguidas.
    destino = os.path.join(RAIZ, STATE_PATH)
    if os.path.exists(destino):
        copia = f"{destino}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        shutil.copy2(destino, copia)
        print(f"\nrespaldo: {os.path.basename(copia)}")

    mem.set_client_knowledge(args.empresa, ficha)
    if not args.solo_ficha:
        mem.set_client_icp(args.empresa, icp)
    mem.save()

    # Releer del disco: confirmar que quedó, en vez de confiar en que save() anduvo.
    verif = make_memory(STATE_PATH)
    ok = len(verif.get_client_knowledge(args.empresa)) == len(ficha)
    if not args.solo_ficha:
        ok = ok and verif.get_client_icp(args.empresa).get("sells") == icp["sells"]
    print("aplicado y verificado en disco." if ok else "ERROR: no quedó guardado.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
