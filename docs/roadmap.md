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
