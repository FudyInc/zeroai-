#!/usr/bin/env bash
# Recrea la estructura de trabajo en paralelo (lo que hacía Conductor en el Mac)
# usando git worktree puro + un workspace de Cursor. Correr UNA vez, desde el
# repo recién clonado:
#
#   bash scripts/setup-workspaces.sh
#
# Deja un directorio por sección (hermanos del repo) y un archivo
# `zeroai.code-workspace` en el nivel de arriba: al abrirlo en Cursor ves todas
# las secciones en una sola ventana, cada una en su rama, sin mezclarse.
#
# Por qué worktrees y no clones: comparten el mismo .git, así que un `git fetch`
# sirve para todos y no se duplican los 100+ MB del historial. Es exactamente
# lo que hacía Conductor por debajo.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT="$(dirname "$REPO_DIR")"
cd "$REPO_DIR"

# sección → rama. Las que no existan en origin se crean desde main.
SECCIONES=(
  "core:core"
  "dashboard:dashboard"
  "motor-whatsapp:motor-whatsapp"
  "motor-llamadas:motor-llamadas"
  "landing:landing"
  "prompts:prompts"
)

echo "▶ Repo:      $REPO_DIR"
echo "▶ Worktrees: $PARENT/zero-<sección>"
echo

git fetch origin --quiet

for entry in "${SECCIONES[@]}"; do
  seccion="${entry%%:*}"
  rama="${entry##*:}"
  destino="$PARENT/zero-$seccion"

  if [ -d "$destino" ]; then
    echo "  · $seccion — la carpeta ya existe, se omite"
    continue
  fi

  # Una rama solo puede estar en UN worktree a la vez (incluido el repo
  # principal). Si ya está tomada, se omite en vez de reventar el script.
  if git worktree list --porcelain | grep -qx "branch refs/heads/$rama"; then
    echo "  · $seccion — la rama '$rama' ya está abierta en otra carpeta, se omite"
    continue
  fi

  if git show-ref --verify --quiet "refs/heads/$rama"; then
    git worktree add "$destino" "$rama" >/dev/null
    echo "  ✓ $seccion → rama '$rama' (local)"
  elif git show-ref --verify --quiet "refs/remotes/origin/$rama"; then
    git worktree add "$destino" -b "$rama" "origin/$rama" >/dev/null
    echo "  ✓ $seccion → rama '$rama' (desde GitHub)"
  else
    git worktree add "$destino" -b "$rama" origin/main >/dev/null
    echo "  ✓ $seccion → rama '$rama' (nueva, desde main)"
  fi
done

# --- el workspace de Cursor: todas las secciones en una ventana --------------
WS="$PARENT/zeroai.code-workspace"
{
  echo '{'
  echo '  "folders": ['
  echo "    { \"name\": \"📁 main (integración)\", \"path\": \"$(basename "$REPO_DIR")\" },"
  for entry in "${SECCIONES[@]}"; do
    seccion="${entry%%:*}"
    case "$seccion" in
      core)           icono="⚙️ CORE" ;;
      dashboard)      icono="🖥️ DASHBOARD" ;;
      motor-whatsapp) icono="🧠 MOTOR · WhatsApp" ;;
      motor-llamadas) icono="🧠 MOTOR · Llamadas" ;;
      landing)        icono="🌐 LANDING" ;;
      prompts)        icono="🎯 PROMPTS" ;;
      *)              icono="$seccion" ;;
    esac
    echo "    { \"name\": \"$icono\", \"path\": \"zero-$seccion\" },"
  done | sed '$ s/,$//'
  echo '  ],'
  echo '  "settings": {'
  echo '    "terminal.integrated.cwd": "${workspaceFolder}",'
  echo '    "files.exclude": { "**/__pycache__": true, "**/*.pyc": true },'
  echo '    "search.exclude": { "**/node_modules": true, "**/dist": true }'
  echo '  }'
  echo '}'
} > "$WS"

echo
echo "✅ Listo."
echo
echo "   Abre en Cursor:  $WS"
echo
echo "   Cada carpeta del panel izquierdo es una sección, en su propia rama."
echo "   Para trabajar en una: abre una terminal (Ctrl+Shift+\`), entra a su"
echo "   carpeta y corre 'claude'. Una pestaña por sección = lo que hacía"
echo "   Conductor."
echo
git worktree list
