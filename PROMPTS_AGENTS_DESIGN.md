# Prompts AGENTS + DESIGN — Integración WhatsApp Inbound

Estado actual (verificado 2026-06-12):

**✅ AGENTS (Ya hecho):**
- CONCIERGE agente — responde WhatsApp, detecta intents, promete envíos
- MEDIABUYER agente — analiza campañas Meta
- Tests de agentes en test_core.py (15+ tests)

**❌ AGENTS (Falta):**
- APIs para que DESIGN consulte replies del CONCIERGE
- API para testear CONCIERGE sin enviar
- API para ver estado de agentes

**❌ DESIGN (Falta):**
- WhatsApp.jsx — página para ver respuestas y testear agente
- Agentes.jsx — navega incorrectamente a /config en lugar de a página real
- No hay UI para pending_offers del CONCIERGE

---

## 🤖 AGENTS #1 — APIs para Replies + Testing

```
[TARGET: 🔨 WORKER] — porque estas son APIs backend

OBJETIVO — Crear endpoints backend para que DESIGN acceda a replies del CONCIERGE y testee el agente.

CONTEXTO — CONCIERGE existe y responde WhatsApp (roadmap completado). Pero DESIGN no tiene APIs para:
  • Ver replies que llegaron (GET /api/replies)
  • Ver detalle de una conversación (GET /api/reply/{lead_key})
  • Testear agente (POST /api/whatsapp/simulate ya existe, mejorar si falta)

SCOPE — Archivos a crear/tocar:
  ✅ api.py — agregar:
     • GET /api/replies?client=X&limit=20&offset=0 → {replies: [...], total: N}
     • GET /api/reply/{lead_key} → {msgs: [...], intents: [...], pending_offer: {...}}
     • POST /api/whatsapp/test (alternativa clara a /api/whatsapp/simulate si la anterior es confusa)
  ✅ zero/crm.py — si es necesario: métodos para query replies por cliente
  ✅ zero/inbox.py — si es necesario: métodos para listar replies
  ❌ frontend/ (DESIGN: no tocar)
  ❌ zero/agents/ (AGENTS: no tocar)

RESTRICCIONES — Paginación (limit/offset). Mock-first. Retornar estructura que DESIGN entienda: msgs con timestamp, intent detectado, pending_offer si aplica. No enviar datos privados (keys de clientes, etc).

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest discover -s tests -t .  (pasa)
  • curl localhost:5000/api/replies?client=acme → {replies: [{lead_key, last_msg, timestamp, intent, has_pending_offer}], total: N}
  • curl localhost:5000/api/reply/diego@example.com → {msgs: [{from, text, ts, intent, zero_response}], pending_offer: {...}}
  • curl -X POST localhost:5000/api/whatsapp/simulate -d '{"msg":"Hola","client":"acme"}' → {reply: "...", intent: "..."}

REPORTE — Endpoints creados, estructura de respuesta, si hay cambios necesarios en CRM/inbox.
```

---

## 🎨 DESIGN #1 — WhatsApp Replies Page

```
[TARGET: 🎨 DESIGN]

OBJETIVO — Crear página WhatsApp.jsx: panel de respuestas inbound con timeline de conversación y test modal.

CONTEXTO — CONCIERGE responde WhatsApp (backend listo). Agentes.jsx tiene card para WhatsApp pero navega a /config, no a página real. Falta:
  • Lista de leads que respondieron (último msg, timestamp, intent, estado)
  • Click → ChatDetail: timeline vertical (msgs cliente + respuestas CONCIERGE)
  • Modal "Testear agente": input msg, botón "Enviar", retorna respuesta + intent detectado
  • Badge: "2 leads respondieron, 1 oferta pendiente"

SUPUESTO: WORKER creó /api/replies, /api/reply/{key}, /api/whatsapp/simulate (o similar).

SCOPE — Archivos a crear/tocar:
  ✅ frontend/src/pages/WhatsApp.jsx (NUEVO: lista de replies)
  ✅ frontend/src/components/ChatDetail.jsx (NUEVO: timeline de conversation)
  ✅ frontend/src/components/TestAgentModal.jsx (NUEVO: test del agente)
  ✅ frontend/src/lib/api.js (agregar: api.replies(), api.replyDetail(), api.testWhatsApp())
  ✅ frontend/src/pages/Agentes.jsx (mejorar: WhatsApp card navega a /whatsapp, no /config)
  ❌ zero/ (WORKER: no tocar)
  ❌ tests/ (DEBUG: no tocar)

RESTRICCIONES — ZEROAI brand (slate, pewter, champagne). No calls a APIs reales (solo mocks en frontend). ChatDetail: timeline vertical con emojis/badges de intents. Modal reutilizable.

ACEPTACIÓN — Verificable al abrir frontend:
  • /whatsapp muestra lista de 2-3 leads mock con replies (nombre, último msg snippet, time, intent badge)
  • Click → ChatDetail: timeline vertical (cliente msg ← ZERO response), intent badges, oferta (si la hay)
  • "Testear agente" modal en WhatsApp: input "Hola, ¿cuál es el precio?" → retorna respuesta + intent badge
  • Agentes.jsx — card WhatsApp navega a /whatsapp (no /config)
  • Colores ZEROAI, animaciones suaves

REPORTE — Componentes creados, si falta algún endpoint (WORKER debe hacerlo), decisiones de layout (ej: por qué timeline vertical).
```

---

## 🎨 DESIGN #2 — Mejorar Agentes.jsx (navegación correcta)

```
[TARGET: 🎨 DESIGN]

OBJETIVO — Actualizar Agentes.jsx para que cada card navigue a su página real (Llamadas, Vender, WhatsApp).

CONTEXTO — Hoy:
  • Email → /vender ✅ (correcto)
  • Llamadas → /llamadas ✅ (correcto)
  • WhatsApp → /config ❌ (debería ir a /whatsapp)
  • Instagram, LinkedIn → disabled ✅ (correcto)

Además: mejorar layout visual, mostrar más estado (ej: "2 leads respondieron en 24h").

SCOPE — Archivos a tocar:
  ✅ frontend/src/pages/Agentes.jsx — actualizar navegación + mejorar visuals
  ✅ frontend/src/components/ — si necesario: componentes reutilizables
  ❌ zero/ (WORKER: no tocar)
  ❌ tests/ (DEBUG: no tocar)

RESTRICCIONES — ZEROAI brand. Mantener estructura actual (grid de cards). Si agregar info de estado (ej: "2 replies en 24h"), asumir que APIs la proveen.

ACEPTACIÓN — Verificable al abrir:
  • WhatsApp card → onClick navega a /whatsapp (no /config)
  • Email card → onClick navega a /vender ✅ (sin cambios)
  • Llamadas card → onClick navega a /llamadas ✅ (sin cambios)
  • (Opcional) Mostrar badge de estado: "2 leads respondieron" en WhatsApp card

REPORTE — Cambios hechos, si necesita APIs para mostrar estado dinámico.
```

---

## 🤖 AGENTS #2 — Mejorar CONCIERGE (Prompts + Robustez)

```
[TARGET: 🤖 AGENTS]

OBJETIVO — Mejorar robustez de CONCIERGE: prompts más claros, intents más fiables, edge cases manejados.

CONTEXTO — CONCIERGE funciona (tiene tests), pero sin validación exhaustiva de que:
  • Intents se detectan correctamente en 15+ casos reales españoles
  • Promesas ("te mando resumen") se cumplen realmente
  • Edge cases (msgs cortos, tildes, caps) se manejan sin error

SCOPE — Archivos a tocar:
  ✅ prompts/concierge.md — mejorar claridad de intents, ejemplos de msgs reales
  ✅ zero/agents/concierge.py — si es necesario: mejorar _mock_result parsing
  ❌ zero/orchestrator.py (WORKER: no tocar)
  ❌ tests/ (DEBUG: no tocar, reporta qué tests faltan)

RESTRICCIONES — Intents: disclose, optout, trust, objection, info, pricing, explain, meeting, accept. Prompts claros. Si modificas concierge.py, reporta; WORKER validará.

ACEPTACIÓN — Verificable al correr:
  • prompts/concierge.md mejorado: describe cada intent + 5-7 ejemplos reales (español) → intent esperado
  • Intents correctos en: "no me interesa" (optout), "mándame resumen" (info), "dale, vamos" (accept), "¿es seguro?" (trust)
  • Edge cases: "NO, GRACIAS" (caps), "nooo" (elongated), "ok", "sí👍" (con emoji), "por acá" (canal, no intent) — todos parsed sin error
  • Promesas: si CONCIERGE dice "te mando resumen", ZERO lo envía (verificable en pending_offers)
  • Si cambios en concierge.py, git diff pequeño y reportado

REPORTE — Mejoras en prompts, edge cases encontrados, cambios en concierge.py (si hay).
```

---

## 🤖 AGENTS #3 — Tests de Contrato (Concierge + Agents)

```
[TARGET: 🔍 DEBUG]

OBJETIVO — Tests exhaustivos: verificar que CONCIERGE y otros agentes retornan schema válida, son determinísticos, y manejan edge cases.

CONTEXTO — CONCIERGE y otros agentes ya funcionan, pero sin tests de:
  • Determinismo: mismo input → mismo mock output
  • Contrato: retorna estructura esperada (intent, reply, etc)
  • Edge cases: input corrupto no crashea

SCOPE — Archivos a crear:
  ✅ tests/test_concierge_contract.py (NUEVO: 8 tests de contrato, determinismo, intents)
  ✅ tests/test_agent_contracts.py (NUEVO: 5 tests de contrato para todos los agentes)
  ❌ zero/agents/ (AGENTS: no tocar)
  ❌ tests/test_core.py (DEBUG: no tocar, estos son complementarios)

RESTRICCIONES — Mock. <30 líneas cada test. Contrato verificado contra zero/contracts.py.

ACEPTACIÓN — Verificable al correr:
  • python3 -m unittest tests.test_concierge_contract -v  (8 tests)
    - test_concierge_returns_valid_schema()
    - test_concierge_deterministic_same_input()
    - test_concierge_intent_field_present()
    - test_concierge_intent_optout_on_no_me_interesa()
    - test_concierge_intent_info_on_mandame_resumen()
    - test_concierge_intent_accept_on_dale()
    - test_concierge_intent_trust_on_es_seguro()
    - test_concierge_edge_case_caps_handled()
  • python3 -m unittest tests.test_agent_contracts -v  (5+ tests de otros agentes)
  • python3 -m unittest discover -s tests -t .  (total 45+, hoy son 40)

REPORTE — Tests escritos, contract issues encontrados, agentes con behaviors inesperados.
```

---

## Orden de Ejecución Recomendado

### Bloque 1 (Paralelo):
- **🔨 WORKER** — APIs para replies (BLOCKING para DESIGN)
- **🤖 AGENTS** — Mejorar CONCIERGE (INDEPENDIENTE)

### Bloque 2 (Después de Bloque 1):
- **🎨 DESIGN #1** — WhatsApp.jsx (requiere APIs del WORKER)
- **🎨 DESIGN #2** — Mejorar Agentes.jsx (puede hacerse paralelo a DESIGN #1)
- **🔍 DEBUG** — Tests de contrato

---

✅ **Todos verificados contra código real. Listo para ejecutar.**
