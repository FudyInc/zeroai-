# Index

Mapa del vault de **ZeroAI (ZERO)** — orquestador multi-agente de generación de leads B2B. Fuente de verdad: el código en `zero/`, los prompts en `prompts/` y el `README.md`.

> **Vara con la que se decide todo:** entregar a un cliente **leads B2B calificados y confiables, listos para contactar**.

## Notas

- [[01 - Vision]] — qué es, misión y propuesta de valor.
- [[02 - Arquitectura]] — el pipeline, los agentes y el orquestador ZERO (con diagrama Mermaid).
- [[03 - Backends]] — los 3 cerebros: mock · local (Ollama/vLLM) · Anthropic API.
- [[04 - CRM y Pipeline de Ventas]] — etapas del CRM, el gate de lead calificado, Kanban / CSV / dashboard.
- [[05 - Modelo de Negocio]] — tiers (STARTER · GROWTH · SCALE · ENTERPRISE), precios CLP y MRR.
- [[06 - Roadmap]] — estado actual y próximos pasos (checklist).
- [[07 - CLI y Comandos]] — flags y ejemplos de uso.
- [[08 - Glosario]] — términos clave en una línea.
- [[09 - Otros]] — módulos, integraciones y decisiones que no encajan arriba (canales, voz, Meta Ads, Supabase, hosting local, etc.).

## Mapa rápido del repo

| Carpeta / archivo | Qué es |
|---|---|
| `prompts/` | system prompts (ZERO + cada sub-agente) — el contrato hacia el modelo |
| `zero/config.py` | **política**: modelos, tiers, reglas del gate, cadencia, forecast |
| `zero/contracts.py` | el contrato JSON (`TaskPayload` / `AgentResponse` / `Lead`) |
| `zero/orchestrator.py` | **ZERO**: reparte tareas, aplica el gate, ensambla la entrega |
| `zero/agents/` | sub-agentes (mock + camino real por backend) |
| `zero/backends.py` | `AnthropicBackend` · `LocalBackend` · extracción de JSON |
| `zero/crm.py` | registro durable de leads (etapas + historial) |
| `main.py` | entrada por CLI |
| `api.py` | backend web (FastAPI) del dashboard |
| `frontend/` | dashboard React/Vite |
| `demo.py` | recorrido animado del pipeline en terminal |

> [!note]
> El `README.md` menciona `webapp.py` (dashboard stdlib); el código actual usa **`api.py` (FastAPI) + `frontend/` (React/Vite)**. Ver [[09 - Otros]].
