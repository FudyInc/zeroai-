# Roadmap / estado de los planes — ZeroAI

Fuente de verdad de en qué vamos. Recuperado de los transcripts de sesión y
verificado contra el código (2026-06-07). Si trabajamos un plan, **se anota aquí
en el momento** — así una compresión de contexto no nos lo borra.

---

## 🔴 Estado de infraestructura (2026-07-03) — dónde vive cada cosa

- **Rama de producción: `main`.** `chore/terminales-por-rol` (la que de verdad corría
  en Ubuntu) se fusionó acá vía fast-forward. Las ramas de trabajo (`core`, `dashboard`,
  `prompts`, etc.) se fusionan y se **borran** — no se acumulan durante semanas. Ver
  [[zero-branch-sprawl-lesson]]: hoy mismo aparecieron un proyecto de Vercel duplicado y
  un `GET /api/vendors` construido dos veces por tener demasiadas ramas divergiendo.
- Nota de modelo de negocio (ver sección de escalabilidad más abajo): el dashboard es
  **propietario** — solo ZeroAI lo opera, los clientes nunca entran ahí.
- **Frontend:** un solo proyecto en Vercel — **`zeroai`** (`zeroai-six.vercel.app`),
  conectado por Git a `main` (auto-deploy en cada push). Nunca correr `vercel`/
  `vercel --prod` manual desde ningún checkout — eso fue lo que generó los duplicados
  `zeroai-x16d`, `zeroai-dashboard` y `project-qfwaa` (ya borrados/por borrar).
- **Backend:** corre en el PC Ubuntu como dos servicios `systemd`
  (`zero-backend.service` + `zero-tunnel.service`), arrancan solos al prender el PC y se
  reinician solos si se caen. Expuesto vía túnel fijo de ngrok (dominio "dev domain,
  yours forever" — gratis, no cambia entre reinicios). `VITE_API_URL` en Vercel apunta a
  esa URL.
- **Antes de construir un endpoint nuevo:** revisa el `api.py` real (rama `main`)
  primero con `grep` — no asumas el contrato de un prompt sin verificar contra el código.
- Guardia automática: `tests/test_core.py::ApiRoutesTest` falla si `api.py` registra la
  misma ruta dos veces (justo el problema de hoy).

## 🎯 Plan de fiabilidad — "listo para el mercado" (2026-07-04) · 🟡 EN CURSO
Criterio: no lanzar hasta que esto esté resuelto **de verdad**, no "se siente listo".
Orden acordado con Diego — no reordenar sin avisar:

1. **Plantillas de WhatsApp Business (Meta)** — ✅ CÓDIGO LISTO (2026-07-04), falta
   el paso manual de Diego. Confirmado en código: `WhatsAppSender.send()`
   (`zero/channels.py`) siempre mandaba `type: "text"`. Meta EXIGE una plantilla
   pre-aprobada para el primer contacto a un lead que nunca escribió, o cualquier
   mensaje fuera de la ventana de 24h desde su último mensaje — un `type: "text"` en
   frío es rechazado por la Graph API real. Afecta: `_send_first_touch` y
   `run_followups` (orchestrator.py). NO afecta las respuestas dentro de
   `handle_inbound` (son réplica a algo que el lead ya escribió, dentro de la ventana
   de 24h — texto libre está bien ahí).
   **Hecho:** `WHATSAPP_TEMPLATE` en `zero/config.py`; `WhatsAppSender` soporta
   `type: "template"` (`_template_body`) y sigue soportando texto libre (`_text_body`)
   para las respuestas; orchestrator marca `whatsapp_send_type: "template"` solo en
   los dos puntos de contacto en frío; sin plantilla configurada, degrada a error
   visible en el CRM (nunca manda texto libre que Meta rechazaría en silencio). 5
   tests nuevos, 297/297 en verde. Instrucciones para Diego en `docs/GO-LIVE.md` §(c).
   **Falta (fuera de código, manual):** Diego crea la plantilla en Meta Business
   Manager, espera aprobación, y la anota en `WHATSAPP_TEMPLATE`.
2. **Fragilidad del hosting** — decidido (2026-07-04), 🟡 EN CURSO. El backend depende
   de un PC Ubuntu + túnel gratis de ngrok; si el PC se apaga/reinicia sin querer,
   todo el producto cae para todos los clientes. Decisión de Diego: **a propósito
   se queda así mientras esté en fase de desarrollo/prueba, sin clientes reales.**
   La migración de verdad se hace recién cuando haya que salir al mercado — no antes.
   - **Migración futura (cuando haya clientes reales):** mover el backend a un VPS
     barato (Hetzner/DigitalOcean, ~$4-6 USD/mes) — mismo código, mismos `systemd`,
     solo que en una máquina con energía/internet garantizados. Render queda
     descartado (ver [[zero-hosting-decision]] — fricción con las keys). Vercel NO
     sirve para el backend (es serverless, sin proceso persistente, y el disco es
     efímero — rompería el fallback local a `state.json`/`crm.json`); Vercel se queda
     con su rol actual, solo el frontend. Supabase (ya construido: `SupabaseCRM`/
     `SupabaseMemory`) sí encaja para la capa de datos cuando llegue el momento —
     ojo: el plan gratis pausa el proyecto tras ~1 semana sin actividad.
   - **Ahora, gratis:** monitoreo con alerta — UptimeRobot (gratis) pegándole a
     `/api/health` cada 5 min, con push a iPhone vía su app oficial. Esto no evita
     la caída, pero avisa en minutos en vez de que lo note un cliente.
   - **Anotado para más adelante, no ahora:** activar en el BIOS del PC Ubuntu
     "Restore on AC Power Loss" (auto-enciende solo si vuelve la luz después de un
     corte) — complementa lo que ya hace `systemd` (reinicia el proceso si se cae).
3. **Test end-to-end HTTP** (`tests/test_api_http.py`, requiere `fastapi`+`httpx`,
   separado del núcleo stdlib-only) — prueba la cadena completa petición → FastAPI →
   auth → respuesta, no solo la lógica interna. Hoy los 297 tests de `test_core.py`
   nunca tocan HTTP real.
4. Resto del checklist de fiabilidad (password real en vez de la de prueba, backup de
   `crm.json`/`state.json`, verificación de firma del webhook de Meta, reintentos de
   envío fallido, vendedores con números reales de WhatsApp Business, prueba de
   CONCIERGE con casos difíciles, prueba en móvil, expiración de sesión probada).

---

## Plan A — Pulido del dashboard (4 puntos) · ✅ COMPLETO
1. **Pulido en TODAS las páginas** (animaciones, skeletons, estados carga/error/vacío) — ✅
   commiteado (rework en las 9 vistas del frontend).
2. **Drag & drop en el Pipeline** — ✅ presente en `frontend/src/pages/Pipeline.jsx`.
3. **Formulario de ICP en "Buscar leads"** — ✅ en `frontend/src/App.jsx`; el backend
   `/api/pipeline` acepta `icp`.
4. **Búsqueda + filtros en Leads** — ✅ en `frontend/src/pages/Leads.jsx`.

## Integraciones + dashboard de configuración · ✅ COMPLETO
Panel `IntegrationCard` en `frontend/src/pages/Config.jsx` + endpoint `/api/config`
(`api.py`), guarda keys en `.env` local, nunca devuelve el secreto. Integraciones:
- **Anthropic** (modo `--live`) · **ElevenLabs** (voz) · **Vapi** (llamadas) ·
  **Supabase** (CRM en la nube).

## Plan B — Motor real / "listo para el día 1" (checklist de 7) · 🟡 EN CURSO
Motor real (que de verdad SOLUCIONE):
1. **Calificación/score REAL** contra el ICP del cliente — ✅ commit `motor-real`
   (prompts reales + `zero/icp.py` + camino real con parseo a prueba de balas).
2. **Discovery real y confiable** — 🟡 parcial: `DuckDuckGoSource` sin key mejorada (✅ 2026-06-11: minería de directorios, fallback a /contacto, filtrado de señales de email/teléfono); falta
   proveedor con key para cobertura mayor. Tests nuevos en `tests/test_discovery.py`; 6/6 PyMEs reales en vivo.
3. **Outreach de calidad real** — ✅ redacta por canal; ⚠️ calidad sin evaluar en vivo
   (requiere correr con key/modelo y juzgar a ojo crítico).

Canales reales:
4. **Que al menos un canal ENVÍE de verdad** (email = el más viable) — ✅ **capa de envío
   lista, mock-first**. `zero/channels.py`: abstracción `Outbox` + `MockSender` /
   `EmailSender` (SMTP stdlib) / `WhatsAppSender` (Meta Cloud API). El orquestador envía
   el primer toque (`run_pipeline`) y los follow-ups (`run_followups`); cada envío queda
   en el historial del CRM. **Mock por defecto incluso con credenciales** — se envía de
   verdad solo con `OUTBOX_LIVE=1` (interruptor "Activar envío real" en Config). Cards de
   Email y WhatsApp en el dashboard. 3 tests nuevos. Falta: probar un envío real end-to-end
   con credenciales, y el **agente conversacional de WhatsApp** (entrante de dos vías, que
   se apoya en el loop de respuestas).

Robustez:
5. **Sin crasheos, maneja datos malos** — ✅ parseo tolerante + 40/40 tests.

Operación:
6. **Login / multi-cliente** — ✅ (2026-06-11): gate de un password (`zero/auth.py`,
   tokens firmados por el propio password) + middleware en `api.py`; sin password
   configurado queda abierto (dev).
7. **Loop completo** (respuesta → acción) — ✅ **agente conversacional listo, mock-first**.
   `register_reply` cierra la secuencia y mueve a `replied` (forward-only). Agente
   **CONCIERGE** (`zero/agents/concierge.py` + `prompts/concierge.md`): responde preguntas
   sobre el negocio del cliente usando su ICP, propone reunión, y **se transparenta como
   IA** si le preguntan. `Zero.converse` (redacta) y `Zero.handle_inbound` (mapea entrante
   → cierra loop → responde → envía). WhatsApp entrante: `zero/whatsapp_inbound.py` (parser)
   + webhook `GET/POST /api/webhooks/whatsapp` (verificación Meta + recepción). Probador en
   vivo: `POST /api/whatsapp/simulate` y card **"Probar el agente de respuestas"** en Config
   (mock por intención; con Anthropic key responde el modelo real). **Detección automática
   de respuestas** ✅ (2026-06-11): `zero/inbox.py` (abstracción `Inbox` + `MockInbox` /
   `FileInbox` drop-box / `ImapInbox` stdlib con `INBOX_LIVE=1`). El orquestador corre
   `check_replies()` antes de los follow-ups (`run_followups`): quien ya respondió no
   recibe más toques. Acción `--action replies` y flag `--inbox` en el CLI. **Intents
   ampliados + ofertas pendientes** ✅ (2026-06-11): CONCIERGE maneja objeciones,
   desconfianza y "mándame info" (intents `objection/trust/info`), y ZERO **cumple lo
   que el agente promete**: la oferta queda en `memory.pending_offers` y la aceptación
   del lead ("sí", "por acá", un correo) dispara el envío del resumen real
   (`build_info_summary`, fiel al ICP) por el canal elegido, con evento `info_sent`
   en el CRM. Falta para real: número de WhatsApp Business + URL pública
   (deploy/ngrok) para el webhook.

## Formulario de ICP (mejorado, 2026-06-07)
Antes capturaba 4 de 8 campos y era write-only. Ahora: los **8 campos** (`industry,
sells, buyer_roles, company_size, regions, must_have, exclude, context`) en el modal
"Buscar leads"; endpoint `GET /api/icp?client=` y **precarga del ICP guardado** del
cliente al abrir el panel (+ link "↻ cargar guardado"). El ICP se persiste por cliente
en `state.json` (local) — pasarlo a la nube es parte de multi-tenant (#6).

---

## Escalabilidad + multi-tenant (track combinado, 2026-06-07) · 🟡 EN CURSO
Modelo decidido: **agencia, un solo dueño** (tú entras; los "clientes" son cuentas
internas aisladas en datos, no entran ellos).
1. **Lectura escalable** — ✅ `SupabaseCRM` ya no hace `SELECT *`: carga **por cliente**
   (`_ensure`), `client_ids()` por proyección, `find_by_contact` server-side; `crm.list`
   con `limit/offset`. `/clients` y `/kpis` scoped. 53/53 tests.
2. **Auth (un login de agencia)** — ✅ (2026-06-11): ver Plan B #6.
3. **Estado a la nube** — ✅: `SupabaseMemory` (`zero/memory_supabase.py`) guarda el
   snapshot completo (ICP, secuencias, ofertas pendientes) en `app_state`;
   `make_memory` la usa si hay credenciales y cae a `state.json` local si no.
4. **Paginación fina** — ✅ (2026-06-08): `CRM.query(client, stages, limit, offset)` empuja
   filtro+orden+slice a PostgREST; `/api/leads?group&limit&offset` → `{leads,total}`;
   frontend con `useInfiniteQuery` + "Cargar más". Orden con desempate único (lead_key)
   para páginas estables.
5. **ICP en la nube** — ✅ verificado (2026-06-08): tabla `app_state` creada, `SupabaseMemory`
   activo, roundtrip de ICP confirmado.

## Meta Ads / Campañas (2026-06-08) · 🟡 mock-first
`zero/metaads.py` (MockMetaAds + MetaAds real vía Graph + `make_metaads`), `/api/campaigns`,
pestaña **Campañas** (KPIs gasto/leads/CPL + tabla + filtro), card en Config. Mock por
defecto; real con `META_ADS_TOKEN` + `META_AD_ACCOUNT_ID`. **Atar leads de ads → CRM: ✅**
(`Zero.import_ad_leads`, endpoint `POST /api/campaigns/sync-leads`, botón en la pestaña
Campañas; entra como `qualified` + tag "Meta Ads", mock por defecto). Falta: insights
reales (gasto/leads del endpoint de Meta).

## ⏸️ Pendientes de PAGO (hacer cuando Diego pueda pagar — ver [[zero-cost-policy]])
Cero gasto por ahora. Estos están construidos **mock-first / con seam listo**; solo falta
enchufar la cuenta/key de pago para que funcionen de verdad:
- **Motor real con Anthropic** — calidad real de scoring/mensajes/agentes. (Alternativa
  gratis: modelo local Ollama). 
- **Meta Ads real**: insights (gasto/leads/CPL reales) y gestión que **aplica** el plan
  de Claude (pausar/presupuesto). (La cuenta de Meta nueva además tiene cooldown inicial.)
- **Discovery con proveedor con key** — cobertura real de prospección.
- **ElevenLabs** (clonación de voz) y **Vapi** (llamadas) — el agente de voz real.
- **Envío email/WhatsApp a volumen** (deliverability / proveedor dedicado tipo SES).

## Lo que sigue (recomendación)
Mientras no haya pagos: perfeccionar lo gratis. En curso: probar email real (SMTP
ya configurado) y pulir el dashboard.
