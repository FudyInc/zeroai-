"""TRACKER — follow-up sequences after the first touch.

Where OUTREACH writes the first message, TRACKER keeps the conversation alive:
for every due step in a lead's sequence it drafts the next, cadence-appropriate
message (nudge → value → break-up). ZERO owns the sequence state in memory;
TRACKER only drafts what to send for the steps it's handed.

Mock mode drafts deterministic, channel- and step-aware copy so the follow-up
flow is fully demoable offline.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..contracts import TaskPayload
from .base import BaseAgent


class Tracker(BaseAgent):
    name = "TRACKER"
    prompt_file = "tracker.md"

    def _mock_result(self, task: TaskPayload) -> Tuple[Dict[str, Any], str, Optional[str]]:
        seqs: List[Dict[str, Any]] = list(task.data.get("sequences") or [])
        allowed = task.constraints.channels or ["email"]
        # Firma con el vendedor asignado si viene — mismo contrato que OUTREACH
        # (ver zero/agents/outreach.py). Nunca inventa un nombre; nunca firma
        # con "TRACKER" (su propio nombre de agente).
        vendor_name = (task.data.get("vendor") or {}).get("name")
        sign = f"\n\n{vendor_name}" if vendor_name else ""

        messages: List[Dict[str, Any]] = []
        for s in seqs:
            channel = s.get("channel") if s.get("channel") in allowed else allowed[0]
            kind = s.get("kind", "nudge")
            # Bug real encontrado en vivo (2026-07-06): `name or "Hola"` metía el
            # saludo genérico COMO SI fuera el nombre de la persona, produciendo
            # "Hola Hola, ..." para cualquier lead sin nombre verificado (el caso
            # más común en discovery web real — ver [[zero-project]]).
            name = s.get("name")
            greeting = f"Hola {name}" if name else "Hola"
            company = s.get("company", "tu empresa")
            subject, body = self._draft(kind, channel, greeting, company, name)
            messages.append({
                "lead_key": s.get("lead_key"),
                "company": company,
                "channel": channel,
                "step": s.get("step"),
                "kind": kind,
                "subject": subject,
                "body": body + sign,
            })

        return {"messages": messages}, "done", f"drafted {len(messages)} follow-ups (mock)"

    @staticmethod
    def _draft(kind: str, channel: str, greeting: str, company: str,
               name: Optional[str]) -> Tuple[Optional[str], str]:
        is_email = channel == "email"
        if kind == "nudge":
            subject = f"Sobre los leads para {company}" if is_email else None
            body = (
                f"{greeting}, te escribí hace unos días sobre generar leads B2B ya "
                f"calificados para {company}. ¿Lo alcanzaste a ver? Con gusto te muestro 3 ejemplos."
            )
        elif kind == "value":
            subject = f"Un caso parecido a {company}" if is_email else None
            body = (
                f"{greeting}, un cliente del rubro de {company} pasó de ~5 a 20 reuniones/mes "
                f"con nuestros leads calificados (score ≥ 70). ¿Te sirve que agendemos 10 min esta semana?"
            )
        else:  # breakup
            # Sin nombre verificado, cerrar sobre la EMPRESA, nunca "¿..., None?"
            subject = (f"¿Cierro el tema, {name}?" if is_email and name
                       else f"¿Seguimos con {company}?" if is_email else None)
            body = (
                f"{greeting}, no quiero insistir de más. Si no es el momento para {company} lo dejo aquí; "
                f"si más adelante quieres leads B2B calificados, escríbeme y retomamos. ¡Éxito!"
            )
        return subject, body
