"""OUTREACH — first-touch messaging (email / WhatsApp / cold call).

Mock mode drafts a short, channel-appropriate first message per qualified lead,
scaling personalization by the client's tier (a STARTER gets a clean template; an
ENTERPRISE gets a more consultative touch). The real model is told to do the same
via prompts/outreach.md.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..contracts import ROLE_UNVERIFIED, TaskPayload
from .base import BaseAgent

# One extra, tier-appropriate sentence woven into the pitch. Empty for STARTER
# (clean and generic); richer/more consultative as the plan grows.
_TIER_TOUCH = {
    "STARTER": "",
    "GROWTH": "Trabajamos con PyMEs de tu rubro.",
    "SCALE": "Medianas como la tuya suelen sumar 15-20 reuniones al mes con esto.",
    "ENTERPRISE": "Para equipos de tu tamaño armamos un piloto a medida por vertical.",
}


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)


class Outreach(BaseAgent):
    name = "OUTREACH"
    prompt_file = "outreach.md"

    def _mock_result(self, task: TaskPayload) -> Tuple[Dict[str, Any], str, Optional[str]]:
        leads: List[Dict[str, Any]] = list(task.data.get("leads") or [])
        allowed = task.constraints.channels or ["email"]
        tier = task.client_tier or "STARTER"
        touch = _TIER_TOUCH.get(tier, "")
        # Firma con el vendedor asignado (Fernanda/Stéfano/...) si viene — mismo
        # contrato que el prompt real (prompts/outreach.md): nunca se inventa un
        # nombre, y sin vendor no hay firma de persona (nunca el nombre interno
        # del agente, "OUTREACH", como firma — visto en vivo con el modelo real).
        vendor_name = (task.data.get("vendor") or {}).get("name")
        sign = f"\n\n{vendor_name}" if vendor_name else ""

        messages: List[Dict[str, Any]] = []
        for ld in leads:
            channel = ld.get("channel") if ld.get("channel") in allowed else allowed[0]
            company = ld.get("company", "tu empresa")
            role = ld.get("role", "tu equipo")
            # "por verificar" (PROSPECTOR, discovery web) es un placeholder honesto de
            # "no sabemos quién decide todavía" — nunca un rol real. Tratarlo como tal
            # evita mensajes que suenan rotos (ej. "vi que lideras como por verificar").
            role_known = bool(role) and role != ROLE_UNVERIFIED
            name = ld.get("name")
            greeting = f"Hola {name}" if name else "Hola"
            if channel == "email":
                subject: Optional[str] = f"Leads B2B calificados para {company}"
                role_clause = (f"Vi que lideras como {role} en {company}" if role_known
                               else f"Vi el trabajo de {company}")
                body = _join(
                    f"{greeting}, soy de la agencia. {role_clause} y generamos leads B2B "
                    f"de alta intención, ya calificados (score ≥ 70).",
                    touch,
                    "¿Te hago llegar una muestra esta semana?",
                ) + sign
            elif channel == "whatsapp":
                subject = None
                body = _join(
                    f"{greeting} 👋 Generamos leads B2B calificados para empresas como {company}.",
                    touch,
                    "¿Te comparto 3 de ejemplo sin costo?",
                ) + sign
            else:  # cold_call / linkedin / sdr_ai
                subject = None
                who = f"{name} ({role}, {company})" if (name or role_known) else f"el equipo de {company}"
                body = _join(
                    f"Guion ({channel}): saludar a {who}; "
                    f"pitch de 15s sobre leads calificados;",
                    touch,
                    "pedir 10 min esta semana.",
                )
            messages.append({
                "company": company,
                "channel": channel,
                "subject": subject,
                "body": body,
            })

        return {"messages": messages}, "done", f"drafted {len(messages)} first-touch messages ({tier}, mock)"
