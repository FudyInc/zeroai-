# Pedido 2026-11-03 · Campañas: ruta de sugerencias + chequeo diario que no se pierda (CORE)

Origen: chequeo general pedido por Diego el 2026-11-03 («haz un checkeo de todo lo que está mal y todo lo que está bien y distribuye las tareas»), desde el terminal motor-whatsapp.

Qué se cerró del pedido anterior (2026-10-28-core-anuncios-pagados), verificado en origin/main:
- `GET /api/campaigns/ads` existe (`api.py:852`), con datos reales: 80 anuncios para losetaschile.
- MEDIABUYER `action="improve_ad"` existe (`zero/agents/mediabuyer.py:31`).
- El dashboard ya llama `suggestAd` → `/api/campaigns/ads/suggest` (`frontend/src/lib/api.js:81`).
- **Nadie expone esa ruta**: `git grep -n suggest origin/main -- api.py` no devuelve nada. Hoy el botón «Sugerir mejoras» da 404.

```
PASO 0: git fetch && git rebase origin/main (tu rama va 3 commits atrás). Revisa git status antes de editar.

[TARGET: ⚙️ CORE] — si tu sección no es CORE, detente y dilo.

TAREA 1 (primero) — GET /api/campaigns/ads/suggest?client=X&ad_id=Y
- Busca el anuncio con el mismo código que /api/campaigns/ads (mismo token del cliente pedido, nunca el de otro).
- Llama a MEDIABUYER con action="improve_ad" y ese item, por el mismo camino que usa api.py::_agent_op.
- Devuelve lo que entrega MEDIABUYER: {diagnostico, pocos_datos, sugerencias[{campo, actual, propuesta, por_que}], metricas_usadas}.
- Sin motor real → 503 con el motivo (principio 1 de CLAUDE.md). Nunca _mock_improve_ad fuera de la suite.
- ad_id que no está en la cuenta → 404 con motivo. Cliente sin Meta → 200/unavailable igual que /ads, o 409. Elige uno y documéntalo en el test.
- El operador no tiene acceso, igual que /ads.
- Tests: sin motor → 503; ad ajeno → 404; usa el token del cliente pedido; forma de respuesta.

TAREA 2 — texto e imagen del post promocionado
Tu propio hallazgo del 10-28: creative.title/body/image_url vienen en null y la miniatura es de 64×64. Lee el post por post_id (GET /{post_id}?fields=message,full_picture,permalink_url) con el token del cliente y rellena creative.body e image_url cuando falten. Solo lectura. Si Graph falla para un post, deja null; no rompas la lista.

TAREA 3 — el chequeo diario del agente de WhatsApp no corre desde el 2026-10-28
Evidencia: `journalctl --user -u zero-golden --since -8day | grep -E "Finished|Failed"`. Solo el 10-28 dice Finished. Los días 10-29, 10-30, 11-01, 11-02 y 11-03 dicen «Failed with result 'signal'».
Causa: WSL arranca, se apaga solo unos 19 s después (`journalctl --since "2026-11-03 12:41:20" --until "12:41:40" | grep "power off"`) y vuelve a arrancar. `Persistent=true` dispara la corrida perdida justo en ese arranque efímero, la matan y el timer la da por hecha hasta las 04:30 del día siguiente, cuando el PC está apagado.
Arreglo propuesto (decide tú el mecanismo y justifícalo): que la corrida que falta se recupere sola. Por ejemplo, que scripts/revisar-salud.py (corre cada 30 min) vea que la última corrida completa de probar-agente.py tiene más de 26 h y la lance, o avise. Mira el resultado, no la intención: «la última pasada completa», no «el timer se disparó».
Test: con un registro de última corrida viejo, la salud lo detecta.

ALCANCE: api.py (solo /api/campaigns*), zero/metaads.py, scripts/revisar-salud.py, ~/.config/systemd/user/zero-golden.* si hace falta (dilo en el reporte, eso no está versionado), tests/.
NO toques: frontend/, zero/agents/mediabuyer.py (si su firma no te sirve, repórtalo), zero/orchestrator.py, prompts/.

ACEPTACIÓN: la suite en verde (el único error tolerado es tests.test_visual_catalog). Para la tarea 1, una llamada real de solo lectura contra un anuncio de losetaschile, con la salida pegada y sin el token.

REPORTE: qué cambió, la salida de la llamada real, cómo verificaste la tarea 3 y los hallazgos fuera de CORE.
```

## TAREA 4 — Definición de lead (decidida por Diego el 2026-11-03)

Diego definió: **es lead todo cliente que llega por WhatsApp o que consulta al negocio que usa el dashboard**, es decir, toda conversación iniciada por un cliente. Hoy las campañas que llevan a WhatsApp muestran leads=0 y CPL=None.

```
- La regla va en zero/config.py (principio 2): por ejemplo, LEAD_DEFINITION con las acciones de Meta que cuentan
  (onsite_conversion.messaging_conversation_started_7d y sus equivalentes) y una nota que cite esta decisión.
- zero/metaads.py la aplica: leads = conversaciones iniciadas y CPL = gasto / leads; si leads=0, CPL=None (nunca un número inventado).
- Tests: anuncio con conversaciones iniciadas → leads y CPL correctos; sin conversaciones → CPL None; la regla se lee desde config.
- En el reporte: una llamada real de solo lectura que muestre leads y CPL de un anuncio de losetaschile.
```

ALCANCE extra para esta tarea: zero/config.py (solo la regla nueva).
