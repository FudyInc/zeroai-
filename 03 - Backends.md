# Backends

El mismo prompt y el mismo [[02 - Arquitectura|contrato JSON]] corren sobre tres cerebros distintos. **Solo se intercambia el objeto backend** — los agentes no cambian. Definidos en `zero/backends.py`.

| Backend | Flag CLI | Usa LLM | Necesita key | Cuándo usarlo |
|---|---|---|---|---|
| **mock** (determinista) | _(default)_ | no | no | construir y probar el pipeline completo sin gastar; tests |
| **local** (Ollama / vLLM / TGI) | `--local` | sí | no | **destino de producción**: modelo propio, sin costo por token |
| **Anthropic API** | `--live` | sí | sí | desarrollo / máxima calidad |

## mock (por defecto)

Sintetiza leads, scores y mensajes **deterministas** a partir de fixtures. Permite ver el pipeline, el gate de lead calificado y los borradores de outreach sin tokens ni red. Es la base del enfoque **mock-first**: cada frontera con el mundo exterior tiene un mock **fiel al contrato** (misma forma de datos). La **discovery web gratis** (DuckDuckGo, sin key) corre también en mock con HTML enlatado en tests (`tests/test_discovery.py`).

## local (`--local`) — el destino de producción

Cualquier endpoint **OpenAI-compatible** sirve (Ollama, vLLM, TGI). Sin install extra (stdlib). `LocalBackend` en `zero/backends.py`.

- `--local-model` (default `qwen2.5-coder:7b`)
- `--local-url` (default `http://localhost:11434/v1`)
- El id de modelo por-agente de Anthropic **se ignora a propósito**: un solo modelo local sirve todos los roles (`self.model` manda).

```bash
python3 main.py --client acme --tier SCALE --query "fintech LATAM" --local \
  --local-model qwen2.5-coder:7b --local-url http://localhost:11434/v1
```

## Anthropic API (`--live`)

`AnthropicBackend` en `zero/backends.py`. Requiere `ANTHROPIC_API_KEY`. Modelos definidos en `zero/config.py`:

| Constante | Modelo | Uso |
|---|---|---|
| `FABLE` | `claude-fable-5` | cerebro de **ZERO** (orquestador) — `ZERO_MODEL` |
| `OPUS` | `claude-opus-4-8` | alternativa fuerte |
| `SONNET` | `claude-sonnet-4-6` | sub-agentes críticos (default de `agents/base.py`) |

```bash
export ANTHROPIC_API_KEY=sk-...
python3 main.py --client acme --tier SCALE --query "fintech LATAM" --count 10 --live
```

## Selección automática (dashboard)

En el backend web (`api.py`), `_agents_best()` elige el mejor cerebro disponible: **Anthropic** (si hay `ANTHROPIC_API_KEY`) → **local** (si hay `LOCAL_MODEL`) → **mock**. Si el modelo "live" falla o devuelve vacío, **cae a mock** para que el agente siempre responda. Ver [[09 - Otros]].

> [!note]
> Coste cero por ahora: la integración Anthropic (de pago) está pospuesta; el sistema corre en mock/local. Ver [[06 - Roadmap]].
