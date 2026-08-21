#!/usr/bin/env bash
# Pone cada workspace al día con origin/main. Sin IA a propósito: esto es git,
# no requiere criterio, y gastar cuota de un modelo en un `git reset` sería
# quemar lo escaso en lo barato.
#
# Por qué existe: la auditoría del 2026-08-21 encontró las 6 ramas entre 18 y
# 128 commits atrasadas, ninguna con trabajo propio. Un agente trabajando ahí
# reimplementa lo que ya existe — así aparecieron los duplicados de /api/vendors
# y de Vercel. Una rama de larga vida desactualizada no es un respaldo, es una mina.
#
# SEGURO: un workspace con cambios sin commitear se SALTA y se reporta. Nunca
# descarta trabajo — prefiere quedar desactualizado a borrar algo tuyo.
set -uo pipefail

REPO="${REPO:-/home/diego/zeroai}"
SECCIONES=(core dashboard landing motor-llamadas motor-whatsapp prompts)

cd "$REPO" || { echo "no existe $REPO"; exit 1; }
git fetch -q origin || { echo "fetch falló (¿sin red?)"; exit 1; }
OBJETIVO=$(git rev-parse --short origin/main)

saltados=()
for s in "${SECCIONES[@]}"; do
  d="$(dirname "$REPO")/zero-$s"
  [ -d "$d" ] || { echo "· $s: no existe, se omite"; continue; }

  sucios=$(git -C "$d" status --porcelain | wc -l)
  if [ "$sucios" -gt 0 ]; then
    echo "! $s: $sucios archivos sin commitear — NO se toca"
    saltados+=("$s")
    continue
  fi

  adelante=$(git -C "$d" rev-list --count origin/main..HEAD)
  if [ "$adelante" -gt 0 ]; then
    echo "! $s: $adelante commits propios sin subir — NO se toca"
    saltados+=("$s")
    continue
  fi

  git -C "$d" reset --hard -q origin/main && echo "· $s → $OBJETIVO"
done

if [ ${#saltados[@]} -gt 0 ]; then
  echo
  echo "revisa a mano: ${saltados[*]}"
  exit 2   # distinto de 0: el timer lo deja visible en el journal
fi
echo
echo "los ${#SECCIONES[@]} workspaces al día con origin/main ($OBJETIVO)"
