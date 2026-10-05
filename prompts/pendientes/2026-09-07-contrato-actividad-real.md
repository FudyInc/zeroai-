# Contrato de entrega CORE → DASHBOARD: actividad real v1

Estado: especificación para implementar; todavía no es una API disponible ni un acuerdo confirmado por CORE.
Origen: `2026-09-07-de-audit-arquitectura-sin-mocks.md`. Ambos encargos dependen de este archivo.

## Interfaz elegida

Extender GET `/api/agents/telemetry` de forma aditiva, conservando sus campos actuales y permisos. No crear un segundo origen de verdad para el mapa.

Agregar `actividad` con esta forma (ejemplo documental, nunca respuesta de producción):

```json
{
  "version": 1,
  "observed_at": 1788822000,
  "expires_at": 1788822015,
  "status": "ok",
  "reason": null,
  "runs": [{
    "run_id": "identificador-unico-por-invocacion",
    "agent": "CONCIERGE",
    "state": "running",
    "execution_kind": "real",
    "engine": "local",
    "model": "modelo-efectivo",
    "started_at": 1788821990,
    "updated_at": 1788822000,
    "expires_at": 1788822030,
    "finished_at": null,
    "error_code": null
  }]
}
```

- Timestamps: segundos Unix UTC. `state`: `running`, `completed`, `error`, `expired`. `execution_kind`: `real`, `simulation`, `unknown`. Motor/modelo desconocidos: null, nunca inferidos de la configuración histórica.
- `status`: `ok` o `unavailable`. Fallo del registro no equivale a `runs: []` con estado ok. Sin campo `actividad`, el frontend muestra actividad no disponible (backend anterior).
- `run_id` es único por invocación, incluso con el mismo task_id. La finalización afecta solo a ese run. Publicar inicio antes de llamar al backend; cerrar éxito/error/excepción en todos los caminos. Retención acotada de finales; los activos no se expulsan silenciosamente al llenar el historial.
- Actividad significa ejecución real invocada, no tarea en cola ni clic. Una llamada a un proveedor que termina fallando sí estuvo en curso. Si no hay motor, devolver indisponibilidad sin fabricar una ejecución real.
- El brazo está encendido si existe al menos un run real, running y vigente del agente, y el snapshot sigue vigente. El centro usa la misma condición sobre cualquier agente. Ni simulation ni unknown iluminan.
- Snapshot: vigencia de 15 segundos; consultar cada 2 segundos mientras la página esté visible. El cliente calcula edad con el reloj del servidor y el tiempo transcurrido desde la recepción, evitando depender de relojes sincronizados. Un error de consulta apaga la actividad y muestra desconexión aunque la caché conserve datos.
- Lease de ejecución: renovación real al menos cada 10 segundos y expiración a los 30 segundos sin renovación. Una llamada bloqueante larga debe seguir renovando. GET no renueva ejecuciones. Al reiniciar, ningún registro huérfano vuelve a running por leerlo del disco.
- CORE elige el mecanismo mínimo compatible con los procesos reales que ejecutan agentes: explicar cobertura API/worker/CLI, coordinación entre procesos y recuperación. No afirmar cobertura global si solo observa un proceso. Un thread lock no basta para escrituras de varios procesos.
- El proveedor/modelo se captura por invocación. Si FallbackBackend cambia al respaldo permitido, actualizar esa ejecución. No usar un atributo global last_engine compartido entre llamadas concurrentes. Si aún no puede conocerse, null.
- Preservar eventos antiguos. Añadir clasificación a eventos nuevos; los antiguos de motor mock son simulación, los indeterminados unknown. Ofrecer `resumen_real` separado, con la misma estructura de `resumen()` pero solo ejecuciones reales confirmadas; mantener el resumen histórico existente por compatibilidad. DASHBOARD usa resumen_real para métricas operativas, y conserva acceso al historial etiquetado.
- No conversaciones, prompts, teléfonos, emails, secretos ni errores crudos del proveedor en este contrato. `reason` es legible y seguro; `error_code` es estable.

## Errores operativos

En rutas interactivas, usar HTTP 503 para motor no configurado/no disponible, 504 para timeout y 502 para respuesta inválida o vacía cuando la operación requiere contenido. Mantener `detail` legible compatible con los consumidores actuales; documentar cómo reconocer esos estados en el cliente. Un resultado vacío válido (por ejemplo, búsqueda sin coincidencias) sigue siendo éxito vacío.

Webhooks ya reconocidos y trabajos en background registran el fallo según su flujo; no fingir que pueden cambiar el HTTP ya enviado. No enviar un texto simulado de reemplazo. Mantener políticas existentes de reintentos y evitar duplicar efectos parciales.

## Handoff

CORE debe dejar un reporte con commit, contrato efectivamente implementado, ejemplos obtenidos con tests aislados, cobertura y comandos/resultados. Si necesita cambiar nombres o semántica, actualizar esta especificación y notificar la dependencia antes de que DASHBOARD conecte la vista. Hasta entonces DASHBOARD puede trabajar el diseño y fixtures de prueba, pero no declarar actividad real terminada.
