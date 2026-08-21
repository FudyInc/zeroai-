# CLI y Comandos

Entrada por `main.py`. El modo por defecto es **mock** (sin key, sin red). Tiers válidos en [[05 - Modelo de Negocio]]; backends en [[03 - Backends]].

## Flags

| Flag | Significado |
|---|---|
| `--client` | client_id (requerido) |
| `--tier` | STARTER · GROWTH · SCALE · ENTERPRISE (requerido) |
| `--query` | intención de descubrimiento (requerido para `pipeline`) |
| `--count` | leads a intentar esta corrida (capado por el límite del tier; default 8) |
| `--discover` | `none` (mock/LLM, default) · `web` (DuckDuckGo real, sin key) |
| `--no-enrich` | saltar la búsqueda de decision-maker en discovery web (más rápido) |
| `--exclude` | dominios excluidos, separados por coma |
| `--action` | `pipeline` (default) · `followups` · `forecast` · `crm` · `replies` |
| `--move` | mover etapa de un lead: `"key=stage"` (con `--action crm`) |
| `--lead` | ver la ficha + timeline de un lead (con `--action crm`) |
| `--as-of` | datetime ISO tratado como "ahora" para follow-ups vencidos |
| `--no-outreach` | saltar el primer mensaje |
| `--inbox` | ruta del archivo inbox (default `inbox.json`). Simula respuestas escribiendo un mensaje JSON ahí. |
| `--live` | usar la API de Anthropic en vez de mock |
| `--local` | usar un modelo local OpenAI-compatible (`--local-model`, `--local-url`) |
| `--local-model` | nombre del modelo local (default `qwen2.5-coder:7b`) |
| `--local-url` | endpoint local (default `http://localhost:11434/v1`) |
| `--state` | archivo de memoria de sesión (default `state.json`) |
| `--export` | escribe el entregable (leads calificados) a un CSV |
| `--json` | imprime el JSON crudo del entregable |
| `--crm` | archivo del CRM (default `crm.json`) |

## Ejemplos

```bash
# pipeline en mock (modo por defecto para desarrollar)
python3 main.py --client acme --tier GROWTH --query "agencias de marketing en Santiago"

# discovery web real (sin key) + enriquecimiento
python3 main.py --client acme --tier GROWTH --discover web \
  --query "agencias de marketing digital en Santiago de Chile" --count 5

# live (Anthropic)
export ANTHROPIC_API_KEY=sk-...
python3 main.py --client acme --tier SCALE --query "fintech LATAM" --count 10 --live

# local (Ollama / vLLM, sin key ni tokens)
python3 main.py --client acme --tier SCALE --query "fintech LATAM" --local \
  --local-model qwen2.5-coder:7b --local-url http://localhost:11434/v1
```

### Acciones más allá del pipeline

```bash
# avanzar secuencias de follow-up vencidas (TRACKER); --as-of simula el paso del tiempo
python3 main.py --client acme --tier SCALE --action followups --as-of 2026-06-08T12:00:00

# proyectar pipeline desde la actividad registrada (ANALYST)
python3 main.py --client acme --tier SCALE --action forecast

# revisar bandeja de respuestas y cerrar secuencias de seguimiento automáticamente
python3 main.py --client acme --tier GROWTH --action replies
```

#### Simular respuestas (inbox local)

Crear un archivo `inbox.json` con respuestas entrantes (simula que un lead contesta):

```json
[
  {
    "channel": "email",
    "from": "juan@empresa.cl",
    "subject": "Re: Tu mensaje",
    "body": "Hola, me interesa conocer más.",
    "received_at": "2026-06-10T14:30:00Z"
  }
]
```

Luego ejecutar:

```bash
python3 main.py --client acme --tier GROWTH --action replies --inbox inbox.json
```

El orquestador hace match con el lead, registra la respuesta, cierra la secuencia de follow-up
y mueve el lead a etapa `replied` en el CRM. El CONCIERGE redacta una respuesta automática.

### CRM (ver [[04 - CRM y Pipeline de Ventas]])

```bash
python3 main.py --client acme --tier GROWTH --action crm                              # Kanban
python3 main.py --client acme --tier GROWTH --action crm --move "valentina@maraustral.cl=won"
python3 main.py --client acme --tier GROWTH --action crm --lead "valentina@maraustral.cl"
python3 main.py --client acme --tier GROWTH --action crm --export libro.csv
```

### Tests y demo

```bash
python3 -m unittest discover -s tests -t .   # red de seguridad del núcleo (stdlib, mock)
python3 demo.py                              # recorrido animado en terminal
```

### Dashboard local

Backend, túnel y dashboard corren como **servicios** y arrancan solos con el
sistema. No hay que levantar nada a mano: entra a http://localhost:5173.

```bash
./start.sh          # revisa que los 3 servicios estén arriba y muestra las URLs
./start.sh --dev    # instancia aparte (:8801 + :5174) para probar sin tocar los servicios

# manejo de los servicios
sudo systemctl status zero-backend zero-tunnel   # backend + túnel (sistema)
systemctl --user status zero-dashboard           # dashboard (usuario, por el node de nvm)
journalctl --user -u zero-dashboard -n 50        # logs del dashboard
```

> [!note]
> El `README.md` muestra `python3 webapp.py` para el dashboard; el actual es `api.py` (FastAPI) + `frontend/` (React/Vite), envuelto por `start.sh`. Ver [[09 - Otros]].
