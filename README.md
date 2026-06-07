# ZERO — Multi-Agent B2B Lead Generation

ZERO is the orchestrator brain (Claude Opus 4.8) of a multi-agent lead-gen pipeline.
It composes JSON tasks, dispatches them to specialized sub-agents, validates the
output against a strict qualified-lead bar, logs every state change, and assembles
the client deliverable.

```
discover → enrich → qualify → validate → outreach → report
```

## Why it runs anywhere

Every agent speaks the **same JSON contract** regardless of backend. The production
target is a **local model** (Qwen/Llama) on your own box via `--local` — no key, no
per-token cost; the Anthropic API (`--live`) is the dev / highest-quality path. Both,
plus mock, share the exact prompts and contract: **only the backend object swaps**.

| Backend | Flag | Uses an LLM | Needs a key |
|---|---|---|---|
| mock (deterministic) | _(default)_ | no | no |
| local (Ollama / vLLM / TGI) | `--local` | yes | no |
| Anthropic API | `--live` | yes | yes |

## Quick start (mock — no key, no deps)

```bash
cd zero
python3 main.py --client acme --tier GROWTH --query "agencias de marketing en Santiago"
```

Mock mode synthesizes deterministic leads/scores so you can see the full pipeline,
the qualified-lead filter, and outreach drafts without spending tokens.

## Live mode (Anthropic API)

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...
python3 main.py --client acme --tier SCALE --query "fintech LATAM" --count 10 --live
```

## Local mode (Ollama / vLLM — no key, no tokens)

Any OpenAI-compatible endpoint works; no extra install (stdlib only).

```bash
# e.g. Ollama on localhost
python3 main.py --client acme --tier SCALE --query "fintech LATAM" --local \
  --local-model qwen2.5-coder:7b --local-url http://localhost:11434/v1
```

## Web dashboard (local, to show the product)

A landing + CRM board in the browser, reading the same `crm.json`. Stdlib only,
runs locally (deploy later if it earns its keep). It only *displays* what the
pipeline already produced.

```bash
python3 main.py --client demo --tier GROWTH --query "fintech LATAM"   # produce some data
python3 webapp.py                                                     # http://localhost:8000
```

## Real discovery (no key)

By default PROSPECTOR uses mock/LLM leads. `--discover web` swaps in a real
DuckDuckGo search + page fetch + contact extraction (stdlib only, no key):

```bash
python3 main.py --client acme --tier GROWTH --discover web \
  --query "agencias de marketing digital en Santiago de Chile" --count 5
```

The source is swappable (`zero/discovery.py`, `DiscoverySource`): a keyed
provider (Brave/SerpAPI) drops in later with the same signature, no PROSPECTOR
change. Real candidates often arrive without a verified contact or a named role
(`role: "por verificar"`) — exactly what the qualified-lead gate is there to filter.

**Decision-maker enrichment** is on by default: ZERO reads each company's
about/team pages and extracts the `Name — Role` of the decision-maker when the
site exposes it. It's *precision-first* — it fills a role only on hard evidence,
leaving `"por verificar"` otherwise (a wrong name is worse than none). Disable it
for speed with `--no-enrich`. Coverage on heterogeneous SME sites is partial;
a keyed data provider is the path to high-coverage enrichment.

## Actions beyond discovery

```bash
# advance due follow-up sequences (TRACKER). --as-of simulates time passing.
python3 main.py --client acme --tier SCALE --action followups --as-of 2026-06-08T12:00:00

# project pipeline from logged activity (ANALYST)
python3 main.py --client acme --tier SCALE --action forecast
```

## CRM — the lead system of record

Every pipeline run populates a durable CRM (`crm.json`): one record per lead with
its funnel **stage** and full interaction **history**. The pipeline advances stages
automatically (`new → qualified/disqualified → contacted → nurturing`); you move the
later ones by hand as you learn what happened.

```bash
# the lead board — a colour Kanban, columns by stage (zero/board.py)
python3 main.py --client acme --tier GROWTH --action crm

# move a lead along the funnel (key shown in the board)
python3 main.py --client acme --tier GROWTH --action crm --move "valentina@maraustral.cl=won"

# one lead's full story — fields + timeline of everything that happened
python3 main.py --client acme --tier GROWTH --action crm --lead "valentina@maraustral.cl"

# export the whole CRM book (every lead + stage) to CSV
python3 main.py --client acme --tier GROWTH --action crm --export libro.csv
```

Stages: `new · qualified · disqualified · contacted · nurturing · replied · meeting ·
won · lost`. Automatic transitions are **forward-only** — re-running the pipeline never
drags a closed lead backwards.

## CLI

| Flag | Meaning |
|---|---|
| `--client` | client_id (required) |
| `--tier` | STARTER · GROWTH · SCALE · ENTERPRISE (required) |
| `--query` | discovery intent (required) |
| `--count` | leads to attempt (capped by the tier's monthly limit) |
| `--discover` | `none` (mock/LLM, default) · `web` (real DuckDuckGo, no key) |
| `--no-enrich` | skip decision-maker lookup in web discovery (faster) |
| `--exclude` | comma-separated excluded domains |
| `--action` | `pipeline` (default) · `followups` · `forecast` · `crm` |
| `--move` | move a lead's stage: `"key=stage"` (with `--action crm`) |
| `--as-of` | ISO datetime treated as "now" for due follow-ups |
| `--no-outreach` | skip first-touch messaging |
| `--live` | call the Anthropic API instead of mock |
| `--local` | use a local OpenAI-compatible model (`--local-model`, `--local-url`) |
| `--state` | session-memory JSON file (default `state.json`) |
| `--export` | write the deliverable (qualified leads + outreach) to a CSV |
| `--json` | print the raw deliverable JSON |

## Layout

```
prompts/            system prompts (ZERO + each sub-agent) — the model-facing contract
  system_zero.md    the orchestrator brain
  prospector.md  qualifier.md  outreach.md  tracker.md  analyst.md
zero/
  config.py         models, tiers, qualified-lead rules, cadence + forecast policy
  contracts.py      TaskPayload / AgentResponse / Lead — the JSON interface
  backends.py       AnthropicBackend · LocalBackend (OpenAI-compatible) · JSON extraction
  discovery.py      DiscoverySource · DuckDuckGoSource (real, no-key web discovery)
  crm.py            CRM lead store — stages + interaction history (crm.json)
  board.py          Kanban rendering of the CRM (presentation only)
  export.py         deliverable → CSV (what the client receives)
  memory.py         session memory, follow-up sequences, persistence, handoff
  orchestrator.py   ZERO: dispatch, validate, log, follow-ups, forecast, deliverable
  agents/
    base.py         shared run loop (mock vs live)
    prospector.py  qualifier.py  outreach.py  tracker.py  analyst.py
main.py             CLI entry point
webapp.py           local web dashboard + landing (reads crm.json, stdlib http)
demo.py             animated terminal walkthrough of the pipeline
```

## Tests

A stdlib safety net over the core logic (gate, discovery delivery, scoring, CRM
stages, full pipeline) — no deps, all in mock:

```bash
python3 -m unittest discover -s tests -t .
```

## Qualified lead — the gate

A lead is delivered only if **all** hold (see `zero/config.py`):

- verified contact (email or phone)
- ICP score ≥ 70
- not on the client's exclusion list
- has company, role, channel
- not contacted in the last 90 days

## Status

All five agents are real on every backend (mock · local · live):
**ZERO** orchestrates; **PROSPECTOR** discovers; **QUALIFIER** scores;
**OUTREACH** writes the first touch; **TRACKER** runs the follow-up cadence
(nudge → value → break-up); **ANALYST** forecasts pipeline from logged activity.
Every lead lands in the **CRM** with its stage and full history.

Real web discovery (`--discover web`) and decision-maker enrichment are live, no
key. Next: a keyed discovery/enrichment provider for high coverage, and reply
detection to auto-close follow-up sequences on response.
```
