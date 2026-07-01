#!/usr/bin/env bash
# 📊 Terminal USO — panel de información de uso para trabajar en ZERO.
# Una sola pestaña con dos paneles (vía tmux):
#   · izquierda: recursos del sistema (btop) — vigila la RAM al correr el modelo local (solo 14 GB).
#   · derecha:   uso de Claude Code (ccusage) — tokens/costo del bloque de facturación activo.
# Uso:  ./uso-terminal.sh
set -e
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:$PATH"

# ccusage: usa el binario global si está; si no, cae a npx (portable, no exige instalar nada).
if command -v ccusage >/dev/null 2>&1; then CC="ccusage"; else CC="npx -y ccusage@latest"; fi
# Monitor de recursos: btop, con degradación a htop y luego top.
if command -v btop >/dev/null 2>&1; then MON="btop"; elif command -v htop >/dev/null 2>&1; then MON="htop"; else MON="top"; fi

SESH="zero-uso"
tmux kill-session -t "$SESH" 2>/dev/null || true
tmux new-session -d -s "$SESH" -n uso
# Panel izquierdo: recursos del sistema.
tmux send-keys -t "$SESH" "$MON" C-m
# Panel derecho: uso de Claude Code, refrescado cada 60 s.
tmux split-window -h -t "$SESH"
tmux send-keys -t "$SESH" "watch -n 60 -t '$CC blocks 2>/dev/null | tail -n 30'" C-m
tmux select-pane -t "$SESH":0.0
exec tmux attach -t "$SESH"
