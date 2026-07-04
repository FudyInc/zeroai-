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
2. **Fragilidad del hosting** — ⏸️ PAUSADO A PROPÓSITO (2026-07-04). El backend
   depende de un PC Ubuntu + túnel gratis de ngrok; si el PC se apaga/reinicia sin
   querer, todo el producto cae. Decisión de Diego: **mientras esté en fase de
   desarrollo/prueba, sin clientes reales, todo esto queda pausado** — ni VPS, ni
   Supabase, ni siquiera UptimeRobot todavía. El foco ahora es el producto en sí
   (punto 3 en adelante). Retomar recién cuando haya que salir al mercado:
   - VPS barato (Hetzner/DigitalOcean, ~$4-6 USD/mes) — mismo código, mismos
     `systemd`, máquina con energía/internet garantizados. Render descartado (ver
     [[zero-hosting-decision]] — fricción con las keys). Vercel NO sirve para el
     backend (serverless, sin proceso persistente, disco efímero — rompería el
     fallback a `state.json`/`crm.json`); se queda con su rol actual, solo frontend.
     Supabase (ya construido: `SupabaseCRM`/`SupabaseMemory`) sí encaja para la capa
     de datos — ojo: el plan gratis pausa el proyecto tras ~1 semana sin actividad.
   - Monitoreo con alerta (UptimeRobot gratis + push a iPhone) — pasos ya definidos,
     ver commit anterior de esta sección; solo falta ejecutarlos cuando toque.
   - BIOS del PC Ubuntu: "Restore on AC Power Loss" (auto-enciende al volver la luz).
3. **Test end-to-end HTTP** — ✅ HECHO (2026-07-04). `tests/test_api_http.py`: levanta
   `api.py` real como subproceso (`uvicorn`) y le pega con HTTP real (stdlib puro —
   `subprocess`+`urllib`, SIN `httpx`/`TestClient`, cero dependencias nuevas más allá
   de lo que `api.py` ya necesita). Corre solo, y se salta a sí mismo (skip limpio)
   si `uvicorn` no está instalado — separado de `test_core.py`, que sigue siendo
   100% stdlib.
   **Encontró un bug real al primer uso:** `GET /api/clients` tiraba `500` crudo
   cuando `SUPABASE_URL`/`SUPABASE_KEY` estaban configuradas pero Supabase no
   respondía (`SupabaseError` sin capturar). Causa: `make_crm()`/`SupabaseCRM` cargan
   perezoso a propósito (no hacen `SELECT *` — ver escalabilidad más abajo), así que
   el fallo real aparece recién al primer query, no al construir el objeto —
   `make_memory()` sí tenía ese fallback (con try/except en la construcción),
   `make_crm()` no tenía ninguno.
   **Arreglado:** manejador de excepción global en `api.py`
   (`@app.exception_handler(SupabaseError)`) que convierte CUALQUIER `SupabaseError`
   sin capturar, en cualquier endpoint, a un `503` con mensaje claro — en vez de un
   `500` genérico. Cubre tanto `crm_supabase.py` como `memory_supabase.py` (comparten
   la misma excepción). Test de regresión agregado. 302/302 tests en verde.
4. Checklist de fiabilidad — ✅ CÓDIGO LISTO (2026-07-04). Los 4 ítems de código
   (firma del webhook, reintentos de envío, backup de crm.json/state.json,
   casos difíciles de CONCIERGE, expiración de sesión) están hechos y probados.
   Quedan 3 puntos que son acción manual de Diego (anotados, no bloquean nada
   de código): password real en vez de la de prueba, vendedores con números
   reales de WhatsApp Business, prueba en móvil.
   - **Verificación de firma del webhook de Meta** — ✅ HECHO. `POST
     /api/webhooks/whatsapp` no verificaba nada — cualquiera con la URL podía
     mandar mensajes falsos haciéndose pasar por un lead (y hasta gatillar una
     respuesta real con `OUTBOX_LIVE=1`). Agregado `verify_meta_signature` en
     `zero/whatsapp_inbound.py` (HMAC-SHA256 contra `WHATSAPP_APP_SECRET`,
     comparación con `hmac.compare_digest`); sin el secreto configurado, o con una
     firma que no cuadra, el webhook rechaza con `403` — no hay forma de recibir
     mensajes reales sin el secreto. `WHATSAPP_APP_SECRET` sumado a
     `POST /api/config` y a `docs/GO-LIVE.md`. 4 tests nuevos (función aislada +
     HTTP real). 306/306 tests en verde.
   - **Reintentos de envío fallido** — ✅ HECHO (2026-07-04). `Outbox.send()` no
     reintentaba nada: un corte de red momentáneo (timeout SMTP, blip de la Graph
     API) degradaba el envío a `"error"` para siempre en el primer intento fallido,
     sin darle ninguna chance a un problema transitorio. Agregado
     `OUTBOX_RETRY_ATTEMPTS`/`OUTBOX_RETRY_DELAY_SECONDS` en `zero/config.py`
     (3 intentos, 1s de espera entre cada uno, configurable por instancia);
     `Outbox.send()` reintenta con esos parámetros y solo degrada a `"error"`
     cuando se agotan todos los intentos. Nunca cambia el contrato (`Outbox`
     sigue sin lanzar excepciones hacia afuera). 2 tests nuevos (reintenta y
     luego funciona / se agotan los reintentos y degrada a error), más un ajuste
     a un test viejo que sin querer empezó a dormir de verdad con la nueva
     lógica (`retry_delay=0` en los tests, para no pagar el segundo real en cada
     corrida de la suite). 308/308 tests en verde, ~1s (tiempo normal).
   - **Backup de `crm.json`/`state.json`** — ✅ HECHO (2026-07-04). `CRM.save()` y
     `SessionMemory.save()` escribían directo sobre el archivo — una escritura
     cortada a mitad de camino (crash, corte de luz, disco lleno) podía dejarlo
     corrupto, y sin ningún respaldo eso significaba perder todos los leads o
     todo el estado de sesión de un saque (`_load()` ya avisaba con
     `RuntimeError` en vez de arrancar vacío, pero no había forma de recuperarse).
     Nuevo módulo compartido `zero/persistence.py` (`save_json`/`load_json`):
     escritura atómica (temporal + `os.replace`, nunca deja un archivo a medio
     escribir) que además rota la versión anterior a `<path>.bak` antes de
     reemplazar; al leer, si el archivo principal está corrupto intenta el
     `.bak` automáticamente (con aviso claro por stderr) antes de recién ahí
     rendirse. `crm.py`/`memory.py` migrados a este módulo, sin cambiar su
     comportamiento externo. `.gitignore` cubre `*.json.bak`/`*.json.tmp`. 6
     tests nuevos (rotación, recuperación desde backup, ambos corruptos → error
     claro, extremo a extremo con `CRM` real).
   - **Prueba de CONCIERGE con casos difíciles** — ✅ HECHO (2026-07-04). Un
     lead real puede escribir cualquier cosa — vacío, groserías, spam, inglés,
     un mensaje gigante — y el agente nunca puede romperse por eso. Probado a
     mano primero (mensaje vacío/blanco, solo emojis, 20.000 caracteres, `None`,
     insultos con "estafa") y ninguno crashea; los 7 tests nuevos
     (`ConciergeEdgeCasesTest`) lo dejan como regresión: mensaje vacío/blanco,
     `data` sin la clave `message`, groserías (nunca las repite en la
     respuesta), spam/sin sentido, "stop" en inglés (opt-out sin traducir
     nada — misma keyword), mensaje de ~25.000 caracteres (con límite de tiempo
     para descartar un ReDoS), y lead sin nombre (el saludo no debe romperse).
   - **Expiración de sesión probada** — ✅ HECHO (2026-07-04). `zero/auth.py` ya
     tenía tests unitarios de `valid_token()` (expira, password rotada, token
     alterado), pero eso nunca probó que el middleware real de `api.py`
     (`auth_guard`) de verdad lo aplique en cada request — la lógica podía
     estar perfecta y el middleware roto, y los tests seguirían en verde.
     Agregada `ApiAuthHttpTest` en `tests/test_api_http.py`: subproceso propio
     con `AUTH_PASSWORD` configurado (separado de `ApiHttpTest`, que corre a
     propósito sin password para probar los demás endpoints libremente),
     probando sobre HTTP real: sin token → 401, token basura → 401, password
     incorrecta en `/api/login` → 401, login con token válido → 200, **token
     vencido firmado con la password real del servidor → 401** (el caso central:
     firma válida pero expirado, para separar "token falso" de "token viejo"),
     y que `/api/health`/`/api/auth/status` nunca piden token. Se extrajo
     `_wait_until_up` como función compartida del archivo (la usaban ambas
     clases). 6 tests nuevos. 327/327 tests en verde (13 de ellos en
     `test_api_http.py`, subiendo el tiempo total a ~1.8s por los dos
     subprocesos de uvicorn — el resto de la suite sigue en ~1s).

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
