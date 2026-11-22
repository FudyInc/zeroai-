[TARGET: 🖥️ DASHBOARD] — si tu sección / $CLAUDE_ROLE no es DASHBOARD, detente y dilo.
PRERREQUISITO: el pedido de CORE `prompts/pendientes/2026-11-22-core-onboarding-datos.md`
fusionado en `origin/main` y el pedido DASHBOARD-1 (`2026-11-22-dashboard-1-auditoria-y-renovacion.md`)
cerrado. Si `GET /api/onboarding/status` no existe en tu API local, detente y dilo — no
construyas contra datos inventados.

OBJETIVO
Un módulo "Onboarding" donde, para un cliente, se sube su catálogo y sus preguntas
frecuentes, se revisa la vista previa con errores por fila, se aplica, y se ve en una sola
lista de chequeo si su agente de WhatsApp ya está listo para salir.

CONTEXTO
- Diego, 2026-11-22: la empresa que contrata solo debería tener que meter su base de datos
  para que el agente funcione en su canal de WhatsApp.
- v1 lo opera la agencia (roles admin y cco) desde el dashboard. Dar acceso directo a la
  empresa cliente (rol nuevo) es una decisión de Diego que NO está tomada: no la implementes;
  deja anotado en el reporte qué haría falta.
- Contrato del backend (CORE): `GET /api/onboarding/template?kind=catalogo|faq`,
  `POST /api/onboarding/preview?client=X` con `{kind, filename, content_base64}`,
  `POST /api/onboarding/apply?client=X` con `{token, motivo}`,
  `GET /api/onboarding/status?client=X`. Lee el reporte de CORE: si el contrato cambió,
  manda el de CORE.
- Ya existen y se reutilizan: `components/KnowledgeHistory.jsx` (versiones/rollback de la
  ficha), `components/AgentTester.jsx` y `components/CasesLab.jsx` (probar el agente), la
  edición de ficha y precios en `pages/Whatsapp.jsx`, credenciales de canal en
  `pages/Config.jsx`. Enlaza o embebe; no los dupliques.

DISEÑO
- Ubicación: dentro del grupo Clientes del Sidebar que definió DASHBOARD-1; ruta
  `/clientes/:id/onboarding`, con acceso desde la ficha del cliente en `pages/Clientes.jsx`.
  Registrar la ruta en `lib/roles.js` (admin + cco) y en `App.jsx`.
- Pasos en una sola vista (no wizard de pantallas): 1 Ficha · 2 Catálogo · 3 Preguntas
  frecuentes · 4 WhatsApp conectado · 5 Probar el agente. Cada paso muestra su estado
  desde `/api/onboarding/status` (ok / falta + `detalle` + `accion`).
- Catálogo y FAQ: botón "Descargar plantilla", zona de soltar archivo (CSV/XLSX, el
  archivo se lee con `FileReader` a base64), tabla de vista previa con las filas con error
  resaltadas y el motivo, resumen nuevas/cambian/sin cambio, y "Aplicar" deshabilitado si
  hay 0 filas válidas. Tras aplicar, refrescar status y mostrar la versión nueva de la ficha.
- `409` (cliente bloqueado, p.ej. PoolEdge) y `413` (archivo grande) se muestran con el
  motivo que devuelve la API, tal cual.
- Estilo: la dirección aprobada (primitivas de `components/ui.jsx`, hairline, slate,
  un solo acento champagne gold — el indicador de "listo para salir"). Solo desktop.

ALCANCE
Puedes tocar: `frontend/` (página nueva `pages/Onboarding.jsx`, componentes nuevos,
`lib/api.js` solo para agregar las 4 llamadas, `App.jsx`, `lib/roles.js`, `Sidebar.jsx`,
`pages/Clientes.jsx` para el acceso).
NO tocar: `api.py`, `zero/`, `prompts/*.md`, `web/`.

CONSTRAINTS
Operación real: sin mock ni datos de ejemplo en el producto; vacío + motivo. Presentación
separada de los datos: los límites (tamaño, columnas obligatorias, qué es "listo") vienen
del backend, el frontend no los repite en código. Cero dependencias npm nuevas (nada de
librerías de Excel: el parseo es del backend). Cero gasto. `git status` antes de editar.
No probar contra datos de un cliente real: usar un cliente de prueba (con Supabase activo,
las escrituras van a la nube).

ACEPTACIÓN
- `python3 -m unittest discover -s tests -t .` en verde.
- `cd frontend && npm run build` sin errores.
- Recorrido real grabado en capturas (`docs/auditoria/capturas/2026-11-22/onboarding-*.png`):
  cliente de prueba vacío (todo en "falta") → descargar plantilla → subir CSV con 1 fila
  mala (se ve el error) → aplicar → status actualizado → rollback desde KnowledgeHistory
  vuelve atrás. Más una captura del 409 al intentar aplicar en `losetaschile`.
- Diego lo abre en desktop y completa el recorrido sin ayuda.

REPORTE
Resumen corto de lo construido, capturas, lo que faltaría para que la empresa cliente lo
use sola (rol, alcance, invitación), y hallazgos de otras secciones (repórtalos, no los arregles).
