#!/usr/bin/env bash
# Instala ngrok + los 4 servicios de producción de ZeroAI en esta máquina (WSL2).
# Correr con: sudo bash deploy/install.sh
# Requisito previo (sin sudo, como usuario diego, en OTRA terminal o antes de este script):
#   ngrok config add-authtoken <tu-token>
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Corre este script con sudo: sudo bash deploy/install.sh"
  exit 1
fi

REPO="/home/diego/zeroai"

echo "==> Instalando ngrok (repo oficial)..."
if ! command -v ngrok >/dev/null 2>&1; then
  curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc | tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
  echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | tee /etc/apt/sources.list.d/ngrok.list >/dev/null
  apt-get update -qq
  apt-get install -y ngrok
else
  echo "    ngrok ya está instalado, se omite."
fi

echo "==> Verificando que el usuario diego tenga el authtoken de ngrok configurado..."
if [ ! -f /home/diego/.config/ngrok/ngrok.yml ]; then
  echo "    AVISO: no encontré /home/diego/.config/ngrok/ngrok.yml"
  echo "    Antes de que zero-tunnel.service funcione, corre (sin sudo, como diego):"
  echo "      ngrok config add-authtoken <tu-token>"
fi

echo "==> Copiando unidades systemd..."
cp "$REPO/deploy/zero-backend.service" /etc/systemd/system/
cp "$REPO/deploy/zero-tunnel.service" /etc/systemd/system/
cp "$REPO/deploy/zero-sheets-sync.service" /etc/systemd/system/
cp "$REPO/deploy/zero-sheets-sync.timer" /etc/systemd/system/
cp "$REPO/deploy/zero-supabase-keepalive.service" /etc/systemd/system/
cp "$REPO/deploy/zero-supabase-keepalive.timer" /etc/systemd/system/

echo "==> Recargando systemd..."
systemctl daemon-reload

echo "==> Habilitando + arrancando backend y túnel..."
systemctl enable --now zero-backend.service
systemctl enable --now zero-tunnel.service

echo "==> Habilitando + arrancando los timers (sheets sync cada 15min, supabase keepalive diario 04:00)..."
systemctl enable --now zero-sheets-sync.timer
systemctl enable --now zero-supabase-keepalive.timer

echo ""
echo "==> Estado:"
systemctl --no-pager status zero-backend.service zero-tunnel.service | grep -E "●|Active:"
systemctl list-timers zero-sheets-sync.timer zero-supabase-keepalive.timer --no-pager

echo ""
echo "Listo. Verifica con: curl -s http://localhost:8800/api/health"
echo "Y el túnel con:      curl -s https://handpick-monogamy-spiny.ngrok-free.dev/api/health"
