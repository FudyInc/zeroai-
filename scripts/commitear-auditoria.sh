#!/usr/bin/env bash
# Deja el informe de auditoría del día commiteado en la rama `audit/diaria`.
#
# Por qué existe: `auditoria.json` está en .gitignore a propósito —auditar.py lo
# sobrescribe en cada corrida, así que versionarlo tal cual solo produciría ruido—.
# Pero eso significa que del historial de salud del repo no queda nada: solo se sabe
# cómo está hoy, nunca si algo lleva roto tres semanas o si se rompió anoche. Esto
# guarda una copia fechada, que sí es historial y no se pisa a sí misma.
#
# Por qué NO hace checkout: dia.sh corre tandas de trabajo autónomo sobre este mismo
# repo. Cambiar de rama a mitad le movería el suelo bajo los pies. Así que el commit
# se construye con plumbing (hash-object → write-tree → commit-tree) y se mueve la
# referencia: el working tree y la rama activa quedan exactamente igual que antes.
#
# Respeta la regla de dia.sh: no toca main y no hace push. Integrar sigue siendo
# decisión de una persona.
set -uo pipefail
cd /home/diego/zeroai || exit 1

RAMA="audit/diaria"
INFORME="auditoria.json"
FECHA="$(date '+%Y-%m-%d')"
DESTINO="docs/auditoria/${FECHA}.json"

[ -f "$INFORME" ] || { echo "  sin $INFORME — ¿corrió auditar.py?"; exit 0; }

# Conteos para el mensaje del commit: el asunto dice de un vistazo si el día fue limpio.
read -r TOTAL ALTOS <<<"$(python3 -c "
import json
h = json.load(open('$INFORME')).get('hallazgos', [])
print(len(h), sum(1 for x in h if x.get('gravedad') == 'alta'))
")"

# La rama puede no existir todavía (primera corrida): se parte del main local.
BASE="$(git rev-parse --verify --quiet "refs/heads/$RAMA" || git rev-parse --verify main)"

# Índice temporal propio: no se toca el índice real del repo.
TMPIDX="$(mktemp)"; trap 'rm -f "$TMPIDX"' EXIT
export GIT_INDEX_FILE="$TMPIDX"
git read-tree "$BASE"

BLOB="$(git hash-object -w "$INFORME")"
git update-index --add --cacheinfo "100644,$BLOB,$DESTINO"
TREE="$(git write-tree)"

# Si el árbol no cambió, el informe de hoy es idéntico al que ya está guardado.
# Un commit vacío diario solo ensuciaría el historial que esto viene a construir.
if [ "$TREE" = "$(git rev-parse "$BASE^{tree}")" ]; then
  echo "  sin cambios respecto a $RAMA — no se crea commit"
  exit 0
fi

MENSAJE="audit: informe del ${FECHA} (${TOTAL} hallazgos, ${ALTOS} altos)"
COMMIT="$(git commit-tree "$TREE" -p "$BASE" -m "$MENSAJE")"
git update-ref "refs/heads/$RAMA" "$COMMIT" "$BASE" 2>/dev/null \
  || git update-ref "refs/heads/$RAMA" "$COMMIT"

echo "  $RAMA ← ${COMMIT:0:7}  $MENSAJE"
echo "  ($DESTINO; main intacta, sin push)"
