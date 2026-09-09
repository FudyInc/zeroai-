#!/usr/bin/env python3
"""Guarda una API key en .env sin que pase por el historial del shell.

    python3 scripts/poner-key.py openai
    python3 scripts/poner-key.py anthropic

Existe por dos motivos concretos, los dos comprobados el 2026-09-08:

- `.env` está en solo-lectura (modo 555), así que el `echo >> .env` obvio falla con
  "Permission denied". Acá se levanta el permiso, se escribe y se vuelve a dejar como
  estaba — el modo restrictivo es deliberado y no se pierde por usar esto.
- Una key pegada en la línea de comandos queda en el historial del shell en texto
  plano, para siempre. `getpass` la pide sin mostrarla y sin que toque el historial.

No imprime la key nunca, ni siquiera al confirmar. Solo dice cuántos caracteres leyó,
que alcanza para notar un pegado a medias sin exponer nada.
"""
import getpass
import os
import re
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zero._env import set_env   # noqa: E402

# La forma esperada de cada key. No es validación de seguridad —es para atajar el error
# tonto de pegar la key equivocada en el proveedor equivocado, que después se manifiesta
# como un 503 críptico a mitad de una búsqueda.
# El `(?!ant-)` no es adorno: las dos keys empiezan con "sk-", así que sin eso pegar la
# de Anthropic cuando se pide la de OpenAI pasa la validación sin chistar, y el error
# reaparece después como un 503 críptico a mitad de una búsqueda.
PROVEEDORES = {
    "openai": ("OPENAI_API_KEY", re.compile(r"^sk-(?!ant-)[A-Za-z0-9_\-]{20,}$"),
               "una key de OpenAI empieza con 'sk-' y NO con 'sk-ant-' "
               "(platform.openai.com/api-keys)"),
    "anthropic": ("ANTHROPIC_API_KEY", re.compile(r"^sk-ant-[A-Za-z0-9_\-]{20,}$"),
                  "una key de Anthropic empieza con 'sk-ant-' (console.anthropic.com)"),
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in PROVEEDORES:
        print(f"uso: {sys.argv[0]} [{' | '.join(PROVEEDORES)}]", file=sys.stderr)
        return 2

    variable, forma, pista = PROVEEDORES[sys.argv[1]]
    env = Path(__file__).resolve().parents[1] / ".env"

    key = getpass.getpass(f"Pega la key para {variable} (no se va a mostrar): ").strip()
    if not key:
        print("No se leyó nada. Sin cambios.", file=sys.stderr)
        return 1
    if not forma.match(key):
        print(f"Eso no tiene forma de key válida: {pista}\nSin cambios.", file=sys.stderr)
        return 1

    modo_original = env.stat().st_mode if env.exists() else None
    try:
        if modo_original is not None:
            env.chmod(modo_original | stat.S_IWUSR)      # permiso de escritura, temporal
        set_env(variable, key, str(env))
    finally:
        if modo_original is not None:
            env.chmod(modo_original)                     # devolver el modo tal cual estaba

    print(f"✅ {variable} guardada en {env} ({len(key)} caracteres).")
    print("   Falta un paso: sudo systemctl restart zero-backend")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
