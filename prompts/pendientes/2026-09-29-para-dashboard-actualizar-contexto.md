# PROMPTS → DASHBOARD: puesta al día antes de recibir trabajo nuevo

[TARGET: DASHBOARD]

Trabaja desde `/home/diego/zero-dashboard`. Esta primera fase es de reconocimiento: actualiza tu conocimiento de la rama, del producto y de las dependencias con CORE. No implementes el encargo de arquitectura ni edites código todavía. Devuelve un informe breve y verificable para que podamos decidir el siguiente prompt.

## Comprobación inicial

1. Lee `CLAUDE.md` y las instrucciones vigentes del workspace. Ejecuta `git status --short`, `git branch --show-current`, `git log -8 --oneline` y compara `dashboard` con `main` usando los commits locales disponibles. Conserva los archivos sin seguimiento y cualquier trabajo ajeno; no hagas `reset`, `clean`, merge, push ni despliegue.
2. Inspecciona el frontend actual: rutas en `frontend/src/App.jsx`, páginas `Arquitectura.jsx` y `Ciclo.jsx`, `components/ArchitectureBrain.jsx`, `components/CicloPanel.jsx`, `lib/architecture-activity.js`, `lib/api.js` y sus pruebas. Identifica qué hace hoy cada vista y qué endpoints consume. Lee el código vigente antes de usar documentos históricos.
3. Revisa `prompts/pendientes/2026-09-07-para-dashboard-arquitectura-real.md` y `2026-09-07-contrato-actividad-real.md` como encargos históricos pendientes de cotejo, no como prueba de implementación. Busca si CORE entregó un handoff posterior y verifica directamente el contrato efectivo de `GET /api/agents/telemetry` en el backend actual. Distingue especificación, implementación y despliegue; una rama con código nuevo no demuestra que el servicio activo ya lo use.
4. Consulta la auditoría más reciente disponible en el historial local, incluido `docs/auditoria/2026-09-29.json` si existe. Separa hallazgos de DASHBOARD de los de CORE o WhatsApp. No repitas trabajos cerrados por commits posteriores.

## Pistas comprobadas al redactar este prompt (29-09-2026)

- `dashboard` estaba en `f802c1b`, con tres archivos antiguos sin seguimiento en `prompts/pendientes/`. `main` local estaba en `e953bed`; había un commit en `main` que no estaba en `dashboard`. Vuelve a medirlo: esta foto puede quedar obsoleta.
- El commit `f802c1b` quitó las terminales de Conductor de la vista y dejó el ciclo en `pages/Ciclo.jsx` y `components/CicloPanel.jsx`. No encargues reconstruir la antigua pantalla Conductor.
- El centro del mapa ya se simplificó (`36f845a`) y el motor de la última ejecución ya se etiqueta como histórico (`87913da`). En cambio, `ArchitectureBrain.jsx` aún calculaba `fresh` con resultados recibidos hace menos de 12 segundos y usaba eso para iluminar brazos. Verifica si sigue así.
- `GET /api/agents/telemetry` devolvía `resumen()` y `recientes`; no se observó el campo `actividad` del contrato v1 ni un handoff de CORE que lo confirme. La filtración por nombre de motor en `architecture-activity.js` no certifica por sí sola que una corrida haya sido real. No afirmes actividad en curso con esos datos.
- La auditoría local del 29-09 registró tres fallos de la suite Python relacionados con WhatsApp y build del dashboard aprobado. Son datos de esa auditoría, no un resultado de pruebas ejecutadas por ti ni necesariamente el estado actual.

## Entrega de esta fase

Responde con: HEAD y estado de la rama; capacidades actuales de Arquitectura y Ciclo; matriz `hecho / pendiente / bloqueado por CORE / incierto` para el encargo del 07-09 con evidencia de archivo o commit; contrato de telemetría realmente disponible; hallazgos recientes relevantes para DASHBOARD; y pruebas que ejecutaste con sus resultados. Si no corres pruebas, dilo. Indica el siguiente trabajo concreto que recomendarías, sin iniciarlo. No uses datos reales ni ejecutes campañas, llamadas o envíos para demostrar la interfaz.
