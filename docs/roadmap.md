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
   Quedan 2 puntos que son acción manual de Diego (anotados, no bloquean nada
   de código): password real en vez de la de prueba, vendedores con números
   reales de WhatsApp Business (en curso — bloqueado hoy por la verificación
   de cuenta personal de Meta, ver docs/GO-LIVE.md §(c)). Prueba en móvil
   **descartada a propósito** (2026-07-04): el dashboard es propietario, solo
   la agencia lo opera, y siempre desde computador — no aporta nada probarlo
   en celular.
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
   **Cuantificado en vivo (2026-07-04)** con el pipeline real completo (Ollama
   qwen2.5:7b + `--discover web`) contra "pooledge" (venta de bordes de piscina
   y pastelones — ex-empresa de Diego, la reabre), buscando "empresas
   constructoras de piscinas en Chile": encontró **8/8 empresas reales y
   legítimas** (Splash Piscinas, Aguamundo, MASPISCINAS, chilepiscinas.cl, …,
   con email/teléfono real), pero **0/8 llegaron al mínimo de calificación
   (70)** — mejor score 65 — de forma consistente por la misma causa:
   PROSPECTOR no logra verificar un decisor real en sitios de PyMEs chicas
   (`role` queda en `"por verificar"`), y QUALIFIER, bien calibrado, penaliza
   fuerte esa falta de señal. No es un bug — es el límite real y ya conocido
   del scraping sin key, ahora con un número concreto detrás.
   **Decisión de Diego (2026-07-04):** el modelo de negocio es vender el mismo
   servicio a empresas chicas, medianas y grandes, a distinto precio y con
   distinto volumen/calidad de entrega según el plan — "a nosotros nos sirven
   todos los negocios". Por eso el piso de calificación pasa a ser **por
   tier**, no un número único: `zero/config.py::MIN_ICP_SCORE_BY_TIER` —
   STARTER 50 (plan de entrada, prioriza volumen, sirve a pymes chicas sin
   decisor verificable), GROWTH 60, SCALE 70, ENTERPRISE 80 (el que más paga
   exige más precisión). `MIN_ICP_SCORE` (60) queda como default/fallback para
   tiers sin entrada propia. `validate_lead`/`_validate_and_record` reciben
   `tier` y usan `config.min_icp_score(tier)`. 6 tests nuevos (piso escala con
   el tier, orden STARTER<GROWTH<SCALE<ENTERPRISE, fallback sin tier). 334/334
   en verde. Fuera de alcance por ahora seguir puliendo el scraping en sí (ver
   [[zero-scope-discipline]]) — esto es política, no mecanismo.
3. **Outreach de calidad real** — ✅ evaluado en vivo (2026-07-04) con el modelo
   real (Ollama qwen2.5:7b) contra el lead real de mejor score de la prueba de
   arriba (Splash Piscinas). El mensaje en sí fue sólido (menciona bien
   PoolEdge, el rubro del lead, tono profesional, CTA claro), pero encontró 2
   bugs reales de calidad, ambos arreglados:
   - **Saludo roto**: sin rol/nombre verificado, el modelo saludaba con el
     **email crudo como si fuera un nombre** ("Hola ventas@splash.cl,") — se ve
     robótico y le resta credibilidad al primer contacto. Arreglado con una
     instrucción explícita en `prompts/outreach.md` (saludar a la empresa, nunca
     citar el email/teléfono como nombre).
   - **Rol placeholder citado como real**: incluso en modo mock, un lead con
     `role="por verificar"` (el placeholder honesto de PROSPECTOR cuando no
     hay decisor verificado) generaba mensajes tipo *"vi que lideras como por
     verificar en Splash Piscinas"*. Nueva constante compartida
     `contracts.ROLE_UNVERIFIED`; `outreach.py` y `prospector.py` la tratan
     igual que un rol vacío/desconocido. Test de regresión agregado.
   - **Firma inventada** (encontrada corriendo `main.py` real, tier STARTER, tras
     arreglar los dos bugs de arriba): sin nadie con quién firmar, el modelo
     real firmó literalmente **"Me llamo OUTREACH... Atentamente, OUTREACH"** —
     usó el nombre interno del sub-agente como si fuera una persona, delatando
     el mecanismo a un lead real. Causa: `run_pipeline` nunca le pasaba a
     OUTREACH el vendedor asignado al cliente (Fernanda/Stéfano), a diferencia
     de `converse_result` (CONCIERGE), que sí lo hacía. Arreglado: mismo patrón
     `{name, tone}` de `vendor_for(client_id)` ahora viaja en `data.vendor` para
     OUTREACH también; `prompts/outreach.md` instruye firmar con ese nombre si
     viene, nunca inventar uno, y **nunca usar "OUTREACH" ni ningún nombre de
     agente/rol interno como firma**. Modo mock actualizado para el mismo
     contrato (firma con `data.vendor.name` si viene, sin firma de persona si
     no). 3 tests nuevos (firma con vendor, nunca firma con el nombre del
     agente, integración completa en `run_pipeline`).
   **Bug de mecanismo encontrado y arreglado en el camino**: QUALIFIER con
   backend real (probado con qwen2.5:7b, aplica a cualquier modelo real) a
   veces omitía `channel`/`email`/`phone`/`role` al reescribir el JSON —
   rechazaba leads perfectamente completos por una falla de fidelidad del
   modelo, no por datos faltantes. `_merge_qualifier_scores` en
   `orchestrator.py` restaura todo excepto `score`/`icp_reasons` desde el lead
   original. 337/337 en verde.

Canales reales:
4. **Que al menos un canal ENVÍE de verdad** (email = el más viable) — ✅ **capa de envío
   lista, mock-first**. `zero/channels.py`: abstracción `Outbox` + `MockSender` /
   `EmailSender` (SMTP stdlib) / `WhatsAppSender` (Meta Cloud API). El orquestador envía
   el primer toque (`run_pipeline`) y los follow-ups (`run_followups`); cada envío queda
   en el historial del CRM. **Mock por defecto incluso con credenciales** — se envía de
   verdad solo con `OUTBOX_LIVE=1` (interruptor "Activar envío real" en Config). Cards de
   Email y WhatsApp en el dashboard. 3 tests nuevos.
   **Probado en vivo (2026-07-06)**: SMTP real (Gmail) ya configurado y
   `outbox_live: true` en producción. Confirmado punta a punta con 2 correos
   reales — uno vía `/api/test-email` (send directo) y otro vía el `Outbox`
   real (con reintentos) — ambos llegaron. Falta: el **agente conversacional de
   WhatsApp** (entrante de dos vías, que se apoya en el loop de respuestas).

   **Hallazgo de robustez (no es bug de código, es riesgo operativo):** el
   remitente es una cuenta de **Gmail personal** (`fudyfoodscl@gmail.com`), no
   un dominio propio de negocio. Tres riesgos reales para cuando haya volumen:
   límite de ~500 correos/día en Gmail gratis; mala entregabilidad (sin
   SPF/DKIM de un dominio propio, más probable que cualquier filtro antispam
   lo mande a spam); y riesgo a la cuenta personal si Gmail detecta un patrón
   de envío masivo/frío. La solución completa (dominio propio + proveedor
   dedicado tipo SES/Mailgun) es gasto — ya está en
   "⏸️ Pendientes de PAGO" más abajo, no se toca ahora.

   **Arreglado, gratis, en el camino**: el "From" del email salía con la
   dirección pelada de la cuenta SMTP, sin decir de parte de quién escribía —
   mismo problema de fondo que las firmas rotas de OUTREACH (ver Discovery/
   Outreach arriba). `EmailSender` ahora arma el header `From` con el nombre
   del vendedor asignado (ej. "Stéfano <cuenta@gmail.com>") cuando
   `_deliver` (usado por `run_pipeline`/`run_followups`) se lo pasa — mismo
   patrón que ya existía para WhatsApp/CONCIERGE
   (`vendor_for(client_id)`). `_build_message` se separó a `@staticmethod`
   para poder probarlo sin tocar la red. 3 tests nuevos. 340/340 en verde.

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
