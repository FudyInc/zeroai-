#!/usr/bin/env bash
# Una foto del estado de ZERO, escrita a disco para que cualquier terminal la lea.
#
# ## Por qué un archivo y no un mensaje
#
# Cada terminal arranca en frío: no sabe qué hay en main, qué workspaces van atrasados
# ni qué pasó con el ciclo de anoche. La tentación es mandarles el estado por mensaje
# cada cierto rato. No hacerlo, por dos razones medidas:
#
#   1. Un mensaje a una sesión que ya no existe NO da error. Entre el 28 y el 30 de
#      agosto se mandaron tres peticiones entre terminales; dos no dejaron rastro y no
#      hubo forma de saber si se perdieron (ver docs/como-circula-un-hallazgo.md).
#   2. Cada mensaje le cuesta un turno a quien lo recibe. Repartir esto cada 5 minutos
#      a seis terminales son 1728 interrupciones al día por información que nadie pidió.
#
# El archivo no se pierde, no interrumpe a nadie, y quien lo necesita lo lee cuando
# arranca. El anillo avisa; los archivos mandan.
#
# ## Por qué no lo escribe un modelo
#
# Todo lo de acá sale de `git`, de `zero.tasks` y del journal. Son hechos, no criterio.
# Gastar una corrida de modelo cada 5 minutos en leer `git rev-list` sería quemar lo
# caro en lo barato — el mismo argumento que ya está escrito en revisar-salud.py.
#
#     bash scripts/estado.sh          # escribe ESTADO.md y lo imprime
#     bash scripts/estado.sh --quiet  # solo escribe
#
# Solo git, bash y stdlib.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SALIDA="$REPO/ESTADO.md"
SECCIONES=(core dashboard landing motor-llamadas motor-whatsapp prompts)

cd "$REPO" || exit 1
git fetch -q origin 2>/dev/null || true

{
  echo "# Estado de ZERO"
  echo
  echo "Generado por \`scripts/estado.sh\` el $(date '+%Y-%m-%d %H:%M:%S %Z'). No se edita a"
  echo "mano: se reescribe entero en cada corrida."
  echo
  echo '## main'
  echo '```'
  git log --oneline -5 main
  echo '```'
  echo
  echo "Sin respaldo remoto: **$(git rev-list --count main --not --remotes) commits**."
  echo
  echo '## Workspaces'
  echo
  echo '| sección | detrás de origin/main | sin commitear | sin respaldo | HEAD |'
  echo '|---|---|---|---|---|'
  for s in "${SECCIONES[@]}"; do
    d="$(dirname "$REPO")/zero-$s"
    [ -d "$d" ] || { echo "| $s | — | — | — | no existe |"; continue; }
    atras=$(git -C "$d" rev-list --count HEAD..origin/main 2>/dev/null || echo '?')
    sucios=$(git -C "$d" status --porcelain 2>/dev/null | wc -l)
    riesgo=$(git -C "$d" rev-list --count HEAD --not --remotes 2>/dev/null || echo '?')
    head=$(git -C "$d" log -1 --format='%h %s' 2>/dev/null | cut -c1-46)
    marca=''; [ "${sucios:-0}" -gt 0 ] || [ "${riesgo:-0}" -gt 0 ] && marca=' ⚠'
    echo "| $s | $atras | $sucios | $riesgo$marca | $head |"
  done
  echo
  echo "\`sin respaldo\` = commits que no existen en ningún remoto. Es la única columna"
  echo "que significa riesgo de pérdida; \`detrás\` y \`sin commitear\` son estado normal."
  echo
  echo '## Cola'
  echo '```'
  python3 -c "
import sys; sys.path.insert(0, '$REPO')
from zero import tasks
r = tasks.resumen()
print(f\"abiertas: {r['abiertas']}  |  \" + '  '.join(f'{k}: {v}' for k, v in sorted(r['por_estado'].items())))
for t in tasks.listar():
    if t['estado'] in ('pendiente', 'en_curso', 'en_revision'):
        print(f\"  {t['estado']:<11} [{t['workspace']}] {t['titulo'][:56]}\")
for t in tasks.listar(estado=tasks.ATASCADA):
    print(f\"  ATASCADA    [{t['workspace']}] {t['titulo'][:56]}\")
" 2>&1
  echo '```'
  echo
  echo '## Objetivos'
  echo '```'
  grep -v '^#' objetivos.md 2>/dev/null | grep -v '^\s*$' || echo '(vacío)'
  echo '```'
  echo
  echo '## Último ciclo autónomo'
  echo '```'
  journalctl --user -u zero-dia.service -n 400 --no-pager 2>/dev/null \
    | grep -E "día autónomo|ABORTADA|encoladas|aprobadas|no había tareas|✓ commiteada|⏭|abiertas:" \
    | tail -12 || echo '(sin registro)'
  echo '```'
} > "$SALIDA"

[ "${1:-}" = "--quiet" ] || cat "$SALIDA"
