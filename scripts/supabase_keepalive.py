"""Ping diario a Supabase — evita que el plan gratis pause el proyecto por
inactividad (~1 semana sin uso). No hace ningún "push": el CRM y la memoria
ya escriben ahí en tiempo real (ver zero/store.py); esto solo asegura que
Supabase vea actividad aunque pase una semana tranquila sin que nadie use
el dashboard.

Uso: python3 scripts/supabase_keepalive.py
Pensado para correr una vez al día vía systemd timer (ver docs/motor-real.md
o el .service/.timer instalados en el Ubuntu de producción).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zero._env import load_env  # noqa: E402
from zero._supabase import SupabaseError, sb_request  # noqa: E402

load_env()


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not (url and key):
        print("[keepalive] SUPABASE_URL/SUPABASE_KEY no configurados — nada que hacer.")
        return 0
    try:
        sb_request(url.rstrip("/"), key, "GET", "app_state?select=id&limit=1")
    except SupabaseError as e:
        print(f"[keepalive] fallo: {e}", file=sys.stderr)
        return 1
    print("[keepalive] ok — Supabase respondió.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
