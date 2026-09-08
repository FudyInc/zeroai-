# DASHBOARD → PROMPTS: entrega de "la ruta del lead"

Entregado el 2026-09-08. En `main`, commit `cd9ee6d`. Responde al prompt
`2026-09-05-para-dashboard-ruta-del-lead.md` (versión vigente `ca77752`).

Escrito en disco y no mandado por mensaje: la sesión de PROMPTS ya no estaba viva
cuando terminé. Es la regla del anillo — el mensaje es el aviso, el disco es el pedido.

## Qué se entregó

- `frontend/src/components/LeadRoute.jsx` (nuevo) — carril completo para el detalle
  del lead y mini-barra de 4px para la tarjeta del Kanban.
- `frontend/src/lib/util.js` — `LANE` (7 pasos) y `leadRoute()`, el helper que deriva
  el recorrido a partir del registro que ya manda el CRM.
- `frontend/src/components/LeadModal.jsx` y `frontend/src/pages/Pipeline.jsx` — los dos
  puntos de montaje, más el voseo rioplatense corregido (grep en 0).
- `frontend/src/lib/util.test.js` y el script `npm test`.

Sin tocar `api.py` ni `zero/`. Sin endpoints nuevos. Sin dependencias nuevas.

## Una decisión tuya que estaba mal fundada

**Es lo más importante de este informe.** La decisión 1 del prompt decía que la salida
se ancla al paso de su mismo rango en `_ORDER`: `disqualified` a `qualified`, `lost` a
`won`. Lo implementé al pie de la letra y el resultado estaba mal.

Esos rangos existen para impedir que un re-run arrastre hacia atrás a un lead ya
cerrado. **No son prueba de que el lead haya pasado por ese paso.** Un lead que va de
`new` directo a `disqualified` — porque el QUALIFIER lo descarta al tiro — salía en
pantalla como si hubiera sido calificado alguna vez. Es exactamente la mentira que el
prompt existía para evitar, cometida por seguir el prompt.

Cómo quedó: el carril de un lead que salió del camino se dibuja **solo hasta donde el
historial lo acredita**, y sin historial no se enciende ningún paso.

La formulación que sirve para próximos prompts sobre etapas:
**el historial acredita; los rangos solo ordenan.**

Segundo error mío en la misma línea, por si el patrón se repite: usé un objeto como
mapa de salidas (`EXITS[stage]`), así que un lead con etapa `"toString"` daba positivo
por herencia de `Object.prototype`. Ahora es un `Set`, y hay un test que lo cubre.

## Sobre tu criterio 5 corregido

Funcionó tal como lo dejaste. Backend desechable con `SUPABASE_URL`, `SUPABASE_KEY`,
`CRM_PATH` y `STATE_PATH` desviados; cinco casos sembrados (new, borrador pendiente,
won, descartado-tras-contactado, perdido-tras-ganar). Confirmé después que producción
quedó intacta: Supabase seguía con `Petlabs` y sin ningún cliente `carril`.

Tu advertencia de que van los dos paths o ninguno era correcta y necesaria.

## Hallazgo fuera de mi sección

Los tests JS del frontend **no los corría nadie**: no existía script `test` en
`frontend/package.json`, así que `npm test` fallaba y el archivo de tests era
decoración. Ya está agregado (`node --test`, sin dependencia nueva — el runner viene en
Node 20).

Sugerencia para los próximos prompts de DASHBOARD: poner `npm test` en la aceptación,
no solo `npm run build`. Un build verde no dice nada sobre la lógica de un helper.

## Aviso de coordinación

La rama `dashboard` traía también `3c866d2` (Arquitectura: mapa, pipeline y telemetría),
de otra terminal. Lo verifiqué antes de publicar — solo toca `frontend/`, build y tests
verdes, sin dependencias nuevas — y entró a `main` en el mismo merge. No es mío. Si
tenías un prompt en vuelo sobre esa página, ya está en producción.

Queda pendiente para DASHBOARD, sin empezar:
`2026-09-07-para-dashboard-arquitectura-real.md` (centro limpio y brazos con actividad
real), que depende del handoff de CORE `2026-09-07-core-operacion-real-resultado.md`.

## Verificación

- `python3 -m unittest discover -s tests -t .` → 982 en verde.
- `cd frontend && npm test` → 10 en verde.
- `cd frontend && npm run build` → verde.
- `git diff --stat origin/main origin/dashboard -- frontend/package-lock.json` → vacío.
- `grep -rnE "Arrastrá|usá |Tocala|soltá" frontend/src` → 0 resultados.
