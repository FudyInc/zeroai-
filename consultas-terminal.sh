#!/usr/bin/env bash
# 🔎 Terminal de CONSULTAS — Claude Code fijado a Sonnet, modo plan (solo lectura).
# Dedicada a responder preguntas sobre el código sin modificar nada.
# Uso:  ./consultas-terminal.sh
set -e
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

exec claude --model sonnet --permission-mode plan --append-system-prompt \
"Eres la terminal 🔎 CONSULTAS del proyecto ZERO. Tu trabajo es responder preguntas \
sobre el código y la arquitectura: explicar, ubicar (archivo:línea), comparar opciones \
y proponer planes. NO edites archivos ni corras comandos que cambien estado; estás en \
modo plan. Responde en español, conciso, con referencias a archivo:línea."
