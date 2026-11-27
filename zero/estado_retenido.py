"""Interruptor "estado local retenido": la nube del estado no vuelve sola.

Si `make_memory` cae a `state.json` por una falla de Supabase, todo lo que se escriba
desde entonces vive solo en ese archivo. Si al volver la nube el backend retomara
Supabase, esos días de cambios quedarían fuera de vista (y el próximo `save()` los
ignoraría). Por eso la primera caída deja un marcador durable; mientras exista, TODO
constructor del estado usa el archivo local aunque Supabase responda. Solo
`scripts/reconciliar_estado.py --aplicar` lo borra, después de fusionar nube + local.

`ZERO_ESTADO_RETENIDO_PATH` cambia la ruta del marcador; vacío desactiva el interruptor
(la suite lo usa para no escribir en `.runtime/` real).
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .config import (ESTADO_RECONCILIAR_COMANDO, ESTADO_RETENIDO_ARCHIVO,
                     ESTADO_RETENIDO_AVISO_VENTANA_S)

_RAIZ = Path(__file__).resolve().parents[1]
_ultimo_aviso = {"at": None}


def ruta() -> Optional[Path]:
    valor = os.environ.get("ZERO_ESTADO_RETENIDO_PATH")
    if valor is not None:
        return Path(valor) if valor else None
    return _RAIZ / ESTADO_RETENIDO_ARCHIVO


def leer() -> Optional[Dict[str, Any]]:
    """El marcador, o None si no hay. Un marcador ilegible cuenta como presente: ante
    la duda el estado sigue en local, que es el lado que no pierde datos."""
    p = ruta()
    if p is None or not p.exists():
        return None
    try:
        datos = json.loads(p.read_text("utf-8"))
    except (ValueError, OSError):
        return {"desde": None, "motivo": "marcador ilegible"}
    return datos if isinstance(datos, dict) else {"desde": None, "motivo": "marcador ilegible"}


def activo() -> bool:
    return leer() is not None


def marcar(motivo: str) -> bool:
    """Crea el marcador si no existe (nunca pisa el `desde` original). Devuelve True si
    lo creó. No levanta: no poder escribirlo no debe tumbar la petición que ya degradó."""
    p = ruta()
    if p is None or p.exists():
        return False
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps({"desde": datetime.now(timezone.utc).isoformat(),
                                   "motivo": str(motivo)[:300]}, ensure_ascii=False), "utf-8")
        os.replace(tmp, p)
    except OSError as e:
        print(f"[zero] no pude escribir el marcador de estado retenido ({e})", file=sys.stderr)
        return False
    return True


def liberar() -> None:
    p = ruta()
    if p is not None:
        p.unlink(missing_ok=True)


def avisar() -> None:
    """Aviso a stderr, una vez por proceso y luego como máximo una por ventana."""
    marca = leer()
    if marca is None:
        return
    ahora = time.monotonic()
    if _ultimo_aviso["at"] is not None and ahora - _ultimo_aviso["at"] < ESTADO_RETENIDO_AVISO_VENTANA_S:
        return
    _ultimo_aviso["at"] = ahora
    print(f"[zero] estado retenido en local desde {marca.get('desde') or 'fecha desconocida'}; "
          f"correr {ESTADO_RECONCILIAR_COMANDO}", file=sys.stderr)
