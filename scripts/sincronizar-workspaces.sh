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

saltados=()      # no se tocaron: informativo
en_riesgo=()     # además, tienen trabajo que no existe en ningún remoto: eso sí se avisa
for s in "${SECCIONES[@]}"; do
  d="$(dirname "$REPO")/zero-$s"
  [ -d "$d" ] || { echo "· $s: no existe, se omite"; continue; }

  sucios=$(git -C "$d" status --porcelain | wc -l)
  if [ "$sucios" -gt 0 ]; then
    echo "! $s: $sucios archivos sin commitear — NO se toca"
    saltados+=("$s"); en_riesgo+=("$s (sin commitear)")
    continue
  fi

  # Adelante de origin/main = rama con trabajo propio. NO se resetea, pero eso solo
  # significa que existe: es el estado normal de una rama de sección entre merges.
  adelante=$(git -C "$d" rev-list --count origin/main..HEAD)
  if [ "$adelante" -gt 0 ]; then
    # Lo que sí es riesgo: commits que no están en NINGÚN remoto. Un `git push` los
    # respalda y el workspace sigue adelante de main igual — son preguntas distintas.
    # Medirlo con `origin/main..HEAD` daba un aviso permanente y falso: `prompts` llevaba
    # 5 commits sobre main, los 5 en origin/prompts, y el mensaje decía "sin subir".
    sin_respaldo=$(git -C "$d" rev-list --count HEAD --not --remotes)
    echo "! $s: $adelante commits propios — NO se toca$([ "$sin_respaldo" -gt 0 ] && echo ", $sin_respaldo SIN RESPALDO")"
    saltados+=("$s")
    [ "$sin_respaldo" -gt 0 ] && en_riesgo+=("$s ($sin_respaldo sin respaldo)")
    continue
  fi

  git -C "$d" reset --hard -q origin/main && echo "· $s → $OBJETIVO"
done

[ ${#saltados[@]} -gt 0 ] && { echo; echo "no se tocaron: ${saltados[*]}"; }

if [ ${#en_riesgo[@]} -gt 0 ]; then
  echo "revisa a mano: ${en_riesgo[*]}"
  # El journal de systemd no lo lee nadie. Se avisa SOLO por trabajo que puede perderse
  # —sin commitear, o commiteado y en ningún remoto—, no por el mero hecho de que una
  # rama esté adelante de main: eso es lo normal y avisarlo entrena a ignorar el canal,
  # que es justo lo que este aviso existe para evitar. Con el sync cada 5 minutos, la
  # diferencia es entre callar y mandar 48 mensajes al día por una rama sana.
  python3 -c "
import sys
sys.path.insert(0, '$REPO')
from zero._env import load_env
from zero.alerts import notify_owner
load_env()
res = notify_owner('ZERO: trabajo en riesgo de perderse en workspaces: ${en_riesgo[*]}',
                   kind='sync-workspaces')
print('aviso →', res['status'], res.get('via') or res.get('reason') or '')
" || echo "(el aviso no salió; el resultado igual queda en el journal)"
  exit 2   # distinto de 0: el timer lo deja visible en el journal
fi
echo
echo "los ${#SECCIONES[@]} workspaces al día con origin/main ($OBJETIVO)"
