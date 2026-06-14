# Prompts de Trabajo — ZERO Robustez

Índice de prompts listos para copiar. Cada bloque es paste-ready en su terminal.

**Orden de ejecución:**
1. 🔨 WORKER #1 — Validadores
2. 🔨 WORKER #2 — Retry logic
3. 🔍 DEBUG #1 — Tests núcleo
4. 🔍 DEBUG #2 — Tests stress
5. 🤖 AGENTS #1 — MEDIABUYER
6. 🤖 AGENTS #2 — Mejorar CONCIERGE
7. 🤖 AGENTS #3 — Test suite agentes
8. 🎨 DESIGN #1 — Campañas dashboard
9. 🎨 DESIGN #2 — Replies UI

---

## 🔨 WORKER #1 — Validadores + Config

```
[TARGET: 🔨 WORKER]

OBJETIVO — Añadir validadores configurables por tier y manejo robusto de datos corruptos.

CONTEXTO — Hoy discovery/orchestrator aceptan datos débilmente (regex weak). Sin validación fuerte: dupes, ruido, corrupción de CRM. ZERO debe rechazar datos inválidos antes de prometer nada.
Plan B #5 (Sin crasheos, maneja datos malos) está marcado ✅ pero sin validación fuerte en discovery.
Los cambios en concierge.py + mediabuyer.py están en progreso; no tocar esos.

SCOPE — Archivos a tocar:
  ✅ zero/config.py (añadir reglas de validación por tier: GROWTH vs ENTERPRISE)
  ✅ zero/validators.py (NUEVO: validador de emails, teléfono, nombres)
  ✅ zero/discovery.py (aplicar validadores, deduplica dentro del batch, log % aceptados)
  ✅ zero/orchestrator.py (manejador de ofertas huérfanas en pending_offers)
  ❌ zero/agents/ (AGENTS: no tocar)
  ❌ tests/ (DEBUG: no tocar)
  ❌ frontend/ (DESIGN: no tocar)

RESTRICCIONES — Supuesto: entrada en español/ascii+tildes. Ignorar emojis/multi-idioma. Deduplicación solo dentro del batch de discovery, no vs CRM. Config-first: todas las reglas van en config.py. Mock-first: validadores deben pasar tests sin deps externas.

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest discover -s tests -t .  (debe pasar; hoy hay 40 tests, no debe bajar)
  • git diff zero/config.py → nuevas claves: VALIDATOR_TIERS = {"GROWTH": {...}, "ENTERPRISE": {...}}
  • git diff zero/discovery.py → log cada validación (lines como "DiscoverySource: 42 raw → 35 valid (83%)")
  • Ofertas sin memoria en pending_offers no crashean (no-op en orchestrator.py)

REPORTE — Al final, di qué cambios hiciste, si hay inconsistencias detectadas (ej: agentes usando validators sin conocerlo) y si DEBUG/DESIGN necesitan updates.
```

---

## 🔨 WORKER #2 — Retry logic + Logging

```
[TARGET: 🔨 WORKER]

OBJETIVO — Retry logic y logging detallado para Email + WhatsApp bajo falla.

CONTEXTO — Canales (zero/channels.py) están listos pero sin manejo de fallas en volumen. Si SMTP cae o WhatsApp rate-limita, hoy crashea o pierde tracking. Necesita: reintento exponencial + logging que trace cada envío (qué falló, dónde, por qué).

SCOPE — Archivos a tocar:
  ✅ zero/channels.py (Outbox, MockSender, EmailSender, WhatsAppSender: añadir retry logic + logging)
  ✅ zero/config.py (nuevas: RETRY_MAX_ATTEMPTS=3, RETRY_BACKOFF_SECS=[1,2,4])
  ✅ zero/crm.py (si es necesario: persistir estado de envío con error details en historial)
  ❌ tests/ (DEBUG: no tocar)
  ❌ zero/agents/ (AGENTS: no tocar)
  ❌ frontend/ (DESIGN: no tocar)

RESTRICCIONES — Mock-first: MockSender simula fallos controladamente (test puede pedir "falla en intento 2"). No deps externas para retry. Logging a stderr con timestamp + lead_key + canal + status.

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest discover -s tests -t .  (pasa)
  • Demo con 5 envíos where 2 simulan "SMTP timeout": log muestra reintento + backoff + final result (retry ok o drop)
  • git diff zero/channels.py → clase Outbox tiene métodos send_with_retry(task_id, lead, msg, channel)

REPORTE — Qué cambios, si hay nuevas dependencias, si DEBUG necesita fixtures de envío.
```

---

## 🔍 DEBUG #1 — Tests núcleo (Parseo + Supabase)

```
[TARGET: 🔍 DEBUG]

OBJETIVO — Test suite exhaustivo: parseo de respuestas + round-trip Supabase + integridad de ofertas.

CONTEXTO — orchestrator.py (accepts_offer, pick_channel, build_info_summary) y memory.py (pending_offers restore) no tienen tests de edge cases. Sin ellos, data corruption en vivo pasa desapercibida.
WORKER acaba de escribir validadores; DEBUG ahora escribe tests que los usen.

SCOPE — Archivos a crear/tocar:
  ✅ tests/test_edge_cases_parsing.py (NUEVO: 30+ casos en accepts_offer, pick_channel, emails extraídos)
  ✅ tests/test_supabase_roundtrip.py (NUEVO: 5-6 tests ICP/memory/leads → cloud → restore)
  ✅ tests/test_core.py (añadir: 5 tests de ofertas huérfanas / pending_offers integrity)
  ❌ zero/ (WORKER: no tocar)
  ❌ frontend/ (DESIGN: no tocar)

RESTRICCIONES — Tests usan mock (cero calls a APIs reales). Si hay SupabaseCRM/Memory, mockear con stubs JSON. Cada test es <30 líneas. Nombres descriptivos (ej: test_accept_offer_with_tildes_and_caps).

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest discover -s tests -t .  (75+ tests pasan; hoy 40, suma 35)
  • python3 -m unittest tests.test_edge_cases_parsing -v  (30+ tests listados)
  • python3 -m unittest tests.test_supabase_roundtrip -v  (5-6 tests listados)
  • Cobertura: accepts_offer() 100% (16 branches), pick_channel() 100%, pending_offers restore 100%

REPORTE — Tests que escribiste, qué edge cases encontraste (ej: "Ø maiúscula no era reconocida"). Si hay bugs encontrados, reséñalos sin fijarlos.
```

---

## 🔍 DEBUG #2 — Tests stress (Canales + Discovery)

```
[TARGET: 🔍 DEBUG]

OBJETIVO — Test suite para canales bajo estrés y validación fuerte en discovery.

CONTEXTO — zero/channels.py (WORKER acaba de añadir retry) y zero/discovery.py (WORKER acaba de añadir validadores) necesitan cobertura de stress + datos reales.
Canales: ¿qué pasa con 100 leads + 2 fallos? Discovery: ¿qué filtra, qué pasa?

SCOPE — Archivos a crear:
  ✅ tests/test_channels_stress.py (NUEVO: 8-10 tests: volumen, fallo SMTP, rate limit, destinatario inválido)
  ✅ tests/test_discovery_validation.py (NUEVO: 8-10 tests: email sin @, teléfono <5 dígitos, dupes, nombres vacíos)
  ❌ zero/ (WORKER: no tocar)
  ❌ frontend/ (DESIGN: no tocar)

RESTRICCIONES — Tests usan mock. Fixtures: 100-lead batch (CSV/JSON mock). Cada test simula 1 fallo. Datos: nombres/emails/teléfonos reales o realistic duds.

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest tests.test_channels_stress -v  (8-10 tests listados, todos pasan)
  • python3 -m unittest tests.test_discovery_validation -v  (8-10 tests listados, todos pasan)
  • python3 -m unittest discover -s tests -t .  (total 90+ tests pasan)
  • Un test ejemplo: test_discovery_deduplicates_same_batch() — recibe 10 dupes, retorna 1.
  • Otro: test_channels_100_leads_2_failures() — 100 envíos, 2 simulan SMTP timeout, 98 exitosos, 2 retry ok.

REPORTE — Tests escritos, qué comportamientos bajo estrés encontraste (ej: "dedup ignoraba case mismatch"). Bugs encontrados: reséñalos.
```

---

## 🤖 AGENTS #1 — MEDIABUYER Agente

```
[TARGET: 🤖 AGENTS]

OBJETIVO — Implementar agente MEDIABUYER que analice ROI/CPL y proponga decisiones de presupuesto.

CONTEXTO — Meta Ads (zero/metaads.py) está conectado pero sin decisión automática. MEDIABUYER debe analizar performance de campañas y proponer: pausar, aumentar presupuesto o mantener (mock-first). Vive en zero/agents/mediabuyer.py.
Supuesto: zero/config.py tendrá MEDIABUYER_THRESHOLDS (definirá WORKER); MEDIABUYER solo los aplica.

SCOPE — Archivos a crear/tocar:
  ✅ zero/agents/mediabuyer.py (NUEVO: clase MediaBuyer con _mock_result + real path via Claude)
  ✅ prompts/mediabuyer.md (NUEVO: instrucciones para Claude)
  ✅ zero/orchestrator.py (si es necesario: integración — reportar qué cambios)
  ❌ zero/config.py (WORKER: no tocar, tu agente asume que existen MEDIABUYER_THRESHOLDS)
  ❌ frontend/ (DESIGN: no tocar)
  ❌ tests/ (DEBUG: no tocar)

RESTRICCIONES — Mock-first: _mock_result() determinista, retorna {"action": "pause|increase|maintain", "reason": "...", "new_budget": X}. Real path: recibe lead stats (qty, CPL real, budget spent) y propone. Input: TaskPayload (campaigns state + leads generated). Output: AgentResponse (action + reason). Supuesto: config.py tendrá MEDIABUYER_THRESHOLDS = {"cpl_max": X, "roi_min": Y}; usa esos números en prompts.

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest discover -s tests -t .  (pasa; hoy 40, no debe bajar)
  • Clase MediaBuyer existe, _mock_result() retorna AgentResponse válida
  • Mock determinista: mismo input (100 leads, $500 spent, CPL $15) → siempre {"action": "pause", ...} o {"action": "maintain", ...} (consistent)
  • Prompts/mediabuyer.md explica qué analiza (ROI, CPL vs threshold) y qué propone
  • Si integraste en orchestrator.py, git diff muestra dónde y por qué

REPORTE — Qué escribiste, si hay config que MEDIABUYER necesita de zero/config.py (reporta sin fijar), si integración en orchestrator requiere cambios de WORKER.
```

---

## 🤖 AGENTS #2 — Mejorar CONCIERGE

```
[TARGET: 🤖 AGENTS]

OBJETIVO — Mejorar CONCIERGE: prompts más robustos + detección confiable de intents.

CONTEXTO — CONCIERGE (roadmap completado) maneja intents (aceptación/objeción/confianza/info) y promete envíos (resumen, 3 ejemplos). Sin validación exhaustiva: confusion entre intents (¿"no gracias" es objeción o rechazo?), edge cases (emojis, caps, tildes), y sin tests que verifiquen que promesas se cumplen.
Cambios en concierge.py están en progreso; mejora los prompts en prompts/concierge.md.

SCOPE — Archivos a tocar:
  ✅ prompts/concierge.md (mejorar claridad de intents, ejemplos de msgs reales → intent esperado)
  ✅ zero/agents/concierge.py (si es necesario: mejorar parsing de intents — reportar)
  ❌ zero/orchestrator.py (WORKER: no tocar)
  ❌ tests/ (DEBUG: no tocar, pero reporta qué tests faltan)
  ❌ frontend/ (DESIGN: no tocar)

RESTRICCIONES — Mock-first: intents detectados sin LLM (determinista). Intents son: `accept` (aceptación), `object` (objeción), `trust` (confianza), `info` (pedir info). Prompts deben ser claros: qué distingue cada uno. Si modificas concierge.py, reporta; WORKER validará.

ACEPTACIÓN — Verificable al correr:
  • prompts/concierge.md mejorado: describe cada intent + 5 ejemplos reales de msgs (español) → intent correcto
  • Intents detectados correctamente en: "no me interesa" (object), "mándame resumen" (info), "dale, adelante" (accept), "no confío mucho, es en línea?" (trust)
  • Edge cases: "NO, GRACIAS" (caps), "nooo" (repetidas), "por acá" (canal, no intent) — todos parsed correctamente
  • Si hay cambios en concierge.py, git diff es pequeño y reportado explícitamente

REPORTE — Mejoras en prompts/concierge.md, qué edge cases encontraste que antes no funcionaban, qué cambios en concierge.py (si los hay) necesita validar WORKER.
```

---

## 🤖 AGENTS #3 — Test suite de Agentes

```
[TARGET: 🤖 AGENTS]

OBJETIVO — Test suite exhaustivo: verificar que todos los agentes (PROSPECTOR, QUALIFIER, CONCIERGE, MEDIABUYER) cumplen contrato + determinismo + robustez de intents.

CONTEXTO — Cada agente tiene _mock_result() pero sin tests que verifiquen: retorna AgentResponse válida, determinismo (mismo input → mismo output), y que intents CONCIERGE (nuevo) se detectan correctamente en 15+ casos reales.
MEDIABUYER es nuevo (AGENTS #1 lo escribió), CONCIERGE mejoró (AGENTS #2 lo hizo), ahora tests verifican ambos.

SCOPE — Archivos a crear/tocar:
  ✅ tests/test_agents.py (NUEVO: tests de mock_result + determinismo + intents)
  ✅ tests/test_concierge_intents.py (NUEVO: 15+ msgs reales → intent correcto)
  ❌ zero/agents/ (AGENTS: no tocar, confía en que MEDIABUYER + CONCIERGE mejoras están listas)
  ❌ zero/orchestrator.py (WORKER: no tocar)
  ❌ frontend/ (DESIGN: no tocar)

RESTRICCIONES — Tests usan mock (cero calls a APIs externas). Cada test <30 líneas. Determinismo: verifica que llamadas repetidas a _mock_result(same_input) retornan mismo output. Intents CONCIERGE: 15+ msgs reales en español (rechazar, pedir info, confiar, etc.) → intent detectado correcto.

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest tests.test_agents -v  (10+ tests: PROSPECTOR, QUALIFIER, CONCIERGE, MEDIABUYER)
    - test_prospector_mock_returns_valid_schema()
    - test_prospector_deterministic()
    - test_qualifier_mock_valid()
    - test_concierge_mock_valid()
    - test_mediabuyer_mock_valid()
    - test_mediabuyer_deterministic()
  • python3 -m unittest tests.test_concierge_intents -v  (15+ tests de intent detection)
    - test_intent_accept_simple() — "dale" → accept
    - test_intent_accept_with_caps() — "DALE" → accept
    - test_intent_object_explicit() — "no me interesa" → object
    - test_intent_trust_implicit() — "es seguro?" → trust
    - test_intent_info_request() — "mándame más info" → info
    - test_intent_edge_tildes() — "Sí, dale" (tildes) → accept
    - test_intent_edge_short_msg() — "ok" → accept
    - test_intent_edge_emojis() — "dale 👍" → accept
  • python3 -m unittest discover -s tests -t .  (total 55+ tests pasan, ahora eran 40)

REPORTE — Tests que escribiste, intents difíciles de detectar que encontraste, si hay agentes con behaviors inesperados (reporta sin fijar).
```

---

## 🎨 DESIGN #1 — Campañas Dashboard

```
[TARGET: 🎨 DESIGN]

OBJETIVO — Dashboard de Campañas Meta Ads: KPI cards, tabla, filtros, estado de conexión en Config — todo ZEROAI brand.

CONTEXTO — Meta Ads está mock-first en zero/metaads.py + /api/campaigns. Pestaña "Campañas" existe pero es bare-bones. Falta UI: KPIs (gasto/leads/CPL), tabla de campañas con estado, empty state, y card en Config que muestre conexión.
Supuesto: /api/campaigns retorna {campaigns: [...], stats: {total_spend, total_leads, avg_cpl}}.

SCOPE — Archivos a crear/tocar:
  ✅ frontend/src/pages/Campaigns.jsx (mejorar: KPI cards + tabla + filtros)
  ✅ frontend/src/pages/Config.jsx (añadir: IntegrationCard para Meta Ads)
  ✅ frontend/src/styles/ (si necesario: clases ZEROAI)
  ❌ zero/ (WORKER: no tocar)
  ❌ tests/ (DEBUG: no tocar)

RESTRICCIONES — ZEROAI brand: paleta slate, pewter, champagne gold, off-white; logo Ø. Mockup primero (Figma/ASCII), componentes después. Estado vacío: "No hay campañas activas" + Ø gris. Card Meta Ads en Config: "Conectado" (green), "Error: Key inválida" (red), botón "Reconectar". KPI cards: gasto total, leads generados, CPL promedio (3 cards). Tabla: nombre, estado (activa/pausada), presupuesto, leads, creada hace X.

ACEPTACIÓN — Verificable al abrir:
  • frontend/src/pages/Campaigns.jsx existe y es paste-ready en React (JSX)
  • 3 KPI cards visibles (gasto, leads, CPL) con números mock
  • Tabla: 3-5 campañas mock, columnas: nombre, estado, presupuesto, leads, creada
  • Filtro "Estado" (todas/activas/pausadas)
  • Empty state: "No hay campañas" + Ø gris cuando lista vacía
  • IntegrationCard en Config.jsx para Meta Ads (status + botón)
  • Colores ZEROAI: slate backgrounds, pewter text, champagne gold accent
  • Diego puede abrir frontend y ver Campañas funcional en mock

REPORTE — Componentes creados, mockup adjunto (si es necesario), decisiones visuales (ej: por qué KPI cards en grid 3), si falta endpoint /api/campaigns (WORKER debe hacerlo).
```

---

## 🎨 DESIGN #2 — Replies UI (WhatsApp Inbound)

```
[TARGET: 🎨 DESIGN]

OBJETIVO — Real-time reply UI: panel de respuestas WhatsApp, chat detail, test modal en Config — ZEROAI brand.

CONTEXTO — CONCIERGE responde a WhatsApp inbound (roadmap completado), pero UI no muestra conversación. Falta: panel "Respuestas" con lista de leads que escribieron, click → chat detail (timeline msgs cliente + respuesta ZERO + intent detectado), card en Config para testear agente.
Supuesto: /api/replies retorna {replies: [{lead_key, msg, timestamp, intent, zero_response, status}]}, /api/whatsapp/simulate simula un msg y retorna respuesta CONCIERGE.

SCOPE — Archivos a crear/tocar:
  ✅ frontend/src/pages/Replies.jsx (NUEVO: lista de leads con replies)
  ✅ frontend/src/pages/ChatDetail.jsx (NUEVO: timeline de conversation)
  ✅ frontend/src/pages/Config.jsx (mejorar: card "Testear agente" con modal)
  ✅ frontend/src/styles/ (si necesario: ZEROAI)
  ❌ zero/ (WORKER: no tocar)
  ❌ tests/ (DEBUG: no tocar)

RESTRICCIONES — ZEROAI brand. Panel Respuestas: card por lead, muestra "último msg", timestamp, estado (enviado/leído/respondido). Click → ChatDetail: timeline vertical (cliente msg → ZERO response), intent detected badge (accept/object/trust/info), oferta enviada (si aplica). Modal "Testear agente": input msg, botón "Enviar", retorna respuesta mock CONCIERGE + intent detectado. No calls a APIs reales en frontend (solo mocks).

ACEPTACIÓN — Verificable al abrir:
  • frontend/src/pages/Replies.jsx existe, muestra 2-3 leads mock con replies
  • Cada card: nombre lead, último msg (snippet), time, estado
  • Click → ChatDetail: timeline vertical con msgs cliente + respuestas ZERO, intent badge
  • Modal "Testear agente" en Config: input field + botón "Enviar", retorna respuesta mock
  • Colores ZEROAI: slate, pewter, champagne accents
  • Diego puede abrir frontend y ver Respuestas + ChatDetail + test modal funcional

REPORTE — Componentes creados, si falta /api/replies (WORKER debe hacerlo), decisiones de layout (ej: por qué timeline vertical).
```

---

**✅ Todos los prompts listos para copiar.**
