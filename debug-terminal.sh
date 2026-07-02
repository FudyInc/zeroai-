#!/usr/bin/env bash
# 🔍 Terminal DEBUG — Claude Code en Opus (default).
# Dedicada a los tests: tests/.
# Se mantiene prendida: si Claude se cierra, se relanza solo.
# Uso:  ./debug-terminal.sh   (la abre automáticamente el comando  zero)
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

PROMPT="Eres la terminal 🔍 DEBUG del proyecto ZERO. Escribes y corres tests y diagnosticas \
fallos. Tu zona de escritura es tests/. Puedes LEER cualquier archivo del repo para \
entender el fallo, pero solo MODIFICAS tests/ (si el arreglo es de código, propónselo \
a WORKER en vez de editar tú zero/ o api.py). Responde en español, conciso."

while true; do
  claude --append-system-prompt "$PROMPT" || true
  echo
  echo "🔍 DEBUG se cerró — relanzando en 3s (Ctrl+C para cerrar la pestaña)…"
  sleep 3 || break
done
