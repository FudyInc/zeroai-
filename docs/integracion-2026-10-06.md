# Handoff de integración — 2026-10-06

Estado comprobado desde `/home/diego/zero-core` el 2026-10-06 (Chile). Antes de
editar o fusionar, volver a consultar `git status` y el HEAD de cada rama: otros
terminales pueden avanzar mientras tanto.

## Trabajo guardado

| Rama | Commit | Contenido |
| --- | --- | --- |
| `main` | `1eba7db`, `674bd45`, `6842b63` | Estado activo de WhatsApp Web y dashboard; merge de remoto; sesiones y base local excluidas de Git. |
| `core` | `d9f1379`, `3e30419` | Consolidación de WhatsApp, conocimiento, memoria y revisión de casos. |
| `dashboard` | `f9231c7` | Aislamiento de vistas por cliente y credenciales de Meta. Suite completa: 972 pruebas OK; build OK. |
| `prompts` | `5d03a8c` | Nota de reconocimiento para dashboard, conservada como documento. |
| `motor-whatsapp` | `2b8cf5c`, `64e5048` | Contexto por empresa y merge previo de `main`. Hay un terminal de Codex activo en este workspace; no se editó. |
| `integrate/live-whatsapp` | `1366df1`, `df9a44a`, `6b36a88` | Integración preliminar de canales, bandeja Web y condiciones de despliegue. |

Las ramas estaban limpias tras esos commits, salvo los archivos locales de sesión
y eventos de producción, que ahora están en `.gitignore`. Este handoff no implica
que las ramas ya estén fusionadas entre sí ni que todo cambio esté desplegado.

## WhatsApp de producción: incidente aún abierto

- El mensaje entrante de prueba `Hola?` del 2026-10-05 22:25 UTC se registró,
  pero una derivación persistente anterior impidió la respuesta automática.
- El código activo de `main` ya limita una revisión por respuesta repetida a esa
  consulta, y las pruebas específicas de handoff pasaron (10 casos). Se quitó
  la derivación antigua del chat de prueba.
- Un reproceso controlado del último mensaje el 2026-10-07 00:54 UTC redactó una
  respuesta, pero el puente informó `sin conexión` durante un reinicio del
  backend. El CRM registra `auto_reply_failed` y la bandeja no muestra salida
  posterior a ese mensaje. **No reintentar ese envío sin revisar primero el chat**:
  un timeout de WhatsApp puede tener resultado incierto.
- El borrador de ese reproceso afirmaba haber revisado la cotización y volvió a
  pedir datos que el contacto había entregado antes. No enviarlo tal cual. El
  motor necesita conservar hechos relevantes de conversaciones largas y probar
  el caso con el banco de conversaciones antes de reactivar respuestas de venta.

## Riesgo de merge

La simulación `git merge-tree --write-tree` detectó conflictos:

- `main` + `motor-whatsapp`: `api.py`, `PricingCard.jsx`, `zero/channels.py`,
  `zero/crm.py`, `zero/crm_supabase.py`, `zero/orchestrator.py`.
- `main` + `integrate/live-whatsapp`: también confligen configuración, Meta Ads,
  pruebas HTTP, aislamiento por cliente y `zero/whatsapp_web.py`.
- `main` + `dashboard`: confligen rutas API, bandeja WhatsApp, vistas del dashboard
  y CRM.

Resolver cada integración en un worktree aislado, revisando las diferencias de
ambos lados por función y ejecutando pruebas y build antes de mover `main` o
`motor-whatsapp`. No aplicar una estrategia de preferir una rama completa:
perdería arreglos de producción o el aislamiento por cliente.
