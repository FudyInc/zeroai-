#!/usr/bin/env bash
# Arranca ZeroAI en local: backend (:8800) + dashboard (:5173).
# Uso:   ./start.sh           → solo en tu Mac (http://localhost:5173)
#        ./start.sh --lan      → accesible en tu wifi (para que tu socio entre)
# Ctrl+C detiene ambos.
set -e
cd "$(dirname "$0")"

HOST_FLAG=""
URL="http://localhost:5173"
if [ "$1" = "--lan" ]; then
  HOST_FLAG="--host"                     # Vite escucha en toda la red local
  IP=$(ipconfig getifaddr en0 2>/dev/null || echo "tu-ip-local")
  URL="http://$IP:5173"
fi

echo "▶ Backend   → http://localhost:8800"
uvicorn api:app --port 8800 --log-level warning &
BACK=$!

echo "▶ Dashboard → $URL"
( cd frontend && npm run dev -- $HOST_FLAG ) &
FRONT=$!

trap 'kill $BACK $FRONT 2>/dev/null' EXIT INT TERM
echo ""
echo "✅ ZeroAI corriendo en local. Abre: $URL"
echo "   (Ctrl+C para detener todo)"
wait
