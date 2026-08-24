#!/usr/bin/env bash
# El día de trabajo autónomo de ZERO, en orden: auditar → planificar → ejecutar.
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

echo; echo "--- 1/3 auditoría ---"
# Devuelve 1 cuando hay hallazgos graves. Eso NO es un fallo del día: es su insumo.
python3 scripts/auditar.py || true

echo; echo "--- 2/3 planificación ---"
python3 scripts/planificar.py --cupo "$CUPO" --encolar || true

echo; echo "--- 3/3 tanda ---"
# Sin tareas en la cola la tanda no hace nada y sale bien; no hay que comprobarlo antes.
python3 scripts/tanda.py --ejecutar --max "$MAX" || true

echo; echo "--- estado de la cola ---"
python3 -c "
from zero import tasks
r = tasks.resumen()
print(f\"  abiertas: {r['abiertas']}  |  \" + '  '.join(f'{k}: {v}' for k, v in sorted(r['por_estado'].items())))
for t in tasks.listar(estado=tasks.ATASCADA):
    print(f\"  ATASCADA [{t['workspace']}] {t['titulo']}\")
"
