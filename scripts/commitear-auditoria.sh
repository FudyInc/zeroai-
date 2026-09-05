#!/usr/bin/env bash
# Deja el informe de auditoría del día commiteado en la rama `audit/diaria`:
# UN commit por fecha, con el último informe de esa fecha.
#
# Por qué existe: `auditoria.json` está en .gitignore a propósito —auditar.py lo
# sobrescribe en cada corrida, así que versionarlo tal cual solo produciría ruido—.
# Pero eso significa que del historial de salud del repo no queda nada: solo se sabe
# cómo está hoy, nunca si algo lleva roto tres semanas o si se rompió anoche. Esto
# guarda una copia fechada, que sí es historial y no se pisa a sí misma.
#
# Por qué la comparación NO es sobre el árbol de git: el informe lleva `cuando` (un
# timestamp) y un `segundos` por check, así que dos corridas seguidas del mismo día
# producen árboles distintos aunque el resultado sea idéntico. La guarda anti-commits
# -vacíos que comparaba árboles no podía dispararse nunca, y la rama lo demuestra:
#
#     197238b audit: informe del 2026-09-04 (0 hallazgos, 0 altos)
#     6107408 audit: informe del 2026-09-04 (0 hallazgos, 0 altos)
#
# Dos commits, mismo día, mismo mensaje; el único diff eran 20.3 → 20.5 segundos.
# Cuánto tardó la suite no es información de salud, es ruido de medición. Lo que
# decide si el día cambió son los `hallazgos` y el resultado de los `checks`.
#
# Los tres casos, explícitos:
#   · no hay commit de hoy en la rama            → commit nuevo
#   · hay commit de hoy y el contenido cambió    → se REEMPLAZA (el commit nuevo se
#     construye sobre el PADRE del de hoy, no encima): el informe que queda es el
#     último del día, que es el que vale
#   · hay commit de hoy y no cambió nada real    → no se hace nada
#
# Por qué NO hace checkout: dia.sh corre tandas de trabajo autónomo sobre este mismo
# repo. Cambiar de rama a mitad le movería el suelo bajo los pies. Así que el commit
# se construye con plumbing (hash-object → write-tree → commit-tree) y se mueve la
# referencia: el working tree, el índice y la rama activa quedan exactamente igual.
#
# Respeta la regla de dia.sh: no toca main y no hace push. Integrar sigue siendo
# decisión de una persona.
#
# --- PENDIENTE, NO SE HACE ACÁ: la rama huérfana -------------------------------
# `BASE` cae en la propia rama a partir del segundo día, así que el árbol de
# audit/diaria arrastra para siempre el main congelado del día 1: cada informe viene
# acompañado de una copia fósil del repo que nadie va a leer y que confunde a
# cualquiera que mire la rama. Lo correcto sería que `audit/diaria` fuera huérfana y
# contuviera SOLO docs/auditoria/. Eso reescribe historial, así que la decisión es de
# Diego y no de este script. El comando que lo haría, para cuando lo decida:
#
#     git worktree add --detach /tmp/audit-huerfana
#     cd /tmp/audit-huerfana
#     git checkout --orphan audit/diaria-limpia
#     git rm -rf --cached . >/dev/null
#     git checkout audit/diaria -- docs/auditoria
#     git add docs/auditoria
#     git commit -m "audit: historial de salud, sin el árbol del repo"
#     # revisar, y recién ahí: git branch -M audit/diaria-limpia audit/diaria
#     cd - && git worktree remove /tmp/audit-huerfana
#
# Se corre a mano y se revisa antes de mover la rama. Este script no lo intenta.
set -uo pipefail

# El repo real. La variable existe para los tests (repo git temporal en tmp); en
# producción nadie la define y el destino es el de siempre.
REPO="${AUDIT_REPO:-/home/diego/zeroai}"
cd "$REPO" || exit 1

RAMA="audit/diaria"
INFORME="auditoria.json"
FECHA="$(date '+%Y-%m-%d')"
DESTINO="docs/auditoria/${FECHA}.json"

[ -f "$INFORME" ] || { echo "  sin $INFORME — ¿corrió auditar.py?"; exit 0; }

# La forma canónica del informe: lo que de verdad dice si el día cambió. Se le quitan
# `cuando` y el `segundos` de cada check — ruido de medición, no salud.
#
# Un informe ilegible no puede hacer pasar el día por "sin cambios": si no se puede
# comparar, cada lado devuelve un marcador distinto y el commit se hace igual.
normalizar() {
  python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:                       # noqa: BLE001 — ilegible = distinto, nunca igual
    print("<ilegible:" + sys.argv[1] + ">"); raise SystemExit(0)
if isinstance(d, dict):
    d.pop("cuando", None)
    for c in d.get("checks") or []:
        if isinstance(c, dict):
            c.pop("segundos", None)
print(json.dumps(d, sort_keys=True, ensure_ascii=False))
' "$1"
}

# Conteos para el mensaje del commit: el asunto dice de un vistazo si el día fue limpio.
read -r TOTAL ALTOS <<<"$(python3 -c "
import json
h = json.load(open('$INFORME')).get('hallazgos', [])
print(len(h), sum(1 for x in h if x.get('gravedad') == 'alta'))
")"

# ¿Ya hay un commit de HOY en la rama? Lo hay si su cabeza introdujo o cambió el
# informe de esta fecha respecto de su propio padre. Se mira el contenido y no el
# mensaje ni la fecha del commit: el mensaje es texto que alguien puede reescribir.
CABEZA="$(git rev-parse --verify --quiet "refs/heads/$RAMA" || true)"
COMMIT_HOY=""
PADRE=""
GUARDADO=""
if [ -n "$CABEZA" ]; then
  GUARDADO="$(git rev-parse --verify --quiet "${CABEZA}:${DESTINO}" || true)"
  PADRE="$(git rev-parse --verify --quiet "${CABEZA}^" || true)"
  PREVIO=""
  [ -n "$PADRE" ] && PREVIO="$(git rev-parse --verify --quiet "${PADRE}:${DESTINO}" || true)"
  [ -n "$GUARDADO" ] && [ "$GUARDADO" != "$PREVIO" ] && COMMIT_HOY="$CABEZA"
fi

if [ -n "$COMMIT_HOY" ]; then
  ANTES="$(git cat-file blob "$GUARDADO" | normalizar guardado)"
  AHORA="$(normalizar local < "$INFORME")"
  if [ "$ANTES" = "$AHORA" ]; then
    echo "  sin cambios reales respecto al informe de hoy (${COMMIT_HOY:0:7}) — no se crea commit"
    exit 0
  fi
  # Reemplazo: se construye sobre el PADRE del commit de hoy, para que la fecha tenga
  # un solo commit y no una cadena de correcciones.
  BASE="$PADRE"
  ACCION="reemplazado"
else
  # Primer informe del día. Si la rama no existe todavía se parte del main local.
  BASE="${CABEZA:-$(git rev-parse --verify main)}"
  ACCION="nuevo"
fi

# Índice temporal propio: no se toca el índice real del repo.
TMPIDX="$(mktemp)"; trap 'rm -f "$TMPIDX"' EXIT
export GIT_INDEX_FILE="$TMPIDX"
if [ -n "$BASE" ]; then git read-tree "$BASE"; else git read-tree --empty; fi

BLOB="$(git hash-object -w "$INFORME")"
git update-index --add --cacheinfo "100644,$BLOB,$DESTINO"
TREE="$(git write-tree)"

# Cinturón extra: si el árbol resultante es idéntico al de la base, no hay nada que
# guardar. Ya no es la guarda principal —esa es la comparación normalizada de arriba—,
# pero cubre el caso de volver a guardar un informe que ya estaba tal cual.
if [ -n "$BASE" ] && [ "$TREE" = "$(git rev-parse "$BASE^{tree}")" ]; then
  echo "  sin cambios respecto a $RAMA — no se crea commit"
  exit 0
fi

MENSAJE="audit: informe del ${FECHA} (${TOTAL} hallazgos, ${ALTOS} altos)"
if [ -n "$BASE" ]; then
  COMMIT="$(git commit-tree "$TREE" -p "$BASE" -m "$MENSAJE")"
else
  COMMIT="$(git commit-tree "$TREE" -m "$MENSAJE")"
fi

# Se mueve la referencia comprobando dónde estaba: si otra corrida la movió mientras
# tanto, esto falla en vez de pisarla.
if [ -n "$CABEZA" ]; then
  git update-ref "refs/heads/$RAMA" "$COMMIT" "$CABEZA" \
    || { echo "  $RAMA se movió mientras corría esto — no se toca"; exit 1; }
else
  git update-ref "refs/heads/$RAMA" "$COMMIT"
fi

echo "  $RAMA ← ${COMMIT:0:7}  $MENSAJE  [$ACCION]"
echo "  ($DESTINO; main intacta, sin push)"
