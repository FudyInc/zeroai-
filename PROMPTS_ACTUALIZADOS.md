# Prompts Actualizados — ZERO (Basados en trabajo real ya hecho)

Análisis del estado actual (2026-06-12):

**✅ YA COMPLETO:**
- MediaBuyer agente (mediabuyer.py + prompts/mediabuyer.md + tests en test_core.py)
- Concierge agente (concierge.py + prompts/concierge.md + tests de intents)
- Campanas.jsx (página completa: KPIs, filtros, tabla, botones optimize/sync)
- Tests de agentes (15+ tests en test_core.py)

**❌ FALTA PARA ROBUSTEZ:**
- Validadores configurables (zero/validators.py — nuevo módulo)
- Retry logic + logging en canales (mejorar zero/channels.py)
- Tests de edge cases (parseo, Supabase roundtrip, discovery validation)
- APIs backend (/api/replies para WhatsApp inbound)
- Replies.jsx (nueva página para respuestas en tiempo real)

**🔄 MEJORAS A LO EXISTENTE:**
- Concierge: prompts más robustos + handling de edge cases
- Campanas: agregar gráficos/trends (opcional)
- Discovery: validación fuerte antes de guardar leads

---

## 🔨 WORKER #1 — Validadores (módulo nuevo)

```
[TARGET: 🔨 WORKER]

OBJETIVO — Crear módulo de validadores configurables por tier (GROWTH vs ENTERPRISE) para rechazar datos corruptos antes de llegar al CRM.

CONTEXTO — Discovery retorna contactos sin validación fuerte (emails sin @, teléfonos rotos, nombres vacíos). Sin rechazo temprano: ruido entra al CRM, degrada calidad. Validadores deben ser:
  • Configurables por tier (reglas diferentes para GROWTH = liberal, ENTERPRISE = estricto)
  • Rápidos (sin deps externas)
  • Logged (% de datos que pasa/rechaza)

SCOPE — Archivos a crear/tocar:
  ✅ zero/validators.py (NUEVO: clases ValidatorRules, validate_contact, validate_batch)
  ✅ zero/config.py (añadir: VALIDATOR_TIERS con reglas por tier)
  ✅ zero/discovery.py (aplicar validadores antes de retornar leads, loguear %)
  ❌ zero/agents/ (AGENTS: no tocar)
  ❌ tests/ (DEBUG: no tocar)
  ❌ frontend/ (DESIGN: no tocar)

RESTRICCIONES — Mock-first: validadores sin deps externas. Entrada en español/ascii. Dedup solo dentro del batch. Config-first: todas las reglas en zero/config.py.

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest discover -s tests -t .  (40+ tests pasan, no baja)
  • zero/validators.py existe con: class ValidatorRules, métodos validate_email, validate_phone, validate_batch
  • zero/config.py tiene: VALIDATOR_TIERS = {"GROWTH": {...rules...}, "ENTERPRISE": {...stricter...}}
  • zero/discovery.py loguea: "DuckDuckGoSource: 42 raw → 35 valid (83%)"
  • Datos inválidos (email sin @, teléfono <5 dígitos, nombre vacío) se rechazan silenciosamente

REPORTE — Qué escribiste, si hay reglas faltantes, si discovery necesita cambios.
```

---

## 🔨 WORKER #2 — Retry logic + Logging en Canales

```
[TARGET: 🔨 WORKER]

OBJETIVO — Agregar retry exponencial + logging detallado a zero/channels.py para manejar fallos de SMTP/WhatsApp.

CONTEXTO — Hoy si SMTP falla, el envío se pierde. Con volumen (100 leads), eso es inaceptable. Necesita:
  • Reintento exponencial (3x con backoff 1s, 2s, 4s)
  • Logging por envío: timestamp, lead_key, canal, intento, status (ok/retry/drop)
  • Mock determinista para testing (puede simular "falla en intento 2")

SCOPE — Archivos a tocar:
  ✅ zero/channels.py (Outbox, EmailSender, WhatsAppSender: agregar send_with_retry)
  ✅ zero/config.py (nuevas: RETRY_MAX_ATTEMPTS=3, RETRY_BACKOFF_SECS=[1,2,4])
  ✅ zero/crm.py (si es necesario: guardar error details en historial)
  ❌ tests/ (DEBUG: no tocar, pero reporta qué tests necesita)
  ❌ zero/agents/ (AGENTS: no tocar)
  ❌ frontend/ (DESIGN: no tocar)

RESTRICCIONES — Mock-first: MockSender simula fallos controladamente. No deps externas para retry. Logging a stderr.

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest discover -s tests -t .  (pasa)
  • Demo: 5 envíos donde 2 simulan SMTP timeout → log muestra reintento + backoff + resultado
  • git diff zero/channels.py → métodos send_with_retry() presentes
  • git diff zero/config.py → RETRY_MAX_ATTEMPTS, RETRY_BACKOFF_SECS presentes

REPORTE — Cambios hechos, si hay nuevas deps, qué tests necesita DEBUG.
```

---

## 🔨 WORKER #3 — APIs Backend para Replies (WhatsApp inbound)

```
[TARGET: 🔨 WORKER]

OBJETIVO — Crear endpoints backend para que DESIGN construya UI de respuestas WhatsApp en tiempo real.

CONTEXTO — Concierge responde a WhatsApp (roadmap completeto), pero frontend no tiene endpoint para mostrar replies. Faltan:
  • GET /api/replies?client=X&limit=20&offset=0 → lista de leads que respondieron
  • GET /api/reply/{lead_key} → detalle: msgs cliente + respuestas ZERO + intents
  • POST /api/whatsapp/simulate → test agent (recibe msg, retorna respuesta mock)

SCOPE — Archivos a tocar:
  ✅ api.py (agregar rutas /api/replies, /api/reply/{lead_key}, /api/whatsapp/simulate)
  ✅ zero/inbox.py (si es necesario: métodos para query replies por cliente)
  ✅ zero/crm.py (si es necesario: proyecciones para replies)
  ❌ frontend/ (DESIGN: no tocar)
  ❌ tests/ (DEBUG: no tocar)
  ❌ zero/agents/ (AGENTS: no tocar)

RESTRICCIONES — Mock-first: /api/whatsapp/simulate retorna mock de CONCIERGE (sin key). Real path: usa Anthropic si hay key. Paginación (limit/offset).

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest discover -s tests -t .  (pasa)
  • curl localhost:5000/api/replies?client=acme → {replies: [...], total: N}
  • curl -X POST localhost:5000/api/whatsapp/simulate -d '{"msg":"Hola"}' → {response: "...", intent: "..."}
  • DESIGN puede pegar en frontend/src/lib/api.js: api.replies(client), api.replyDetail(lead_key), api.simulateWhatsApp(msg)

REPORTE — Endpoints creados, estructura de respuesta, si hay cambios necesarios en CRM/inbox.
```

---

## 🔍 DEBUG #1 — Tests de Edge Cases (Parseo + Ofertas)

```
[TARGET: 🔍 DEBUG]

OBJETIVO — Cobertura exhaustiva de edge cases en parseo de respuestas y cumplimiento de promesas del Concierge.

CONTEXTO — accepts_offer() y pick_channel() en orchestrator.py aceptan español con edge cases (tildes, caps, emojis, msgs cortos). Sin tests: bugs pasan desapercibidos. Falta también verificar que pending_offers se cumplen.

SCOPE — Archivos a crear:
  ✅ tests/test_edge_cases_parsing.py (NUEVO: 30+ casos de accepts_offer + pick_channel)
  ✅ tests/test_pending_offers.py (NUEVO: 10 casos de oferta → cumplimiento)
  ❌ zero/ (WORKER: no tocar)
  ❌ frontend/ (DESIGN: no tocar)

RESTRICCIONES — Tests usan mock. <30 líneas cada uno. Nombres descriptivos.

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest tests.test_edge_cases_parsing -v  (30+ tests listados)
  • python3 -m unittest tests.test_pending_offers -v  (10+ tests listados)
  • python3 -m unittest discover -s tests -t .  (total 50+, ahora son 40)
  • Cobertura: accepts_offer() 100%, pick_channel() 100%, cumplimiento ofertas 100%

REPORTE — Tests escritos, edge cases encontrados (ej: Ø mayúscula no se reconocía), bugs si hay.
```

---

## 🔍 DEBUG #2 — Tests de Robustez (Canales + Discovery + Supabase)

```
[TARGET: 🔍 DEBUG]

OBJETIVO — Cobertura de stress: canales bajo volumen + fallos, discovery bajo datos sucios, Supabase roundtrip.

CONTEXTO — WORKER acaba de mejorar retry en channels y agregar validadores. Ahora necesita tests que verifiquen:
  • 100 leads + 2 fallos SMTP → reintento ok
  • Discovery recibe 10 dupes → deduplica a 1
  • Email sin @ → rechaza
  • ICP → Supabase → restore → ICP (igual)

SCOPE — Archivos a crear:
  ✅ tests/test_channels_stress.py (NUEVO: 8-10 tests de volumen + fallos)
  ✅ tests/test_discovery_validation.py (NUEVO: 8-10 tests de validación)
  ✅ tests/test_supabase_roundtrip.py (NUEVO: 5-6 tests ICP/memory → cloud → restore)
  ❌ zero/ (WORKER: no tocar)
  ❌ frontend/ (DESIGN: no tocar)

RESTRICCIONES — Mock. Fixtures: 100-lead batch, datos reales-ish. Cada test <30 líneas.

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest tests.test_channels_stress -v  (8-10 tests)
  • python3 -m unittest tests.test_discovery_validation -v  (8-10 tests)
  • python3 -m unittest tests.test_supabase_roundtrip -v  (5-6 tests)
  • python3 -m unittest discover -s tests -t .  (total 70+)
  • Ejemplos de tests:
    - test_channels_100_leads_2_smtp_failures() — 100 → 98 ok, 2 retry ok
    - test_discovery_deduplicates_batch() — 10 dupes → 1
    - test_icp_supabase_roundtrip() — write/read/restore igual

REPORTE — Tests escritos, comportamientos bajo estrés encontrados, bugs encontrados.
```

---

## 🤖 AGENTS #1 — Robustez Concierge (Prompts + Handling)

```
[TARGET: 🤖 AGENTS]

OBJETIVO — Mejorar robustez de CONCIERGE: prompts más claros + manejo de edge cases (msgs cortos, emojis, objeciones complejas).

CONTEXTO — Concierge funciona (tiene tests en test_core.py) pero sin validación en vivo de que intents se detectan correctamente en 15+ casos reales españoles. Falta:
  • Prompts más claros: qué distingue "no me interesa" (object) de "mándame info" (info)?
  • Handling: msgs muy cortos ("ok", "sí"), con emojis ("dale👍"), tildes ("sí, dale"), caps ("NO")
  • Promise: si dice "te mando resumen", ZERO lo envía (ya está en orchestrator, verificar integridad)

SCOPE — Archivos a tocar:
  ✅ prompts/concierge.md (mejorar: claridad intents + ejemplos de msgs edge case)
  ✅ zero/agents/concierge.py (si es necesario: mejorar parsing — reportar)
  ❌ zero/orchestrator.py (WORKER: no tocar)
  ❌ tests/ (DEBUG: no tocar)
  ❌ frontend/ (DESIGN: no tocar)

RESTRICCIONES — Intents: accept, object, trust, info. Prompts claros. Si cambias concierge.py, reporta; WORKER lo valida.

ACEPTACIÓN — Verificable al correr:
  • prompts/concierge.md mejorado: describe cada intent + 5 ejemplos reales → intent esperado
  • Intents detectados en: "no me interesa" (object), "mándame resumen" (info), "dale" (accept), "¿es seguro?" (trust)
  • Edge cases: "NO, GRACIAS" (caps), "nooo", "ok", "sí👍" — todos parsed correctamente
  • Si hay cambios en concierge.py, git diff pequeño y reportado

REPORTE — Mejoras en prompts, edge cases encontrados, cambios en concierge.py (si hay).
```

---

## 🤖 AGENTS #2 — Validación de Contratos (MediaBuyer + Concierge)

```
[TARGET: 🤖 AGENTS]

OBJETIVO — Tests exhaustivos: verificar que MediaBuyer y Concierge retornan AgentResponse válida, determinista y que cumplen contrato.

CONTEXTO — MediaBuyer y Concierge ya funcionan, pero sin tests de:
  • Determinismo: mismo input → mismo mock output (no randomness)
  • Contrato: retorna AgentResponse con campos requeridos (intent, action, reason, etc)
  • Edge cases: input corrupto no crashea, retorna error graceful

SCOPE — Archivos a crear:
  ✅ tests/test_mediabuyer_contract.py (NUEVO: 5 tests de contrato + determinismo)
  ✅ tests/test_concierge_contract.py (NUEVO: 5 tests de contrato + intents + promises)
  ❌ zero/agents/ (AGENTS: no tocar)
  ❌ tests/test_core.py (DEBUG: no tocar, estos son complementarios)
  ❌ frontend/ (DESIGN: no tocar)

RESTRICCIONES — Mock. <30 líneas cada test. Contrato verificado contra zero/contracts.py.

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest tests.test_mediabuyer_contract -v  (5 tests)
  • python3 -m unittest tests.test_concierge_contract -v  (5 tests)
  • python3 -m unittest discover -s tests -t .  (total 50+)
  • Ejemplos:
    - test_mediabuyer_returns_valid_schema()
    - test_mediabuyer_deterministic()
    - test_concierge_intent_field_present()
    - test_concierge_promise_implies_action()

REPORTE — Tests escritos, qué contrato issues encontraste (si hay), agentes con behaviors inesperados.
```

---

## 🎨 DESIGN #1 — Replies Page (WhatsApp Inbound UI)

```
[TARGET: 🎨 DESIGN]

OBJETIVO — Crear Replies.jsx: panel de respuestas WhatsApp en tiempo real con timeline de conversación.

CONTEXTO — Concierge responde a WhatsApp (backend listo), pero frontend no muestra replies. Falta:
  • Lista de leads que escribieron (último msg, ts, estado)
  • Click → ChatDetail: timeline vertical (msgs cliente + respuestas ZERO + intent badge)
  • Card en Config: "Testear agente" (input + botón, retorna respuesta mock + intent)

SUPUESTO: WORKER ya hizo /api/replies, /api/reply/{lead_key}, /api/whatsapp/simulate. DESIGN asume que existen.

SCOPE — Archivos a crear/tocar:
  ✅ frontend/src/pages/Replies.jsx (NUEVO: lista de replies)
  ✅ frontend/src/pages/ChatDetail.jsx (NUEVO: timeline de conversation)
  ✅ frontend/src/pages/Config.jsx (mejorar: card "Testear agente")
  ✅ frontend/src/styles/ (si necesario: ZEROAI brand)
  ❌ zero/ (WORKER: no tocar)
  ❌ tests/ (DEBUG: no tocar)

RESTRICCIONES — ZEROAI brand: slate, pewter, champagne gold. Panel Replies: card por lead, "último msg", time, estado. ChatDetail: timeline vertical (cliente → ZERO), intent badge (accept/object/trust/info), oferta enviada (si aplica). Modal test: input, botón "Enviar", retorna respuesta mock + intent. No calls a APIs reales (solo mock en frontend).

ACEPTACIÓN — Verificable al abrir frontend:
  • frontend/src/pages/Replies.jsx existe, muestra 2-3 leads mock con replies
  • Cada card: nombre lead, snippet último msg, time, estado
  • Click → ChatDetail: timeline vertical, intent badge, oferta (si la hay)
  • Modal "Testear agente" en Config: input, botón, retorna respuesta mock
  • Colores ZEROAI presentes
  • Diego abre /replies y ve conversaciones en tiempo real

REPORTE — Componentes creados, si falta algún endpoint (WORKER debe hacerlo), decisiones de layout.
```

---

## 🎨 DESIGN #2 — Mejoras Visuales a Campanas.jsx (Opcional)

```
[TARGET: 🎨 DESIGN]

OBJETIVO — Agregar elementos visuales a Campanas.jsx: gráfico de trends, breakdown por región/objetivo.

CONTEXTO — Campanas.jsx ya tiene KPIs + tabla + filtros (muy bueno). Mejora visual:
  • Gráfico: spend/leads trend (últimos 7 días, si data existe)
  • Breakdown: "CPL por región" o "leads por objetivo"
  • Cards de campañas: agregar "trending up/down" indicator
  • Estado visual: "Optimizando..." durante sync

SCOPE — Archivos a tocar:
  ✅ frontend/src/pages/Campanas.jsx (agregar gráfico + breakdown + indicators)
  ✅ frontend/src/components/ (si necesario: Chart, sparklines)
  ✅ frontend/src/styles/ (ZEROAI brand)
  ❌ zero/ (WORKER: no tocar)
  ❌ tests/ (DEBUG: no tocar)

RESTRICCIONES — ZEROAI brand. Gráfico simple (recharts o similar). Mock data si no existen trends reales. No deps nuevas si es posible.

ACEPTACIÓN — Verificable al abrir:
  • Gráfico de trends visible (spend/leads últimos 7 días)
  • Breakdown cards (CPL por región o leads por objetivo)
  • Cards de campañas: trending indicator (↑/↓)
  • Estado "Optimizando..." durante clicks

REPORTE — Qué agregaste, deps nuevas (si hay), si necesita cambios backend para trends reales.
```

---

## Orden de Ejecución Recomendado

### Paralelo:
- **🔨 WORKER #1** (Validadores) — independiente
- **🔨 WORKER #3** (APIs Replies) — independiente
- **🎨 DESIGN #1** (Replies.jsx) — depende de WORKER #3, puede empezar

### Secuencial:
1. **🔨 WORKER #2** (Retry) — después de WORKER #1 (usa config)
2. **🔍 DEBUG #1** (Edge cases) — después de WORKER #1 + #2
3. **🔍 DEBUG #2** (Robustez) — después de WORKER #1 + #2 + DEBUG #1
4. **🤖 AGENTS #1** (Robustez Concierge) — independiente
5. **🤖 AGENTS #2** (Validación contratos) — después de AGENTS #1
6. **🎨 DESIGN #2** (Mejoras Campanas) — opcional, independiente

---

✅ **Todos los prompts están actualizados con el trabajo real ya hecho.**
