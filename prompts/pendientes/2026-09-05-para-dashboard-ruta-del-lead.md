# Prompt de PROMPTS a DASHBOARD — la ruta del lead (2026-09-05)

Escrito en disco porque al momento de mandarlo no había sesión de DASHBOARD viva. Pégalo
entero en la terminal de DASHBOARD. Nace de un pedido directo de Diego, no de AUDIT.

Verificado contra `origin/main` (1449e75) el 2026-09-05: el voseo sigue en las 2 líneas,
`LeadRoute.jsx` no existe, `motion.js`/`util.js` intactos, `_ORDER` sin cambios.

---

[TARGET: 🖥️ DASHBOARD]
Si tu sección no es DASHBOARD, detente y dilo: este trabajo toca solo frontend/.

ANTES DE EMPEZAR
  git fetch origin && git merge origin/main
  git status --porcelain   → limpio

OBJETIVO
Que al abrir un lead se vea, de un vistazo, por dónde va en su recorrido: un carril animado de
fases con la actual encendida, las cumplidas marcadas con su fecha real, y las salidas (descartado
/ perdido) representadas como lo que son — una salida del camino, no un paso más adelante.

CONTEXTO
- Todo el dato necesario YA llega al frontend. Verificado: /api/board devuelve crm.list(), que es
  el registro completo del lead — incluye `history` y `outreach`. /api/leads/{key} devuelve el
  mismo registro. NO necesitas endpoint nuevo y no vas a tocar api.py ni zero/. Si crees que falta
  un dato, repórtalo, no lo agregues.
- El lenguaje de movimiento ya existe y es una sola fuente: frontend/src/lib/motion.js (rise, fade,
  surface, stagger, staggerDense, SPRING, meterFill, prefersReducedMotion, EDITORIAL, DURATION).
  Lee su encabezado antes de escribir una animación. Lo extiendes si hace falta; no creas variantes
  nuevas dentro de las páginas.
- Las primitivas visuales están en frontend/src/components/ui.jsx (Card, Button, Badge, Eyebrow,
  SectionTitle...). Extender, no reinventar. Cero dependencias nuevas.
- Etapas y colores: frontend/src/lib/util.js (STAGES, ORDER), espejo de zero/config.py::CRM_STAGES.
  Los colores salen de STAGES[stage].c — no hardcodees ninguno.

DECISIONES YA TOMADAS (respétalas; no son negociables en este trabajo)

1. EL CARRIL SON 7 PASOS, NO 9.
   new → qualified → contacted → nurturing → replied → meeting → won
   `disqualified` y `lost` NO son pasos: son SALIDAS. La razón está en el código — zero/crm.py:37
   le da a `disqualified` el mismo rango que a `qualified`, y a `lost` el mismo que a `won`:
       "new": 0, "qualified": 1, "disqualified": 1, "contacted": 2, ...
   Un lead descartado NO está más avanzado que uno calificado. Si dibujas los 9 en fila, la UI
   miente. Cuando el lead está en una salida: dibuja el carril hasta el último paso que alcanzó y
   marca la salida como un desvío al final de ese punto, con el color de STAGES.disqualified.c /
   STAGES.lost.c; los pasos que nunca alcanzó quedan apagados.

2. LA APROBACIÓN HUMANA ES UN SUB-ESTADO, NO UNA ETAPA.
   El borrador esperando visto bueno es `lead.outreach.status === 'draft'` (definición canónica en
   zero/crm.py::pending_outreach_count). Represéntalo como una marca intermedia ENTRE `qualified` y
   `contacted` — un punto con pulso suave y la leyenda "esperando tu visto bueno", que al hacer
   clic lleva a /aprobar. Solo aparece si ese borrador existe. NO agregues una etapa al CRM ni a
   STAGES/ORDER: la política de etapas vive en zero/config.py y no se toca desde aquí.

3. LAS FECHAS SALEN DEL HISTORIAL REAL, Y EL HISTORIAL TIENE HUECOS.
   · La posición actual la manda `lead.stage`, siempre. Nunca la deduzcas del historial.
   · Las fechas de los pasos cumplidos salen de los eventos {event: 'stage'} de `lead.history`,
     cuyo `detail` tiene la forma "new → qualified" (zero/crm.py:119).
   · El paso `new` NO tiene evento: upsert crea el registro sin registrarlo (zero/crm.py:84). Un
     paso cumplido sin evento se muestra cumplido y SIN fecha. Prohibido inventar o interpolar una
     fecha.
   · El recorrido NO es monótono: set_stage es incondicional (zero/crm.py:111), así que arrastrar
     una tarjeta hacia atrás en el Kanban hace retroceder al lead de verdad. Dibuja el estado
     ACTUAL; si el historial tiene un retroceso, que se lea en la lista de eventos, no que rompa el
     carril.
   · "Hace N días" en el punto actual: calcúlalo del último evento `stage` que lleve a la etapa
     actual. Sin ese evento, no muestres antigüedad.

4. MOVIMIENTO CON CRITERIO, NO REPLAY.
   · Entrada del carril: `rise` para el conjunto, `stagger()` para los puntos.
   · El relleno de la línea entre puntos usa `meterFill` — es el único elemento que puede pasar de
     ~380 ms, porque ahí el recorrido ES el dato.
   · Se anima UNA vez al montar, y cuando el lead cambia de etapa estando visible. No un replay en
     cada re-render de react-query.
   · prefersReducedMotion() se respeta: sin desplazamiento, se mantiene el cambio de opacidad, el
     relleno salta al valor final.

SCOPE — archivos que puedes tocar
  NUEVO: frontend/src/components/LeadRoute.jsx — el componente, con dos tamaños:
     <LeadRoute lead={r} />            completo, con etiquetas y fechas
     <LeadRoute lead={r} compact />    mini-barra de puntos, sin texto
  frontend/src/components/LeadModal.jsx — la versión completa, entre el bloque del Badge de etapa
     (línea ~78) y el de "Por qué calificó".
  frontend/src/pages/Pipeline.jsx — la mini-barra en la tarjeta del Kanban. No debe romper el
     arrastre (draggable/onDragStart) ni el modo compacto; en compacto va igual, es 4px de alto.
  frontend/src/lib/util.js — aquí van el carril (LANE) y el helper que deriva el recorrido de un
     lead, junto a STAGES/ORDER que ya viven ahí. Con comentario que explique por qué el carril
     tiene 7 y no 9.
  frontend/src/lib/motion.js — solo si necesitas una variante nueva y compartible.

DE PASO, EN EL MISMO CAMBIO
Corregir el voseo rioplatense de Pipeline.jsx a español neutro. Son 2 líneas y es el único lugar
del frontend donde quedó.
  · línea 50: "Arrastrá una tarjeta ... o usá el menú. Tocala para ver el detalle."
  · línea 104: "soltá aquí"
Deja "Arrastra ... o usa el menú. Tócala para ver el detalle." y "suelta aquí".
Verificación: grep -rnE "Arrastrá|usá |Tocala|soltá" frontend/src  →  0 resultados.

NO TOCAR
  api.py · zero/** · web/** · tests/ del núcleo · supabase_schema.sql
  frontend/src/pages/Conductor.jsx y components/conductor/** — ahí se entregó la vista del ciclo
  autónomo (1449e75); no es tuyo en este trabajo.
  Nada de endpoints nuevos. Nada de dependencias nuevas (framer-motion, lucide-react,
  @tanstack/react-query y sonner ya están; no agregues ninguna otra).

RESTRICCIONES
- Presentación separada de los datos: este componente DIBUJA, no decide. Ninguna regla de negocio
  nueva.
- Paleta ZEROAI (slate, pewter, champagne gold, off-white). Colores de etapa desde STAGES[stage].c.
  Cero verdes hardcodeados — eso ya se erradicó una vez (a18faab), no lo reintroduzcas.
- Modo oscuro incluido: tiene que leerse en ambos.
- App de escritorio, solo la usa la agencia desde PC. No inviertas en móvil.
- git status antes de editar: hay otros terminales con trabajo en vuelo.

ACEPTACIÓN — todo verificable corriendo
  1. python3 -m unittest discover -s tests -t .   → verde (al escribir esto: 975 tests OK)
  2. cd frontend && npm run build                  → verde, sin warnings nuevos
  3. git diff --stat frontend/package.json frontend/package-lock.json  → VACÍO
  4. grep -rnE "Arrastrá|usá |Tocala|soltá" frontend/src  → 0 resultados
  5. Abre el dashboard (./start.sh) y comprueba los cuatro casos, con captura o descripción:
     a. Lead en `new`          → primer punto encendido, resto apagado, sin fecha.
     b. Lead con outreach.status === 'draft' → la marca de "esperando tu visto bueno" aparece entre
        calificado y contactado, y lleva a /aprobar al hacer clic.
     c. Lead en `won`          → carril completo, relleno hasta el final.
     d. Lead en `disqualified` → el carril llega hasta donde llegó y muestra la salida, NO un punto
        al final de la fila. Este es el caso que separa un buen trabajo de uno que miente.
  6. Kanban: la mini-barra se ve en cómodo y en compacto, y arrastrar una tarjeta entre columnas
     sigue funcionando.
  7. Con "reducir movimiento" activo: el carril aparece sin desplazamiento y el relleno salta al
     valor final. Nadie pierde información.

REPORTE
Resumen corto de qué cambiaste y por qué, y una lista aparte de cualquier cosa que encuentres FUERA
de tu sección (api.py, zero/, otro workspace). Repórtala, no la arregles.
