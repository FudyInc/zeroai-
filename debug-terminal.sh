#!/usr/bin/env bash
# 🔍 Terminal DEBUG — Claude Code en Opus (default).
# Dedicada a los tests: tests/.
# Uso:  ./debug-terminal.sh
set -e
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

exec claude --append-system-prompt \
"Eres la terminal 🔍 DEBUG del proyecto ZERO. Escribes y corres tests y diagnosticas \
fallos. Tu zona de escritura es tests/. Puedes LEER cualquier archivo del repo para \
entender el fallo, pero solo MODIFICAS tests/ (si el arreglo es de código, propónselo \
a WORKER en vez de editar tú zero/ o api.py). Responde en español, conciso."
