# Dimensiones del dashboard — plan de implementación

**Objetivo:** extender a las vistas operativas la escala, jerarquía y uso del ancho del diseño reciente de WhatsApp.

**Referencia:** `frontend/src/pages/Whatsapp.jsx` y `frontend/src/pages/whatsapp.css`.

**Criterio visual:** cabecera amplia con título legible, descripción breve y dato contextual; separación de 28 px entre bloques; paneles y controles con espacio suficiente. Conservar paleta y tipografía existentes, modo oscuro y diseño móvil. La interfaz seguirá mostrando datos reales y estados de carga/error actuales.

## Tareas

- [x] Crear `WorkspaceHero` y sus estilos compartidos en `frontend/src/components/`, con título, descripción, etiqueta, icono y dato opcional.
- [x] Actualizar `Pipeline.jsx`: usar cabecera y secciones claras; mantener drag, selector de etapa, densidad y scroll horizontal.
- [x] Actualizar `Dashboard.jsx`, `Leads.jsx`, `Forecast.jsx`, `Clientes.jsx`, `Campanas.jsx` y `Agentes.jsx` con la cabecera y el ritmo de WhatsApp. Mantener las acciones y métricas existentes.
- [x] Ajustar las otras vistas del dashboard sin ampliar por fuerza los formularios estrechos.
- [x] Compilar el frontend y ejecutar sus pruebas: `npm run build` y `npm test` pasan el 2026-10-14.
- [ ] Revisar visualmente las vistas principales en móvil y escritorio con una sesión autorizada. El navegador local muestra el inicio de sesión.

**Riesgos a comprobar:** columnas del Kanban en ancho pequeño, controles de filtro con zoom de texto, estados sin cliente y modo oscuro.
