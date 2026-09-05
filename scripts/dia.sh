#!/usr/bin/env bash
# El día de trabajo autónomo de ZERO, en orden: auditar → planificar → ejecutar → archivar.
#
# El orden no es cosmético. Cada paso alimenta al siguiente:
#
#   1. `auditar.py`   mide qué está roto hoy. No cuesta tokens y tarda segundos.
#   2. `planificar.py` convierte esos hallazgos —y los objetivos de objetivos.md— en
#                      tareas encoladas, con archivos declarados y criterio de terminado.
#   3. `tanda.py`      toma las tareas, las trabaja en los workspaces, y NADA se commitea
#                      sin pasar por las cuatro puertas (aislamiento, alcance, tests, juez).
#
# Invertir el orden —planificar antes de auditar— hace que el planificador trabaje con
# el informe de ayer y proponga arreglar cosas que ya se arreglaron.
#
# Todo queda en la rama del workspace. Esto NO hace push, NO toca main y NO toca datos.
# La decisión de integrar el trabajo sigue siendo de una persona.
set -uo pipefail
cd /home/diego/zeroai || exit 1

CUPO="${CUPO:-3}"          # cuántas tareas puede proponer el planificador
MAX="${MAX:-2}"            # cuántas ejecuta la tanda (tope de gasto del día)

echo "=== $(date '+%Y-%m-%d %H:%M') — día autónomo ==="

echo; echo "--- 1/4 auditoría ---"
# Devuelve 1 cuando hay hallazgos graves. Eso NO es un fallo del día: es su insumo.
python3 scripts/auditar.py || true

echo; echo "--- 2/4 planificación ---"
python3 scripts/planificar.py --cupo "$CUPO" --encolar || true

echo; echo "--- 3/4 tanda ---"
# Sin tareas en la cola la tanda no hace nada y sale bien; no hay que comprobarlo antes.
#
# `--avisar` NO es opcional acá: cada paso de este script termina en `|| true` para que
# un fallo no corte el día, así que nadie lee el código de salida y el WhatsApp al dueño
# es el ÚNICO monitoreo que existe. Sin este flag el resumen no salía nunca — la tanda
# estuvo ocho días abortando en silencio (el aborto ya avisa por su cuenta, sin flag).
# El código de salida se captura en el `||` mismo: un `|| true` seguido de `$?` da
# siempre 0, porque el `true` ya reemplazó el código de la tanda.
RC_TANDA=0
python3 scripts/tanda.py --ejecutar --max "$MAX" --avisar || RC_TANDA=$?
# Queda escrito en el journal para que `journalctl --user -u zero-dia.service` sirva de
# registro aunque el aviso no haya salido (sin SMTP/WhatsApp configurado, notify_owner
# reporta el error y sigue, que es lo correcto pero deja el día sin rastro).
if [ "$RC_TANDA" -eq 2 ]; then
  echo "  ⚠ la tanda ABORTÓ (código 2): hay credenciales o datos de producción en un workspace"
elif [ "$RC_TANDA" -ne 0 ]; then
  echo "  ⚠ la tanda terminó con código $RC_TANDA"
fi

echo; echo "--- 4/4 informe de auditoría al historial ---"
# Guarda el informe del día fechado en la rama audit/diaria. Va al final a propósito:
# solo tiene sentido archivar lo que la auditoría midió una vez que el día ya corrió.
bash scripts/commitear-auditoria.sh || true

echo; echo "--- estado de la cola ---"
python3 -c "
from zero import tasks
r = tasks.resumen()
print(f\"  abiertas: {r['abiertas']}  |  \" + '  '.join(f'{k}: {v}' for k, v in sorted(r['por_estado'].items())))
for t in tasks.listar(estado=tasks.ATASCADA):
    print(f\"  ATASCADA [{t['workspace']}] {t['titulo']}\")
"
