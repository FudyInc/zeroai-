# PROMPTS → DASHBOARD: centro limpio y brazos con actividad real

[TARGET: DASHBOARD]

Pedido autorizado por Diego. Leer `2026-09-07-de-audit-arquitectura-sin-mocks.md` y `2026-09-07-contrato-actividad-real.md`, entregados junto a este archivo.

Trabajar en /home/diego/zero-dashboard, solo frontend y reporte de entrega. Verificar HEAD/status antes de editar; preservar trabajo ajeno. Base inspeccionada: 3c866d2. No reemplazar la arquitectura existente desde una rama antigua.

## Lo que cambia

ArchitectureBrain.jsx hoy deriva fresh/active de resultados recibidos hace menos de 12 segundos. El brazo pulsa después de trabajar y puede hacerlo con mocks o errores. El centro repite logo y ZEROAI; los nodos no tienen el centrado pedido. architecture-data.js incluye Mock entre tecnologías operativas.

1. Simplificar el centro: quitar el logo grande de ese punto y usar ZERO con una etiqueta corta. Centrar nombre y descripción breve de cada agente; nodos de dimensiones consistentes, sin texto cortado ni brazos atravesándolo. Detalles técnicos en el panel secundario. No rediseñar otras páginas.
2. Consumir actividad v1 del contrato compartido. Brazo/nodo y centro activos solo por runs reales, running y vigentes. Selección tiene estilo distinto y nunca parece ejecución. Error diferenciado; reposo sin pulsos. Eliminar fresh como señal de trabajo. Actualizar leyendas, estados vacíos y pie que hoy describen pulsos de resultados.
3. Sin contrato, backend caído, snapshot vencido o status unavailable: mostrar actividad no disponible y apagar brillo de trabajo. React Query puede conservar caché: no reutilizarla como actividad vigente tras error. Diferenciar sin ejecuciones de sin conexión.
4. Motor efectivo del run activo; último motor histórico etiquetado como histórico, sin afirmar que es configuración actual. No presentar un motor genérico live como proveedor conocido. Concierge sin motor muestra No disponible y motivo accionable seguro de API, sin texto simulado.
5. Retirar Mock del catálogo operativo. Mantener historial simulado claramente etiquetado y separado de resumen_real. No borrar registros ni renombrarlos como IA real; datos antiguos indeterminados se muestran como desconocidos.
6. Reutilizar estilos/primitivas/movimiento existentes. Móvil/escritorio, claro/oscuro, navegación por teclado y texto accesible. Con movimiento reducido conservar brillo estático de actividad; no depender solo del color. Pausar animación no congela el estado real.

## Dependencia y entrega

El diseño puede avanzar ahora. La conexión y aceptación de actividad dependen del handoff CORE: `2026-09-07-core-operacion-real-resultado.md`. El contrato adjunto es una especificación encargada, no una API ya disponible. Si CORE cambia la forma, reconciliar contrato/consumidor explícitamente. No tocar api.py o zero/ para sortear la dependencia ni introducir timers que finjan trabajo.

Conservar el cliente API y manejo de errores centralizados existentes. Si hace falta UI fuera de Arquitectura para mostrar el error operativo de Concierge, limitar el cambio a ese consumidor y explicar la necesidad.

## Aceptación

- npm run build desde frontend.
- Revisar visualmente a 360, 768 y 1440 px, temas claro/oscuro y movimiento reducido; guardar capturas fuera del código de producción y reportar rutas.
- Fixtures SOLO en pruebas o harness aislado no importado por producción: reposo, llamada larga, dos runs del mismo agente, dos agentes, fin de uno mientras otro sigue, error, backend caído con caché, lease vencido, contrato ausente y registros simulados/desconocidos.
- Demostrar con llamada controlada que el brazo enciende antes del resultado, permanece durante trabajo largo y apaga al terminar. Con fixtures se valida la UI; el cierre de integración requiere además comprobar el contrato producido por CORE en un entorno aislado.
- Comprobar cero pulsos por selección, mock, error histórico o resultado reciente. No iniciar campañas, llamadas o envíos reales para obtener evidencias.

Dejar prompts/pendientes/2026-09-07-dashboard-arquitectura-real-resultado.md con archivos, pruebas/build, capturas, commit si existe y estado de integración con CORE. No declarar corregido lo que solo tiene fixture o implementación sin verificar.
