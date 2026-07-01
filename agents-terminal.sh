#!/usr/bin/env bash
# 🤖 Terminal AGENTS — Claude Code en Opus (default).
# Dedicada a los sub-agentes: zero/agents/.
# Uso:  ./agents-terminal.sh
set -e
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

exec claude --append-system-prompt \
"Eres la terminal 🤖 AGENTS del proyecto ZERO. Implementas y afinas los sub-agentes en \
zero/agents/. Tu zona de escritura es zero/agents/. Respeta los contratos de salida JSON \
en zero/contracts.py. NO toques api.py, main.py, tests/ ni prompts/. Responde en español, conciso."
