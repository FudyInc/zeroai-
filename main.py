#!/usr/bin/env python3
"""ZERO CLI — run a lead-gen pipeline for one client.

Mock by default (no key / no deps). Use --live to call the Anthropic API.

    python main.py --client acme --tier GROWTH --query "agencias de marketing en Santiago"
    python main.py --client acme --tier SCALE --query "fintech LATAM" --count 10 --live
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from zero._env import load_env
from zero.agents import build_agents
from zero.config import TIERS
from zero.memory import SessionMemory
from zero.orchestrator import Zero

load_env()   # load secrets from .env if present


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ZERO — B2B lead-gen orchestrator")
    p.add_argument("--client", required=True, help="client_id")
    p.add_argument("--tier", required=True, choices=list(TIERS), help="client tier")
    p.add_argument("--action", choices=["pipeline", "followups", "forecast", "crm"], default="pipeline",
                   help="pipeline · followups · forecast · crm (lead board)")
    p.add_argument("--crm", default="crm.json", help="CRM lead store (JSON)")
    p.add_argument("--move", default=None,
                   help='mover un lead de etapa: "clave=etapa" (con --action crm)')
    p.add_argument("--lead", default=None,
                   help="ver el detalle e historial de un lead por su clave (con --action crm)")
    p.add_argument("--query", help="discovery intent / target description (required for pipeline)")
    p.add_argument("--as-of", dest="as_of", default=None,
                   help="ISO datetime to treat as 'now' for due follow-ups (--action followups)")
    p.add_argument("--count", type=int, default=8, help="leads to attempt this run (tier-capped)")
    p.add_argument("--discover", choices=["none", "web"], default="none",
                   help="none = mock/LLM leads · web = real DuckDuckGo discovery (no key)")
    p.add_argument("--no-enrich", action="store_true",
                   help="skip decision-maker lookup in web discovery (faster, fewer fetches)")
    p.add_argument("--exclude", default="", help="comma-separated excluded domains")
    p.add_argument("--no-outreach", action="store_true", help="skip first-touch messaging")
    p.add_argument("--live", action="store_true", help="use the Anthropic API instead of mock")
    p.add_argument("--local", action="store_true",
                   help="use a local OpenAI-compatible model (Ollama/vLLM) — no key, no tokens")
    p.add_argument("--local-model", default="qwen2.5-coder:7b", help="local model name (--local)")
    p.add_argument("--local-url", default="http://localhost:11434/v1",
                   help="local OpenAI-compatible base URL (--local)")
    p.add_argument("--state", default="state.json", help="session-memory file")
    p.add_argument("--export", default=None, help="write the deliverable (qualified leads) to a CSV path")
    p.add_argument("--json", action="store_true", help="print raw deliverable JSON")
    args = p.parse_args(argv)

    if args.live and args.local:
        print("ERROR: choose one of --live or --local, not both.", file=sys.stderr)
        return 2
    if args.action == "pipeline" and not args.query:
        print("ERROR: --query is required for --action pipeline.", file=sys.stderr)
        return 2

    backend = None
    mock = not (args.live or args.local)
    if args.live:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            print("ERROR: --live needs ANTHROPIC_API_KEY in the environment.", file=sys.stderr)
            return 2
        try:
            from zero.backends import AnthropicBackend
            backend = AnthropicBackend(api_key=key)
        except ImportError:
            print("ERROR: --live needs `pip install anthropic`.", file=sys.stderr)
            return 2
    elif args.local:
        from zero.backends import LocalBackend
        backend = LocalBackend(model=args.local_model, base_url=args.local_url)

    source = None
    if args.discover == "web":
        from zero.discovery import DuckDuckGoSource
        source = DuckDuckGoSource(enrich=not args.no_enrich)

    from zero.crm import CRM
    try:
        crm = CRM(args.crm)
        memory = SessionMemory(args.state)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    memory.register_client(args.client, args.tier)
    zero = Zero(build_agents(backend=backend, mock=mock, source=source), memory=memory, crm=crm)

    if args.action == "crm":
        return _run_crm(crm, args)

    if args.action == "followups":
        result = zero.run_followups(args.client, as_of=args.as_of)
        printer = _print_followups
    elif args.action == "forecast":
        result = zero.forecast(args.client)
        printer = _print_forecast
    else:
        result = zero.run_pipeline(
            client_id=args.client,
            tier=args.tier,
            query=args.query,
            count=args.count,
            exclusions=[d.strip() for d in args.exclude.split(",") if d.strip()],
            write_outreach=not args.no_outreach,
        )
        if args.export and not result.get("error"):
            from zero.export import deliverable_to_csv
            n = deliverable_to_csv(result, args.export)
            print(f"✓ {n} leads exportados a {args.export}")
        printer = lambda d: _print_report(d, mock)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        printer(result)
    return 0


def _run_crm(crm, args) -> int:
    if args.move:
        key, _, stage = args.move.partition("=")
        key, stage = key.strip().lower(), stage.strip()
        try:
            rec = crm.set_stage(args.client, key, stage, detail="manual")
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 2
        if rec is None:
            print(f"No encontré el lead '{key}' para {args.client}. "
                  f"Revisá la clave en el tablero (key: ...).", file=sys.stderr)
            return 2
        crm.save()
        print(f"✓ {key} → {stage}")

    if args.lead:
        from zero.board import render_lead
        print(render_lead(crm, args.client, args.lead.strip().lower(), color=sys.stdout.isatty()))
        return 0

    if args.export:
        from zero.export import crm_to_csv
        n = crm_to_csv(crm, args.client, args.export)
        print(f"✓ {n} leads del CRM exportados a {args.export}")
        return 0

    if args.json:
        print(json.dumps(crm.board(args.client), ensure_ascii=False, indent=2))
    else:
        _print_crm_board(crm, args.client)
    return 0


def _print_crm_board(crm, client: str) -> None:
    from zero.board import render
    print(render(crm, client, color=sys.stdout.isatty()))


def _print_followups(d: dict) -> None:
    if d.get("error"):
        print(f"✗ Follow-ups fallaron en '{d['error']}': {d.get('notes')}")
        return
    msgs = d.get("followups", [])
    print(f"\n=== ZERO · TRACKER · seguimientos para {d['client_id']} ===")
    if not msgs:
        print(d.get("notes", "no hay seguimientos pendientes"))
        return
    print(f"Avanzadas {d['advanced']} secuencias · abiertas restantes: {d.get('open_remaining', 0)}\n")
    for m in msgs:
        head = f"[{m['channel']}] {m['company']} · paso {m.get('step')} ({m.get('kind')})"
        if m.get("subject"):
            head += f" · {m['subject']}"
        print(f"  {head}\n    {m['body']}")
    print()


def _print_forecast(d: dict) -> None:
    if d.get("error"):
        print(f"✗ Forecast falló en '{d['error']}': {d.get('notes')}")
        return
    f = d.get("forecast", {})
    inp, asm, proj = f.get("inputs", {}), f.get("assumptions", {}), f.get("projection", {})
    print(f"\n=== ZERO · ANALYST · forecast para {d['client_id']} ===")
    print(f"Funnel: descubiertos {inp.get('discovered')} → calificados {inp.get('qualified')} "
          f"→ contactados {inp.get('contacted')} (secuencias abiertas {inp.get('open_sequences')})")
    print(f"Tasas: reply {asm.get('reply_rate')} · meeting {asm.get('meeting_rate')} "
          f"· win {asm.get('win_rate')} · deal ${asm.get('avg_deal_value_usd')}")
    print(f"Proyección: ~{proj.get('expected_replies')} respuestas → "
          f"~{proj.get('expected_meetings')} reuniones → "
          f"~{proj.get('expected_wins')} cierres → "
          f"${proj.get('expected_pipeline_usd')} pipeline")
    if f.get("commentary"):
        print(f"  ANALYST: {f['commentary']}")
    print()


def _print_report(d: dict, mock: bool) -> None:
    if d.get("error"):
        print(f"✗ Pipeline falló en '{d['error']}': {d.get('notes')}")
        return
    s = d["summary"]
    mode = "MOCK" if mock else "LIVE"
    print(f"\n=== ZERO · entrega para {d['client_id']} ({d['tier']}) · {mode} ===")
    print(f"Query: {d['query']}")
    print(f"Scoring: {s['scoring_model']} | Canales: {', '.join(s['channels'])}")
    print(f"Descubiertos {s['discovered']} → calificados {s['qualified']} "
          f"(rechazados {s['rejected']})\n")

    for i, ld in enumerate(d["qualified_leads"], 1):
        contact = ld.get("email") or ld.get("phone") or "—"
        print(f"{i:>2}. [{ld['score']}] {ld['company']} · {ld['role']}")
        print(f"     {contact}  ·  canal: {ld['channel']}")
        if ld.get("icp_reasons"):
            print(f"     {' | '.join(ld['icp_reasons'])}")

    if d.get("outreach"):
        print(f"\n--- Outreach (primer toque, {len(d['outreach'])} msgs) ---")
        for m in d["outreach"][:3]:
            head = f"[{m['channel']}] {m['company']}"
            if m.get("subject"):
                head += f" · {m['subject']}"
            print(f"  {head}\n    {m['body']}")
        if len(d["outreach"]) > 3:
            print(f"  ... (+{len(d['outreach']) - 3} más)")

    if d.get("rejected"):
        print(f"\n--- Rechazados ({len(d['rejected'])}) ---")
        for r in d["rejected"]:
            print(f"  {r['company']} [{r['score']}]: {', '.join(r['reasons'])}")
    print()


if __name__ == "__main__":
    raise SystemExit(main())
