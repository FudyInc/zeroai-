# CLAUDE.md — ZERO

Orientación para trabajar en este repo. Léelo antes de tocar código.

## Qué es

ZeroAI (ZERO) vende **agentes de WhatsApp plug-and-play para pymes**: el negocio que
contratamos tiene su agente respondiendo, cotizando y derivando a una persona lo antes
posible. Su misión, y la vara con la que se decide todo:

> **Que un negocio nuevo tenga su agente de WhatsApp respondiendo bien en horas, no días.**

Decisión de Diego, 2026-11-27. Después del agente de WhatsApp vienen, en ese orden, el
contenido de marketing por empresa (campañas, reels, videos) y los agentes de llamada.
Los leads pasan a ser un **extra del paquete** (más B2C que B2B: clientes para el negocio
del cliente). El pipeline histórico de leads (`discover → qualify → validate → outreach →
follow-up → forecast`, con CRM) sigue en el código y no se borra, pero ya no es el centro.

## Cómo correr

```bash
# pipeline con el motor local (Ollama) — como corre en producción
python3 main.py --client acme --tier GROWTH --query "fintech LATAM" --local

# pipeline en mock — SOLO para desarrollo sin red. El cliente `acme` es el demo:
# revisar-salud.py lo excluye de su detector justo por esto.
python3 main.py --client acme --tier GROWTH --query "fintech LATAM"

# tests del núcleo (stdlib, sin deps)
python3 -m unittest discover -s tests -t .

# tablero CRM / detalle de un lead / animación
python3 main.py --client acme --tier GROWTH --action crm
python3 demo.py
```

Backends del CLI: `--local` (modelo local OpenAI-compatible, p.ej. Ollama) · `--live`
(API Anthropic) · mock si no se pide ninguno.

**Motores en producción (2026-11-27):** WhatsApp responde con Claude — el agente de PoolEdge
usa **Opus 5.5** directo (`LOSETASCHILE_AGENT`, decisión de Diego: "Sonnet no es lo
suficientemente poderoso para negocios"); el agente general usa `WHATSAPP_ENGINE` (Sonnet 5.5
con Groq de respaldo). Ollama está apagado desde el 2026-11-08.

**El backend HTTP (`api.py`) no tiene esa tercera opción**: sin `LOCAL_MODEL` ni
`ANTHROPIC_API_KEY` responde 503. El `mock` por defecto del CLI es una comodidad de
desarrollo y no llega al producto — ver el principio 1.

## Mapa del código

- `main.py` — CLI, puerta de entrada.
- `zero/orchestrator.py` — **ZERO**: reparte tareas, aplica el gate, ensambla la entrega;
  `converse_result`/`handle_inbound` son el motor del agente de WhatsApp.
- `zero/losetas_*.py`, `zero/pool_border.py` — agente a medida de PoolEdge (cliente
  `losetaschile`). Lo que es dato del negocio debe migrar a la puerta única de datos.
- `zero/onboarding.py` — importación de catálogo y FAQ por archivo (CSV/XLSX) por empresa.
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

1. **Operación real. El mock construyó esto y ya no lo opera.**

   Hasta el 2026-09-08 el principio era *mock-first*: construir contra mocks y enchufar
   lo real después. Cumplió su trabajo — el producto existe. Desde esa fecha ZERO opera
   con motor real (Ollama local, `qwen2.5:14b`), y **el mock no corre en producción**.

   Sin motor real, la respuesta es **503 con el motivo**, no una plantilla. La regla que
   manda es: *nunca presentar como real algo que no lo es* (ver `api.py::_agent_op`). Una
   respuesta de plantilla tras un fallo del motor no es tolerancia a fallos: es una falla
   disimulada, y disimularla es lo que hizo que ocho días de ciclo muerto pasaran
   inadvertidos con la suite en verde.

   Si algo no funciona, **se pule al tiro**. No se tapa con un mock.

   Dos lugares donde el mock sigue siendo legítimo, y solo dos:
   - **La suite.** `tests/` levanta el pipeline sin red. La escotilla es
     `ZERO_PIPELINE_MOCK_OK=1` —solo el valor exacto `"1"`— y **no va en `.env`, ni en
     `start.sh`, ni en las units de systemd**. Si aparece ahí, `revisar-salud.py` lo
     detecta y avisa.
   - **La frontera de lo que cuesta plata o no existe todavía** (Meta Ads, Vapi,
     ElevenLabs — ver `[[zero-cost-policy]]`). Ahí el mock no se hace pasar por real:
     la pantalla muestra vacío con el motivo.

   El mock debe seguir siendo **fiel al contrato** (misma forma de datos) o da falsa
   confianza.

   **Cómo se detecta que esto se rompió:** `scripts/revisar-salud.py` corre cada 30 min,
   lee la telemetría y avisa por WhatsApp si algún agente de un cliente real respondió
   con motor `mock`. Mira el resultado, no la intención: da igual por qué puerta se coló.
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
