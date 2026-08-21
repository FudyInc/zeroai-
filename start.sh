#!/usr/bin/env bash
# ZeroAI en local.
#
# Normalmente NO necesitas este script: backend (:8800), túnel y dashboard
# (:5173) corren como servicios y arrancan solos con el sistema.
#   - backend y túnel : systemctl status zero-backend zero-tunnel
#   - dashboard       : systemctl --user status zero-dashboard
#
# Este script sirve para dos casos:
#   ./start.sh          → revisa que todo esté arriba y te dice dónde entrar.
#   ./start.sh --dev    → levanta una instancia aparte, en otros puertos, para
#                         probar cambios sin tocar los servicios de siempre.
set -e
cd "$(dirname "$0")"

up() { curl -sf -m 2 -o /dev/null "$1"; }

if [ "${1:-}" = "--dev" ]; then
  # Puertos alternativos: no pisan a los servicios que están corriendo.
  DEV_API=8801
  DEV_WEB=5174
  echo "▶ Instancia de pruebas (los servicios de siempre siguen intactos)"
  echo "  backend   → http://localhost:$DEV_API"
  uvicorn api:app --port "$DEV_API" --log-level warning &
  BACK=$!
  echo "  dashboard → http://localhost:$DEV_WEB"
  ( cd frontend && VITE_PROXY_TARGET="http://localhost:$DEV_API" npm run dev -- --port "$DEV_WEB" --strictPort ) &
  FRONT=$!
  trap 'kill $BACK $FRONT 2>/dev/null' EXIT INT TERM
  echo ""
  echo "✅ Abre: http://localhost:$DEV_WEB   (Ctrl+C detiene solo esta instancia)"
  wait
  exit 0
fi

echo "Estado de los servicios de ZeroAI:"
echo ""

if up http://localhost:8800/api/health; then
  echo "  ✅ backend    http://localhost:8800"
else
  echo "  ❌ backend    caído  →  sudo systemctl restart zero-backend"
fi

if up http://localhost:5173/; then
  echo "  ✅ dashboard  http://localhost:5173"
else
  echo "  ❌ dashboard  caído  →  systemctl --user restart zero-dashboard"
fi

if up http://localhost:4040/api/tunnels; then
  echo "  ✅ túnel      $(curl -s -m 2 http://localhost:4040/api/tunnels \
      | python3 -c "import sys,json;print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null || echo activo)"
else
  echo "  ❌ túnel      caído  →  sudo systemctl restart zero-tunnel"
fi

echo ""
echo "Abre el dashboard en: http://localhost:5173"
echo "(¿probando cambios sin tocar producción? usa ./start.sh --dev)"
