# CLAUDE.md — ZERO

Orientación para trabajar en este repo. Léelo antes de tocar código.

## Qué es

ZERO es un orquestador multi-agente de **generación de leads B2B**. Su misión, y la
vara con la que se decide todo:

> **Entregar a un cliente leads B2B calificados y confiables, listos para contactar.**

Cadena del pipeline: `discover → qualify → validate → outreach → follow-up → forecast`,
y cada lead queda registrado en un CRM.

## Cómo correr

```bash
# pipeline en mock (sin key, sin red) — el modo por defecto para desarrollar
python3 main.py --client acme --tier GROWTH --query "fintech LATAM"

# tests del núcleo (stdlib, sin deps)
python3 -m unittest discover -s tests -t .

# tablero CRM / detalle de un lead / animación
python3 main.py --client acme --tier GROWTH --action crm
python3 demo.py
```

Backends: mock (default) · `--local` (modelo local OpenAI-compatible, p.ej. Ollama) ·
`--live` (API Anthropic). El destino de producción es un modelo **local**.

## Mapa del código

- `main.py` — CLI, puerta de entrada.
- `zero/orchestrator.py` — **ZERO**: reparte tareas, aplica el gate, ensambla la entrega.
- `zero/agents/` — sub-agentes: PROSPECTOR, QUALIFIER, OUTREACH, TRACKER, ANALYST.
  Cada uno: una clase con `_mock_result` (offline) y el camino real vía backend.
- `zero/config.py` — **la política**: tiers, reglas del gate, cadencia, forecast. Los
  números de negocio viven aquí (p.ej. `MIN_ICP_SCORE`).
- `zero/contracts.py` — el contrato JSON (TaskPayload / AgentResponse / Lead).
- `zero/backends.py` · `zero/discovery.py` · `zero/inbox.py` — piezas **intercambiables** (LLM / fuente de
  leads / bandeja de respuestas); cada una con su versión real y su mock.
- `zero/crm.py` — registro durable de leads (etapas + historial).
- `zero/memory.py` — estado de sesión + secuencias de follow-up.
- `zero/board.py` · `zero/export.py` — presentación (Kanban) y entrega (CSV). Sin lógica.
- `tests/test_core.py` — red de seguridad del núcleo.

## Principios (no negociables)

1. **Mock-first.** Se construye y prueba contra mocks; las integraciones reales se
   enchufan después. Todo frente que toque el mundo exterior (LLM, scraping, correo, APIs)
   tiene un mock en su frontera. El mock debe ser **fiel al contrato** (misma forma de
   datos) o da falsa confianza.
2. **Política separada del mecanismo.** Las reglas de negocio están en `config.py`; la
   lógica solo las aplica. Cambiar la promesa = cambiar config, no la lógica.
3. **Presentación separada de los datos.** `board.py`/`export.py` solo dibujan/exportan; no
   deciden nada.
4. **Disciplina de alcance.** Cada feature es un pasivo (mantención/soporte). Adueñarse del
   núcleo antes de expandir. No abrir frentes nuevos sin necesidad real.
5. **Equipo de 1.** Preferir robustez y claridad del núcleo sobre features. Probar siempre
   corriendo, no suponiendo. Tests en verde antes de seguir.

## Convenciones

- Python 3, **solo stdlib** en el núcleo (la única dep opcional es `anthropic`, para `--live`).
- Tras cambiar lógica del núcleo: correr la suite de tests.
- `state.json` y `crm.json` son datos locales (en `.gitignore`); nunca sobrescribirlos a
  ciegas — si están corruptos, el código avisa en vez de borrarlos.

---

## Rol: conductor

Tu trabajo por defecto en este repo es **dirigir, no ejecutar**. Hay sub-agentes
definidos en `.claude/agents/`; úsalos.

Ante una tarea de más de un paso:

1. **Reconocimiento.** `explorador` primero. No asumas dónde vive algo — en este
   repo la política está en `config.py` y el mecanismo en otro lado, y confundirlos
   es el error más caro que puedes cometer aquí.
2. **Plan.** Escríbelo en pasos concretos y muéstralo antes de tocar archivos. Cada
   paso nombra a su sub-agente.
3. **Delegación.** Reparte. Los pasos independientes van en paralelo, en un solo
   bloque de llamadas.
4. **Cierre.** `revisor` y `verificador` corren siempre antes de dar algo por hecho.
   Nada se declara terminado sin la suite en verde.

Tú mantienes el contexto global y la coherencia entre piezas. Los sub-agentes
arrancan en frío: dales rutas exactas, decisiones ya tomadas y restricciones,
porque no ven esta conversación.

### Cuándo NO delegar

Delegar cuesta tiempo. Hazlo tú si es una pregunta que se responde leyendo uno o
dos archivos, un cambio de una línea, o algo conversacional. La regla: si
describir la tarea cuesta más que hacerla, hazla.

### Antes de confirmar con el usuario

Pregunta antes de: borrar archivos, `git push`, instalar cualquier dependencia
(rompe la regla de solo-stdlib), tocar `state.json` o `crm.json`, o mover números
de negocio fuera de `config.py`.
