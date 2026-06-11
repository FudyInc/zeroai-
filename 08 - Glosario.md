# Glosario

Términos clave de ZeroAI, una línea cada uno. Ver también [[02 - Arquitectura]] y [[04 - CRM y Pipeline de Ventas]].

| Término | Definición |
|---|---|
| **ZERO** | El orquestador: reparte tareas a sub-agentes, aplica el gate y ensambla la entrega. |
| **Sub-agente** | Especialista (PROSPECTOR, QUALIFIER, OUTREACH, TRACKER, ANALYST…) que recibe una `TaskPayload` y responde una `AgentResponse`. |
| **Contrato JSON** | Las dataclasses `TaskPayload` / `AgentResponse` / `Lead` (`zero/contracts.py`) que todo agente habla, sin importar el backend. |
| **Backend** | El cerebro que ejecuta al agente: mock · local (Ollama/vLLM) · Anthropic. Ver [[03 - Backends]]. |
| **Mock-first** | Construir y probar contra mocks fieles al contrato; enchufar lo real después en su frontera. |
| **ICP** | *Ideal Customer Profile* — el perfil de cliente ideal del cliente contra el que se califica un lead. |
| **ICP score** | Puntaje 0–100 que asigna QUALIFIER; **≥ 70** (`MIN_ICP_SCORE`) para ser entregable. |
| **Lead calificado** | Lead que pasa **todo** el gate (contacto verificado, score ≥ 70, no excluido, tiene company/role/channel, no contactado en 90 días). |
| **Gate** | El filtro de lead calificado que aplica ZERO antes de entregar. |
| **Enrichment** | Enriquecer un lead leyendo about/team del sitio para extraer el `Nombre — Rol` del decision-maker. |
| **`por verificar`** | Valor de `role` cuando no hay evidencia dura del cargo (precision-first: un nombre errado es peor que ninguno). |
| **Etapa (stage)** | Posición del lead en el funnel del CRM (`new → … → won/lost`). |
| **Forward-only** | Las transiciones automáticas nunca arrastran un lead cerrado hacia atrás. |
| **Follow-up cadence** | Secuencia de seguimiento de TRACKER: día 3 nudge → día 7 value → día 14 breakup. |
| **Forecast** | Proyección determinista del pipeline (`project_funnel`) con tasas que ANALYST propone. |
| **Tier** | Plan del cliente (STARTER/GROWTH/SCALE/ENTERPRISE): define leads/mes, scoring y canales. Ver [[05 - Modelo de Negocio]]. |
| **MRR** | *Monthly Recurring Revenue* — suma de los `price_clp` de los clientes con plan activo. |
| **Deliverable / entregable** | El paquete final de leads calificados + outreach que recibe el cliente (CSV / dashboard). |
| **Outbox** | Capa de envío (`zero/channels.py`): mock por defecto; `OUTBOX_LIVE=1` para enviar de verdad. Ver [[09 - Otros]]. |
| **CONCIERGE** | Agente conversacional que redacta la respuesta cuando un lead contesta. |
| **MEDIABUYER** | Agente que gestiona campañas Meta Ads (CPL vs objetivo) con Claude. |
| **PITCHWRITER** | Agente que redacta el pitch de venta, creativo y distinto cada vez. |
