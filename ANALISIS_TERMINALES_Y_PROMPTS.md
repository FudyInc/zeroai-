# Análisis de Terminales + Prompts Estratégicos

Fecha: 2026-06-12 | Estado actualizado según git + cambios en progreso

---

## 📊 Estado de Cada Terminal

### 🔨 WORKER — API + Core

**EN PROGRESO:**
- `api.py` — endpoints siendo mejorados (última modif reciente)
- `zero/orchestrator.py` — pipeline dividido en pasos nombrados (commit f119437)
- `zero/memory.py`, `zero/memory_supabase.py` — restauración de estado
- `zero/discovery.py` — fuentes de discovery
- `zero/inbox.py` — detección de replies

**ESTADO:** 70% completo. Core robusto, APIs básicas presentes.

**FALTA:**
- ❌ Validadores configurables (validators.py) — no existe
- ❌ Retry logic en channels.py — no está implementado
- ❌ APIs para replies: GET /api/replies, GET /api/reply/{key} — NO existen
- ❌ Tests de edge cases en parseo — no existen

**RECOMENDACIÓN:** WORKER debe crear APIs de replies AHORA (bloquea a DESIGN).

---

### 🎨 DESIGN — Frontend

**EN PROGRESO (según git diff):**
- `frontend/src/pages/Agentes.jsx` — MODIFICADO (navegación?)
- `frontend/src/components/AgentTester.jsx` — NUEVO (existe desde cambios recientes)
- Último commit: "Frontend: página propia del agente WhatsApp (estado, probar conversación, actividad)"
  - **Esto significa WhatsApp.jsx probablemente YA EXISTE**

**ESTADO:** 75% completo. Dashboard funcional, páginas principales presentes.

**YA HECHO:**
- ✅ Campanas.jsx — completa (KPIs, tabla, filtros)
- ✅ Agentes.jsx — existe (pero en modificación)
- ✅ Llamadas.jsx — completa (llamadas Vapi)
- ✅ Vender.jsx — completa (pitch + envío email)
- ✅ Dashboard, Pipeline, Leads, Config — todas presentes

**FALTA:**
- ❌ Verificar si WhatsApp.jsx está funcional (probablemente sí)
- ❌ Mejorar navegación en Agentes.jsx (WhatsApp → /whatsapp, no /config)
- ❌ Integración de Replies.jsx con APIs de WORKER (bloqueada por APIs)

**RECOMENDACIÓN:** DESIGN termina Agentes.jsx, espera APIs de WORKER para completar WhatsApp.jsx.

---

### 🤖 AGENTS — Agentes

**EN PROGRESO:**
- `zero/agents/concierge.py` — MODIFICADO (mejora de intents)
- `prompts/concierge.md` — MODIFICADO (18 ejemplos reales, JSON output claro)

**ESTADO:** 80% completo. Agentes principales funcionales.

**YA HECHO:**
- ✅ PROSPECTOR — descubre
- ✅ QUALIFIER — califica
- ✅ OUTREACH/PITCHWRITER — genera pitch
- ✅ TRACKER — sigue up
- ✅ CONCIERGE — responde WhatsApp (en mejora)
- ✅ MEDIABUYER — gestiona Meta Ads
- ✅ Tests de agentes (82 tests en test_core.py)

**EN MEJORA (casi listo):**
- 🟡 CONCIERGE — prompts mejorados, 18 ejemplos, intents claros (en git diff)

**FALTA:**
- ❌ Tests de contrato (verificar schema de salida)
- ❌ Tests de determinismo (mismo input → mismo output)
- ❌ Tests de edge cases de intents

**RECOMENDACIÓN:** AGENTS termina CONCIERGE, luego escribe tests de contrato.

---

### 🔍 DEBUG — Tests

**EN PROGRESO:**
- `tests/test_core.py` — MODIFICADO (82 tests, probablemente añadiendo más)
- `tests/test_discovery.py` — modificado recientemente

**ESTADO:** 80% completo. Tests de core presentes, cobertura buena.

**YA HECHO:**
- ✅ GateTest (10+)
- ✅ ProspectorTest (10+)
- ✅ QualifierTest (10+)
- ✅ OutreachTest (10+)
- ✅ CRMTest, RobustnessTest, PipelineIntegrationTest
- ✅ MemoryPersistenceTest, LifecycleTest, ReplyLoopTest
- ✅ ChannelTest, ConciergeTest, PendingOfferTest
- ✅ ScalabilityTest, AuthTest, MetaAdsTest
- ✅ PitchWriterTest, UsedEmailsTest

**FALTA:**
- ✅ Tests de edge cases en parseo (`tests/test_contracts.py` — 18 tests: from_dict defensivo, Lead.key, _as_int)
- ❌ Tests de Supabase roundtrip
- ❌ Tests de canales bajo estrés
- ❌ Tests de discovery validation
- ✅ Tests de contrato de agentes (`tests/test_agents.py` — PROSPECTOR/QUALIFIER/CONCIERGE/MEDIABUYER/OUTREACH/TRACKER/ANALYST; PITCHWRITER ya en test_core)

**RECOMENDACIÓN:** DEBUG escribe tests para validadores (cuando WORKER cree validators.py) y tests de contrato de agentes.

---

## 🎯 Prompts Estratégicos Recomendados

### URGENTE (Bloquea a otros):
1. **🔨 WORKER** — APIs para replies (GET /api/replies, GET /api/reply/{key})
   - Bloquea: DESIGN (WhatsApp.jsx)
   - Estimado: 30 min
   - Status: NO INICIADO

2. **🔨 WORKER** — Validadores.py (module nuevo con reglas por tier)
   - Bloquea: DEBUG (tests de validation)
   - Estimado: 45 min
   - Status: NO INICIADO

### IMPORTANTE (En paralelo):
3. **🤖 AGENTS** — Tests de Contrato (CONCIERGE + otros agentes)
   - Depende: AGENTS termina mejora de CONCIERGE
   - Estimado: 30 min
   - Status: ESPERANDO

4. **🎨 DESIGN** — Mejorar Agentes.jsx (navegación correcta)
   - Bloquea: Nada (independiente)
   - Estimado: 15 min
   - Status: EN PROGRESO

5. **🔨 WORKER** — Retry logic en channels.py
   - Bloquea: DEBUG (tests de stress)
   - Estimado: 45 min
   - Status: NO INICIADO

### SECUNDARIO (Después de lo anterior):
6. **🔍 DEBUG** — Tests de Edge Cases (parseo, ofertas, validación)
   - Depende: WORKER #1, #2
   - Estimado: 1 hora
   - Status: NO INICIADO

7. **🔍 DEBUG** — Tests de Supabase Roundtrip
   - Depende: Nada especial
   - Estimado: 30 min
   - Status: NO INICIADO

---

## 📋 Plan de Acción Recomendado

### Ahora (paralelo):
```
WORKER #1: APIs replies          └─→ DESIGN: completa WhatsApp.jsx
WORKER #2: Validadores.py       └─→ DEBUG: tests de validation
AGENTS: Tests de contrato        
DESIGN: Mejorar Agentes.jsx      (listo rápido)
```

### Después:
```
WORKER #3: Retry logic
DEBUG: Tests de edge cases (parseo + canales stress)
```

### Opcional (cuando todo esté robusto):
```
Gráficos de trends en Campanas.jsx
Dashboard de estado de agentes en tiempo real
Mejoras visuales avanzadas
```

---

## 📊 Métricas Actuales

- **Tests:** 82 en test_core.py (buena cobertura)
- **Agentes:** 8 funcionando (PROSPECTOR, QUALIFIER, OUTREACH, TRACKER, ANALYST, CONCIERGE, MEDIABUYER, PITCHWRITER)
- **Páginas Frontend:** 11 (Dashboard, Leads, Pipeline, Campañas, Clientes, Agentes, Llamadas, Vender, Arquitectura, Forecast, Config)
- **APIs:** ~30 endpoints
- **Clientes:** Multi-tenant en Supabase
- **Integraciones:** Anthropic, Vapi, Meta Ads, Email (SMTP), WhatsApp, Supabase

---

## 🚨 Riesgos Actuales

1. **APIs de Replies faltantes** — DESIGN no puede completar WhatsApp
2. **Validadores no existen** — datos sucios pueden entrar al CRM
3. **Retry logic débil** — fallos en envío se pierden
4. **Tests de contrato ausentes** — agentes pueden tener bugs en schema
5. **Prompts de CONCIERGE en progreso** — cambios sin mergear aún

