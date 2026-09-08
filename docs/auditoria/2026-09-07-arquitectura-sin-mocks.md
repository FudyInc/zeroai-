# AUDIT → PROMPTS → DASHBOARD: arquitectura y operación sin mocks

Fecha: 2026-09-07. Pedido explícito de Diego.
Estado: entregado a la bandeja de PROMPTS; pendiente de elaboración, envío e implementación. No afirmar que ya está corregido.

## Pedido

Auditar y retirar simulaciones de la operación visible, especialmente Concierge. Simplificar el centro del mapa: el logo actual se ve mal y los textos deben quedar centrados. Prioridad visual: los brazos que unen ZERO con cada agente deben iluminarse cuando ese agente realmente está trabajando. PROMPTS debe preparar y remitir el encargo a DASHBOARD, coordinando antes con CORE las dependencias de backend.

## Evidencia y alcance comprobados

Lectura estática, sin ejecutar agentes ni enviar mensajes a leads. Árboles examinados: AUDIT c3ccc1a (antiguo), main/core 986daca y dashboard 3c866d2. No extrapolar el código antiguo de AUDIT a producción. No se verificó visualmente el navegador ni la configuración del motor desplegado.

- DASHBOARD: `frontend/src/components/ArchitectureBrain.jsx` calcula `fresh` con resultados de menos de 12 segundos y construye `active` a partir de ellos, incluidos errores y mocks. Eso ilumina brazos DESPUÉS del resultado, no durante una llamada. La propia leyenda y el pie lo reconocen.
- CORE/main: `zero/orchestrator.py`, `dispatch`, llama a `telemetry.registrar` después de `agent.run`. Falta una señal de ejecución en curso; frontend no puede deducirla honestamente de ese historial.
- DASHBOARD: el centro renderiza `/logo.png` más otro texto ZEROAI, ORQUESTADOR y una descripción dentro de 170 × 170 px. `architecture-brain.css` fija el logo a 70 × 70 y los nodos a `text-align: left`. El desagrado visual y el centrado solicitado vienen del reporte de Diego; no de una captura inspeccionada.
- DASHBOARD: `architecture-data.js` incluye Mock entre las tecnologías y `engineLabel` traduce el motor histórico mock. Concierge se selecciona por defecto; ver ese motor no prueba que sea el motor configurado actualmente.
- CORE/main: `api.py`, `_agents_best` y `_agents_for_client` pueden devolver `build_agents(mock=True)`; `_agent_op` vuelve a ejecutar la operación con mocks ante error del motor real o resultado vacío. Auditar todos sus consumidores, incluido Concierge, para retirar estas rutas del modo operativo.
- CORE/main: `zero/finance.py`, `get_finance`, produce datos de ejemplo si falta finance.json. La UI debe presentar ausencia de datos, no cifras inventadas.
- Meta Ads ya tiene una corrección en main contra fallback de campañas falsas (`api.py` alrededor de 710). Revalidarla: no encargar como pendiente el comportamiento antiguo visto en AUDIT.

Reproducción de la inspección:
```bash
rg -n 'fresh|active|logo.png|brain-core' /home/diego/zero-dashboard/frontend/src/components/ArchitectureBrain.jsx
rg -n 'text-align|brain-core img|brain-signal' /home/diego/zero-dashboard/frontend/src/components/architecture-brain.css
rg -n 'mock|def _agent_op|def _agents_best|def _agents_for_client' /home/diego/zeroai/api.py
rg -n 'def dispatch|agent.run|registrar' /home/diego/zeroai/zero/orchestrator.py
rg -n 'mock|def get_finance' /home/diego/zeroai/zero/finance.py
```

## PROMPTS: secuencia de entrega

1. Preparar tarea CORE: eliminar fallback a simulación en rutas operativas; ante motor o integración no disponible, devolver un estado explícito y recuperable. Recorrer API, agentes, finanzas, campañas y canales para cerrar otros caminos de datos ficticios. No basta quitar la palabra mock. Conservar fixtures aisladas de pruebas y el historial existente; no borrar CRM ni registros históricos, ni activar envíos reales como sustituto de la simulación.
2. Acordar un contrato de actividad con inicio, fin, error, identificador de ejecución y expiración/recuperación si el proceso muere. Resolver concurrencia: terminar una ejecución no debe apagar otro trabajo activo del mismo agente. El motor reportado debe corresponder a la ejecución efectiva. No incluir contenido de conversaciones.
3. Preparar y remitir a DASHBOARD la corrección visual y el consumo del contrato. El trabajo visual puede avanzar mientras CORE implementa; la aceptación de “trabajando” depende de la señal real.
4. Dejar trazabilidad de tareas/archivos enviados y resultados de verificación. Este archivo es un pedido persistente, no confirma que una sesión lo haya leído.

## Criterios para el prompt de DASHBOARD

- Centro limpio: retirar el logo grande de ese punto y usar un núcleo sencillo con ZERO y una etiqueta corta. Evitar marca duplicada y textos técnicos que recarguen el mapa.
- Nombre y descripción breve de cada agente centrados en su nodo, con ancho y altura consistentes, sin recortes ni cruces con brazos. Mostrar detalles técnicos en el panel secundario si se necesitan.
- Brazo y nodo iluminados mientras exista trabajo REAL en curso de ese agente. Centro activo cuando haya algún trabajo real. Reposo sin pulsos; error diferenciado; desconexión o datos vencidos sin fingir actividad. Seleccionar un agente no debe parecer una ejecución.
- No usar el resultado reciente como sustituto de “trabajando”. Si se conserva un destello de finalización, distinguirlo explícitamente de la ejecución en curso.
- Retirar Mock del catálogo de capacidades operativas. Los registros históricos simulados deben seguir identificados como simulación, separados de métricas y estados de actividad real; no renombrarlos como IA real ni borrarlos.
- Concierge sin motor disponible muestra “No disponible”/“Sin conexión” con el motivo accionable que entregue API; no respuesta simulada ni afirmación de estar trabajando.
- Mantener legibilidad móvil/escritorio y temas claro/oscuro. Respetar movimiento reducido: brillo estático de actividad y texto accesible, sin depender solo del color.

## Verificación exigida al implementar

CORE: pruebas de motor no configurado, timeout, respuesta vacía y fallo sin fallback mock; no generación de cifras/leads/mensajes ficticios; inicio/fin/error y concurrencia; limpieza de actividad obsoleta. Correr suite del núcleo tras cambios.
DASHBOARD: build y revisión visual a 360, 768 y 1440 px; comprobar reposo, ejecución larga, dos agentes simultáneos, finalización, error y backend caído. Los brazos deben encenderse ANTES de recibir el resultado y apagarse al terminar. Usar fixtures controladas solo en pruebas, fuera de la operación real.

No activar campañas, llamadas ni envíos para verificar. No declarar disponible una integración solo porque desapareció su etiqueta mock.
