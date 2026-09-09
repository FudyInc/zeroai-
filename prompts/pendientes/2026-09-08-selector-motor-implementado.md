# Selector de motor por búsqueda — implementado por pedido de Diego

2026-09-08. Integrado localmente en main hasta 42fc6c8; cambios de CORE y DASHBOARD preservados en sus ramas. Sin push.

Buscar leads ahora presenta OpenAI, Anthropic y Qwen. Selección obligatoria en el formulario, aislada por corrida, sin fallback a otro motor. API anteriores conservan su selección automática si omiten provider. Error de inicio mantiene el formulario; submit bloqueado durante la petición.

Verificación: suite CORE 1016 tests OK, frontend 12 OK, build OK; 8 pruebas nuevas de selección/aislamiento/errores. Navegador desktop y móvil: envío de provider y conservación del formulario ante 503. Ruta start-selected impide que un backend anterior ignore silenciosamente el campo provider.

PENDIENTE OPERATIVO: reiniciar zero-backend.service. Está activo como servicio de sistema, sin --reload; sudo -n exigió contraseña. El proceso activo aún no reconoce provider. Ejecutar en terminal con permisos:

    sudo systemctl restart zero-backend.service

Luego recargar dashboard. OpenAI y Anthropic requieren claves configuradas; no se hicieron llamadas pagadas ni búsquedas reales en la verificación. No volver a encargar la implementación: falta solo activar el backend actualizado.

## Activación verificada — 2026-09-08

RESUELTO el pendiente operativo anterior: zero-backend.service activo desde 19:40:47 -03. El OpenAPI del proceso en :8800 incluye RunRequest.provider y /api/pipeline/start-selected. Vite en :5173 sirve el selector pipeline-provider y el cliente que llama a start-selected. No hace falta otro reinicio. No se ejecutaron búsquedas reales ni llamadas pagadas para esta comprobación.
