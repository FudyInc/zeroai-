#!/usr/bin/env bash
# 🚀 Lanzador ZERO — abre UNA ventana de Ptyxis con las 7 pestañas/terminales,
# cada una arrancando ya en su rol y modelo.
#   🔎 CONSULTAS · 📝 PROMPTS · 🔨 WORKER · 🔍 DEBUG · 🤖 AGENTS · 🎨 DESIGN · 📊 USO
# Uso:  ./zero-terminals.sh   (o el comando  zero  desde cualquier lado)
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

# Primera pestaña abre la ventana (maximizada); las demás se añaden a esa ventana.
ptyxis --new-window --maximize -T "🔎 CONSULTAS" -d "$DIR" -- "$DIR/consultas-terminal.sh"
sleep 0.6
ptyxis --tab -T "📝 PROMPTS" -d "$DIR" -- "$DIR/prompts-terminal.sh"
sleep 0.4
ptyxis --tab -T "🔨 WORKER"  -d "$DIR" -- "$DIR/worker-terminal.sh"
sleep 0.4
ptyxis --tab -T "🔍 DEBUG"   -d "$DIR" -- "$DIR/debug-terminal.sh"
sleep 0.4
ptyxis --tab -T "🤖 AGENTS"  -d "$DIR" -- "$DIR/agents-terminal.sh"
sleep 0.4
ptyxis --tab -T "🎨 DESIGN"  -d "$DIR" -- "$DIR/design-terminal.sh"
sleep 0.4
ptyxis --tab -T "📊 USO"     -d "$DIR" -- "$DIR/uso-terminal.sh"
