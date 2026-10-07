# Motor WhatsApp: silencio y contexto en el chat de Diego

Estado al 2026-10-06 (Chile): **sin fix confirmado en producción**. Este archivo es un handoff para el terminal de Motor WhatsApp; depositarlo no equivale a que el terminal lo haya leído.

## Caso real y evidencia

- WhatsApp Web recibió `Hola`, `Hola me llamo Diego`, una consulta de bordes de piscina y luego `Hola?`. El último entrante quedó registrado el 2026-10-05 22:25 UTC, pero una derivación persistente anterior bloqueó la respuesta automática.
- Se corrigió esa derivación en `main` y se limpió el estado del chat de prueba. Un reproceso controlado del `Hola?` el 2026-10-07 00:54 UTC generó un borrador que decía `Ya revisé tu consulta` y volvía a pedir modelo y medidas ya entregados. El puente respondió `Puente WhatsApp Web sin conexión` durante un reinicio. El CRM registró `auto_reply_failed` y la bandeja no mostró salida posterior.
- El puente y el backend se recuperaron. No hubo un nuevo mensaje entrante de Diego desde ese reproceso; por ello el caso no está validado de punta a punta.
- No reenviar el borrador ni reintentar a ciegas el envío fallido: confirmar antes en el chat real si salió, ya que un fallo de transporte puede dejar resultado incierto.

## Trabajo en curso que conviene integrar

- `motor-whatsapp` seguía en `64e5048`, limpio, sin este arreglo. Hay un Codex activo en `/home/diego/zero-motor-whatsapp`; no se editó ese worktree.
- `/tmp/zero-motor-live` (`integrate/live-whatsapp`) tiene cambios **sin commit** en `zero/orchestrator.py`, `tests/test_whatsapp_handoff.py`, `zero/whatsapp_context.py` y `tests/test_whatsapp_context.py`. Recuperan hechos antiguos y secciones relevantes de conocimiento, y bloquean afirmaciones de revisión de cotización. Sus 15 pruebas dirigidas pasaron el 2026-10-06. No editar ni comitear esos archivos desde otro terminal sin coordinar con su autor.
- Hueco comprobado: `_unverified_quote_review_claim('¡Hola Diego! Ya revisé tu consulta. ¿Cuál modelo y medidas necesitas?')` devuelve `False`, mientras que devuelve `True` para `Ya revisé tu cotización; está aprobada.`. Incluir `consulta` u otra formulación equivalente en el control, sin bloquear frases inocuas del cliente, y agregar un test con el borrador real.

## Condición de cierre

1. En conversación larga, conservar hechos aportados por el cliente (modelo, medidas, ubicación) y no volver a pedirlos si están disponibles. Validar con una secuencia realista, no solo con mensajes sintéticos aislados.
2. Un saludo posterior al handoff debe poder recibir respuesta segura. Una respuesta repetida o una afirmación no comprobada debe pasar a revisión con un aviso adecuado, sin dejar silencio ni marcar el chat como bloqueado para siempre.
3. Impedir que el agente afirme que revisó, confirmó o aprobó una consulta/cotización sin una revisión comprobada. Usar el borrador real como regresión.
4. Verificar el resultado del envío en el puente y en la bandeja; manejar el estado incierto y no duplicar mensajes. Probar la secuencia en entorno controlado antes de activar respuesta automática en producción.
5. Publicar commit y resultado de pruebas en el worktree responsable; luego integrar preservando cambios de `main`. Hay conflictos conocidos en `api.py`, `zero/orchestrator.py`, `zero/channels.py`, CRM y otras áreas. No fusionar eligiendo una rama completa.

Referencia de estado más amplio: `/home/diego/zeroai/docs/integracion-2026-10-06.md`.
