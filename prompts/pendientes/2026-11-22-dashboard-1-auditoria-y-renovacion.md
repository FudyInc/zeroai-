[TARGET: 🖥️ DASHBOARD] — si tu sección / $CLAUDE_ROLE no es DASHBOARD, detente y dilo.

OBJETIVO
Dejar el dashboard del operador (`frontend/`) coherente, sin pantallas rotas ni datos
disfrazados, y listo para recibir el módulo de onboarding de clientes — partiendo de una
auditoría con evidencia, no de gustos.

CONTEXTO
- Diego, 2026-11-22: "mejorar visual y funcionalmente todo el dashboard", porque el agente
  de WhatsApp está próximo a estar listo y vienen clientes nuevos.
- Dirección visual APROBADA (no se reinventa): editorial premium, casi monocromo, hairline
  cálido, sin glassmorphism ni sombras pesadas; slate `#2C3529` para titulares/primario,
  pewter para grises, champagne gold una sola vez por vista; Montserrat display con
  `tracking-tight` en números/titulares; eyebrows uppercase `tracking-[0.13em]`.
  Primitivas fuente de verdad en `frontend/src/components/ui.jsx`: `Card`, `Button`
  (píldora), `Eyebrow`, `SectionTitle` — se usan y se extienden, no se duplican.
- Tablas/kanban densos (Leads, Pipeline) sin decoración, conservando los colores
  semánticos de `lib/util.js STAGES`.
- Dashboard de uso interno, SOLO desktop (1440px). No optimizar ni probar móvil.
- No nombrar empresas competidoras como referencia en código, comentarios ni docs.
- Rechazar los defaults genéricos de agente (fuentes, gradientes, tarjetas-arcoíris).

PASO 0 — rama (medido hoy)
`/home/diego/zero-dashboard`, rama `dashboard`: 123 commits atrás de `origin/main`, 1 adelante
pero ya en main (`git cherry` lo marca `-`). Tiene 10 archivos sin commitear de hace
~13 días; `Leads.jsx` y `lib/leadIdentity.js` ya son idénticos a main, `Pipeline.jsx`
difiere en ~118 líneas y `App.jsx` en 4.
1. NO uses `git stash` ni borres nada. Guarda el WIP como commit en una rama de respaldo:
   `git switch -c dashboard-wip-2026-11-09 && git add -A && git commit -m "wip: dashboard sin commitear al 2026-11-22"`.
2. `git fetch origin && git switch -c feat/dashboard-renovacion origin/main`.
3. Reporta si algo del WIP de `Pipeline.jsx`/`App.jsx` sigue valiendo frente a main. No lo
   apliques sin decirlo.
OJO: la rama `FudyInc/finanzas-pooledge` tiene 5 commits propios + 21 archivos sin commitear
que tocan `Pipeline.jsx`, `lib/api.js` y `PoolEdgeExcelReview.jsx`. No reestructures esos
tres archivos; ajustes de estilo puntuales sí, y repórtalos.

FASE A — auditoría (entregable antes de cambiar nada grande)
Levanta la app real (`cd frontend && npm run dev`, API local con `./start.sh`) a 1440px y
recorre las 19 rutas de `App.jsx` con cada rol de `lib/roles.js` que la vea. Escribe
`docs/auditoria/2026-11-22-dashboard.md` con una tabla: ruta · hallazgo · severidad ·
evidencia (captura en `docs/auditoria/capturas/2026-11-22/` o la request de red que falla).
Severidades:
- P0: pantalla rota, request que da 404/500 no manejado, dato de plantilla/mock mostrado
  como real (viola el principio 1: sin dato real se muestra vacío CON el motivo).
- P1: inconsistencia con la dirección visual (clases sueltas en vez de primitivas, más de
  un acento gold por vista, tipografía fuera de sistema), estados vacíos/carga/error
  ausentes, navegación confusa o páginas que se solapan (revisa Dashboard/Vender/Avances
  y Funciones/Ciclo/Aprobar).
- P2: pulido.
Cierra la fase con una propuesta de navegación del Sidebar agrupada por tarea
(p.ej. Operación · Ventas · Clientes · Sistema) que deje un hueco para "Onboarding" dentro
de Clientes. Fusionar o eliminar páginas = pedir confirmación a Diego antes.

FASE B — implementación
Arregla todos los P0 y los P1 dentro de `frontend/`. Si un P0 es del backend (endpoint que
falta o responde mal), NO lo parches en el frontend con datos inventados: muestra el estado
de error con el motivo y repórtalo para CORE.

ALCANCE
Puedes tocar: `frontend/` (excepto lo indicado arriba de finanzas), `docs/auditoria/`.
NO tocar: `api.py`, `zero/`, `prompts/*.md`, `web/` (eso es LANDING), `tests/` de Python.

CONSTRAINTS
Operación real (sin mock en el producto; vacío + motivo), presentación separada de los
datos (el frontend no decide reglas de negocio), cero gasto, cero dependencias npm nuevas
salvo que Diego lo apruebe, `git status` antes de editar.

ACEPTACIÓN
- `python3 -m unittest discover -s tests -t .` en verde (desde la raíz).
- `cd frontend && npm run build` sin errores ni warnings nuevos; tests de frontend que
  existan (`*.test.js`) en verde.
- El informe de la Fase A existe con capturas y cada P0/P1 marcado como arreglado (con la
  captura del después) o reportado a otra sección.
- Captura de cada ruta después del cambio, abierta por Diego en desktop.

REPORTE
Resumen corto: qué cambió por ruta, qué quedó pendiente y por qué, decisiones que necesita
Diego (fusiones de páginas, nav), y hallazgos de otras secciones (repórtalos, no los arregles).
