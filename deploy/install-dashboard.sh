#!/usr/bin/env bash
# Instala el dashboard (:5173) como servicio de usuario, para que arranque solo
# con el sistema igual que el backend y el túnel.
# Correr SIN sudo:  bash deploy/install-dashboard.sh
#
# Por qué unidad de usuario y no de sistema: el dashboard corre con el node de
# nvm, que vive en el home. Además así no hace falta sudo.
# `enable-linger` es lo que hace que systemd levante tus servicios de usuario en
# el boot aunque no hayas abierto una terminal.
set -euo pipefail

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
  echo "No corras este script con sudo: es un servicio de usuario."
  exit 1
fi

REPO="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"

echo "==> Buscando node..."
NODE_BIN="$(dirname "$(command -v node || true)")"
if [ -z "$NODE_BIN" ] || [ ! -x "$NODE_BIN/npm" ]; then
  echo "    ERROR: no encontré node/npm en el PATH."
  echo "    Abre una terminal donde funcione 'node -v' y vuelve a correr esto."
  exit 1
fi
echo "    node $(node -v) en $NODE_BIN"

if [ ! -d "$REPO/frontend/node_modules" ]; then
  echo "==> Instalando dependencias del frontend (npm ci)..."
  ( cd "$REPO/frontend" && npm ci )
fi

echo "==> Escribiendo la unidad en $UNIT_DIR..."
mkdir -p "$UNIT_DIR"
sed "s#__NODE_BIN__#$NODE_BIN#g" \
  "$REPO/deploy/zero-dashboard.user.service" > "$UNIT_DIR/zero-dashboard.service"

echo "==> Activando arranque en el boot (linger)..."
loginctl enable-linger "$USER"

echo "==> Recargando y arrancando..."
systemctl --user daemon-reload
systemctl --user enable --now zero-dashboard.service
systemctl --user restart zero-dashboard.service

echo "==> Esperando a que Vite levante..."
for _ in $(seq 1 30); do
  if curl -sf -m 2 -o /dev/null http://127.0.0.1:5173/; then break; fi
  sleep 1
done

echo ""
systemctl --user --no-pager status zero-dashboard.service | grep -E "●|Active:|Loaded:"
echo ""
if curl -sf -m 3 -o /dev/null http://127.0.0.1:5173/; then
  echo "Listo. Dashboard en http://localhost:5173"
else
  echo "AVISO: el servicio arrancó pero :5173 no responde todavía."
  echo "Revisa con: journalctl --user -u zero-dashboard -n 40 --no-pager"
fi
