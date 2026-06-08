# Roadmap / estado de los planes — ZeroAI

Fuente de verdad de en qué vamos. Recuperado de los transcripts de sesión y
verificado contra el código (2026-06-07). Si trabajamos un plan, **se anota aquí
en el momento** — así una compresión de contexto no nos lo borra.

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
2. **Discovery real y confiable** — 🟡 parcial: `DuckDuckGoSource` sin key; falta
   proveedor con key para cobertura.
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
6. **Login / multi-cliente** — ❌ pendiente (no hay auth en `api.py`).
7. **Loop completo** (respuesta → acción) — ✅ **agente conversacional listo, mock-first**.
   `register_reply` cierra la secuencia y mueve a `replied` (forward-only). Agente
   **CONCIERGE** (`zero/agents/concierge.py` + `prompts/concierge.md`): responde preguntas
   sobre el negocio del cliente usando su ICP, propone reunión, y **se transparenta como
   IA** si le preguntan. `Zero.converse` (redacta) y `Zero.handle_inbound` (mapea entrante
   → cierra loop → responde → envía). WhatsApp entrante: `zero/whatsapp_inbound.py` (parser)
   + webhook `GET/POST /api/webhooks/whatsapp` (verificación Meta + recepción). Probador en
   vivo: `POST /api/whatsapp/simulate` y card **"Probar el agente de respuestas"** en Config
   (mock por intención; con Anthropic key responde el modelo real). 4 tests nuevos.
   Falta para real: número de WhatsApp Business + URL pública (deploy/ngrok) para el webhook.

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
2. **Auth (un login de agencia)** — ❌ pendiente: gate simple (un password) sobre API+dashboard.
3. **Estado a la nube** — ❌ pendiente: ICP/secuencias salen de `state.json` a la DB
   (hoy siguen locales → no sobreviven multi-instancia).
4. **Paginación de un cliente enorme** — ⏳ siguiente afinamiento: empujar `limit/offset`
   al query de Supabase y paginar la tabla de Leads en el frontend.

## Lo que sigue (recomendación)
La verdadera prueba pendiente es la **calidad real** (#2/#3): correr con tu key o el
modelo local y evaluar si los leads/mensajes son buenos. Después: **canal email que
envíe** (#4). Auth/multi-tenant (#6) y el loop (#7) cuando el motor esté impecable.
