#!/usr/bin/env python3
"""Animated terminal demo of ZERO's multi-agent pipeline.

Runs a real (mock-backend) pipeline in memory, then animates ZERO dispatching to
each sub-agent — spinner while the agent "thinks", JSON flowing back, the funnel
filtering down to qualified leads, outreach typing out, and a forecast.

    python3 demo.py            # full animation
    python3 demo.py --fast     # quick, short pauses
    python3 demo.py --no-anim  # plain static frames (no cursor tricks / no TTY)

No dependencies. Honors a non-TTY stdout by falling back to static output.
"""
from __future__ import annotations

import argparse
import itertools
import sys
import time

from zero.agents import build_agents
from zero.memory import SessionMemory
from zero.orchestrator import Zero

# --- ANSI ---------------------------------------------------------------------
C = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "green": "\033[92m", "cyan": "\033[96m", "yellow": "\033[93m",
    "magenta": "\033[95m", "violet": "\033[94m", "red": "\033[91m",
    "grey": "\033[90m", "white": "\033[97m",
}
AGENT_COLOR = {
    "PROSPECTOR": "green", "QUALIFIER": "cyan", "OUTREACH": "yellow",
    "TRACKER": "magenta", "ANALYST": "violet",
}
SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class UI:
    def __init__(self, anim: bool, speed: float, force: bool = False):
        # Animate when asked and either it's a real TTY or the user forced it.
        self.anim = anim and (force or sys.stdout.isatty())
        self.speed = speed

    def c(self, s: str, color: str) -> str:
        return f"{C[color]}{s}{C['reset']}" if self.anim else s

    def sleep(self, base: float) -> None:
        if self.anim:
            time.sleep(base * self.speed)

    def line(self, s: str = "") -> None:
        print(s)

    def dispatch(self, agent: str, verb: str, result: str) -> None:
        """ZERO → AGENT with a spinner, then a green check + result."""
        col = AGENT_COLOR.get(agent, "white")
        tag = self.c(f"ZERO", "violet") + self.c(" → ", "grey") + self.c(f"{agent:<10}", col)
        label = self.c(verb, "white")
        if not self.anim:
            print(f"  {tag} {label}  {self.c('✓', 'green')} {self.c(result, 'grey')}")
            return
        frames = int(14 * self.speed) + 6
        for i in range(frames):
            sp = self.c(SPIN[i % len(SPIN)], col)
            sys.stdout.write(f"\r  {tag} {label}  {sp} {C['grey']}{verb.lower()}…{C['reset']}\033[K")
            sys.stdout.flush()
            time.sleep(0.06)
        sys.stdout.write(f"\r  {tag} {label}  {C['green']}✓{C['reset']} {C['grey']}{result}{C['reset']}\033[K\n")
        sys.stdout.flush()

    def typewriter(self, prefix: str, body: str) -> None:
        if not self.anim:
            print(f"      {prefix} {body}")
            return
        sys.stdout.write(f"      {prefix} ")
        for ch in body:
            sys.stdout.write(ch)
            sys.stdout.flush()
            time.sleep(0.004 * self.speed)
        sys.stdout.write("\n")


def funnel_bar(ui: UI, label: str, n: int, total: int, color: str) -> None:
    width = 30
    filled = int(width * (n / total)) if total else 0
    bar = "█" * filled + ui.c("·" * (width - filled), "grey")
    print(f"   {label:<12} {ui.c(bar, color)} {ui.c(str(n), color)}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ZERO animated pipeline demo")
    p.add_argument("--fast", action="store_true", help="short pauses")
    p.add_argument("--anim", action="store_true",
                   help="force the animation even if a TTY isn't detected (VS Code Run button, etc.)")
    p.add_argument("--no-anim", action="store_true", help="static output, no cursor tricks")
    p.add_argument("--client", default="demo")
    p.add_argument("--tier", default="SCALE")
    p.add_argument("--query", default="fintech B2B en LATAM")
    args = p.parse_args(argv)

    ui = UI(anim=not args.no_anim, speed=0.45 if args.fast else 1.0, force=args.anim)

    # If the user wanted animation but we fell back to static, say why.
    if not args.no_anim and not ui.anim:
        print(f"\n{C['yellow']}· Salida estática: no se detectó terminal interactiva.{C['reset']}")
        print(f"{C['grey']}  Para ver la animación, corré en la TERMINAL integrada (no el botón ▶):{C['reset']}")
        print(f"{C['grey']}    python3 demo.py --anim{C['reset']}\n")

    # Run a real pipeline (mock backend) in memory to animate over real output.
    mem = SessionMemory(None)
    zero = Zero(build_agents(mock=True), memory=mem)
    d = zero.run_pipeline(args.client, args.tier, args.query, count=8)
    s = d["summary"]

    ui.line()
    ui.line(ui.c("  ╭───────────────────────────────────────────────╮", "violet"))
    ui.line(ui.c("  │  ", "violet") + ui.c("ZERO", "bold") + ui.c("  ·  orquestador multi-agente de lead-gen   ", "white") + ui.c("│", "violet"))
    ui.line(ui.c("  ╰───────────────────────────────────────────────╯", "violet"))
    ui.line(f"   {ui.c('cliente', 'grey')} {d['client_id']}   {ui.c('tier', 'grey')} {d['tier']}   {ui.c('query', 'grey')} {d['query']}")
    ui.line()
    ui.sleep(0.5)

    ui.dispatch("PROSPECTOR", "Descubrir + enriquecer", f"{s['discovered']} leads")
    ui.dispatch("QUALIFIER", "Calificar (ICP 0-100) ", f"{s['scored']} puntuados · scoring {s['scoring_model']}")
    ui.sleep(0.2)

    ui.line()
    ui.line(f"   {ui.c('VALIDATE', 'bold')} {ui.c('— gate de lead calificado', 'grey')}")
    funnel_bar(ui, "descubiertos", s["discovered"], s["discovered"], "grey")
    ui.sleep(0.25)
    funnel_bar(ui, "calificados", s["qualified"], s["discovered"], "green")
    ui.sleep(0.25)
    funnel_bar(ui, "rechazados", s["rejected"], s["discovered"], "red")
    ui.line()
    ui.sleep(0.3)

    ui.dispatch("OUTREACH", "Redactar primer toque", f"{len(d.get('outreach', []))} mensajes")
    for m in d.get("outreach", [])[:2]:
        head = ui.c(f"[{m['channel']}]", "yellow") + " " + ui.c(m["company"], "white")
        ui.typewriter(head, m["body"][:96] + ("…" if len(m["body"]) > 96 else ""))
    ui.sleep(0.3)

    ui.line()
    ui.dispatch("TRACKER", "Agendar seguimientos ", f"{s.get('sequences_opened', 0)} secuencias (nudge→value→breakup)")

    fc = zero.forecast(args.client).get("forecast", {})
    proj = fc.get("projection", {})
    ui.dispatch("ANALYST", "Proyectar pipeline   ",
                f"~{proj.get('expected_meetings', 0)} reuniones · ${proj.get('expected_pipeline_usd', 0):.0f}")

    ui.line()
    ui.line(f"  {ui.c('✓ entrega lista', 'green')} — {s['qualified']} leads calificados, "
            f"{len(d.get('outreach', []))} primeros toques, forecast incluido.")
    ui.line()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
