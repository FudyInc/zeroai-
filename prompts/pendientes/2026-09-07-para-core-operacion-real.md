# PROMPTS → CORE: operación sin fallback simulado y actividad en curso

[TARGET: CORE]

Pedido autorizado por Diego. Leer el pedido de AUDIT y `2026-09-07-contrato-actividad-real.md`, entregados junto a este archivo. Implementar backend; entregar contrato comprobado a DASHBOARD.

## Antes de tocar código

Trabajar en /home/diego/zero-core. Inspeccionar HEAD y git status. Al preparar este encargo, HEAD era 986daca y había cambios ajenos sin commit en api.py, scripts/auditar.py y tests/test_auditar.py (checks omitidos). No descartar, commitear ni mezclar esos cambios como propios. Coordinar el solapamiento en api.py; no hacer merge ni exigir limpieza borrando trabajo en vuelo. Revalidar cada hallazgo contra el árbol actual.

## Evidencia verificada por PROMPTS

- api.py::_agents_best acaba en build_agents(mock=True). _agent_op reejecuta fn con mocks ante excepción o respuesta vacía: puede inventar una respuesta y repetir efectos parciales.
- La función mencionada por AUDIT como _agents_for_client no existe en este árbol. Sí existe _agents_autonomous, que también puede devolver mock: rastrear consumidores y guardas efectivas.
- _exigir_motor_real ya protege el pipeline y conserva ZERO_PIPELINE_MOCK_OK para pruebas. No quitar esa protección ni habilitar el override en despliegue.
- Zero.dispatch registra telemetría después de agent.run; una excepción incluso puede saltarse ese registro. telemetry tiene historial y lock de threads, sin protocolo de actividad compartida.
- FallbackBackend cuenta fallbacks globalmente; eso no identifica el proveedor usado por una invocación concurrente.
- Finanzas YA retiró costos de ejemplo: summary(None, ...) retorna source=sin_datos e history vacío. Algunos docstrings antiguos todavía dicen mock. No implementar un get_finance inexistente ni repetir el arreglo. Verificar semántica de ausencia frente a cero real y corregir documentación pertinente.
- Las campañas y el pipeline recibieron protecciones en 986daca. Revalidarlas con pruebas, no deshacerlas.

## Trabajo

1. Mapear rutas operativas y consumidores: API interactiva, Concierge entrante, acciones/scheduler, pipeline, campañas, finanzas y canales. Reportar tabla ruta → origen de datos → comportamiento sin motor/integración. Identificar también llamadas directas a agentes fuera de dispatch.
2. Eliminar fallback a simulación donde produzca respuestas, leads, cifras o estados ficticios. Distinguir construir un orquestador con agentes sin usar de ejecutar realmente esos agentes: no romper una acción determinista por un mock que nunca se invoca. Preservar mocks explícitos de tests/demo aislados, sin que entren al CRM o métricas operativas.
3. Aplicar errores del contrato; no sustituir la simulación por un envío real ni por un nuevo respaldo pagado. Conservar prioridades y respaldos reales YA autorizados, permisos, revisión humana y límites de envío. No cambiar políticas comerciales.
4. Implementar inicio/fin/error, concurrencia, lease, recuperación, proveedor efectivo y resumen real según el contrato adjunto. La telemetría no debe romper el trabajo que observa; su indisponibilidad debe ser visible. Mantener esquema histórico y consumidores antiguos.
5. Dejar handoff persistente en prompts/pendientes/2026-09-07-core-operacion-real-resultado.md y entregar una copia a DASHBOARD. Registrar si solo se depositó el archivo o si hubo acuse de lectura.

Alcance: api.py, zero/telemetry.py, zero/orchestrator.py, zero/backends.py, pruebas relevantes; otros módulos del núcleo solo cuando el mapa de consumidores demuestra una ruta ficticia operativa. Sin frontend ni nuevas dependencias. Cambios necesarios en motores de WhatsApp/llamadas requieren coordinar su sección; documentar cualquier dependencia abierta y no dar el conjunto por terminado.

## Aceptación

- Tests sin red para motor ausente, configuración inválida, timeout, respuesta vacía inválida, resultado vacío válido y excepción después de un efecto parcial. Probar que no se vuelve a invocar fn con mocks, no se escriben datos ficticios y no se repite el efecto.
- Una llamada controlada bloqueada debe verse running ANTES de liberarla. Probar dos ejecuciones simultáneas del mismo agente, dos agentes, error devuelto y excepción lanzada, renovación durante llamada larga, proceso muerto/reinicio, expiración y fallo de almacenamiento. Terminar una no apaga la otra.
- Probar cambio al respaldo permitido con atribución por ejecución concurrente. Eventos simulados/históricos desconocidos no cuentan como actividad ni métricas reales.
- Compatibilidad del endpoint y permisos actuales; ausencia de conversaciones/secretos. Fixtures antiguas de telemetría siguen legibles.
- Revalidar finanzas sin archivo y campañas sin integración sin inventar datos. Correr python3 -m unittest discover -s tests -t . desde el worktree y reportar resultados reales, diferenciando fallos previos si aparecen.
- Todas las pruebas con rutas temporales: CRM, STATE, finanzas y telemetría; proveedores y canales sustituidos en tests. No activar campañas, llamadas, envíos ni agentes reales para verificar. No tocar .env, datos persistentes, deploy o la cola automática.

Reporte: archivos propios, pruebas y resultados, commit si se creó, rutas auditadas/protegidas, riesgos o cobertura pendiente y handoff del contrato. Implementado, probado e integrado son estados distintos.
