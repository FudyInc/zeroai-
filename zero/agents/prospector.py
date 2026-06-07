"""PROSPECTOR — lead discovery + enrichment.

Mock mode synthesizes plausible, deterministic leads from a small fixture pool so
the pipeline produces stable, demoable output with no network access.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

from ..contracts import AgentResponse, TaskPayload
from .base import BaseAgent

_COMPANIES = [
    ("Andesoft", "andesoft.cl"), ("LogiSur", "logisur.cl"), ("NovaRetail", "novaretail.com"),
    ("CumbreData", "cumbredata.io"), ("Patagonia Foods", "patagoniafoods.cl"),
    ("RutaCloud", "rutacloud.com"), ("ViñaTech", "vinatech.cl"), ("MarAustral", "maraustral.cl"),
    ("FintechAndes", "fintechandes.com"), ("SaludDigital", "saluddigital.cl"),
    ("AgroNorte", "agronorte.cl"), ("ConstruyeYa", "construyeya.cl"),
]
_ROLES = [
    "Gerente Comercial", "Head of Growth", "CEO", "Director de Operaciones",
    "Gerente de Marketing", "Fundador", "VP Ventas", "Country Manager",
]


def _h(seed: str) -> int:
    return int(hashlib.sha256(seed.encode()).hexdigest(), 16)


class Prospector(BaseAgent):
    name = "PROSPECTOR"
    prompt_file = "prospector.md"

    def run(self, task: TaskPayload) -> AgentResponse:
        # A configured discovery source is the *real* path: it takes precedence
        # over both mock fixtures and free-form LLM generation.
        if self.source is not None:
            return self._discover_real(task)
        return super().run(task)

    def _discover_real(self, task: TaskPayload) -> AgentResponse:
        query = task.data.get("query") or task.instructions
        cap = task.constraints.max_items or 8
        channels = task.constraints.channels or ["email"]
        try:
            candidates = self.source.search_leads(query, cap, channels)
        except Exception as e:  # network/parse hiccup — degrade, don't crash the pipeline
            return AgentResponse(task.task_id, self.name, "partial", {"leads": []},
                                 f"discovery falló: {e}")

        leads: List[Dict[str, Any]] = []
        for c in candidates:
            lead = dict(c)
            if not lead.get("role"):
                lead["role"] = "por verificar"   # honest placeholder; QUALIFIER/humans refine
            leads.append(lead)

        status = "done" if leads else "partial"
        with_contact = sum(1 for l in leads if l.get("email") or l.get("phone"))
        note = f"descubiertos {len(leads)} reales vía web ({with_contact} con contacto)"
        return AgentResponse(task.task_id, self.name, status, {"leads": leads}, note)

    def _mock_result(self, task: TaskPayload) -> Tuple[Dict[str, Any], str, Optional[str]]:
        cap = task.constraints.max_items or 8
        channels = task.constraints.channels or ["email"]
        query = task.data.get("query") or task.instructions

        # Generate until we actually reach the requested count, de-duping by
        # company as we go — one lead per company, so the client never gets the
        # same business twice. Attempts are bounded in case the fixture pool is
        # too small to fill the cap (then we honestly report "partial").
        leads: List[Dict[str, Any]] = []
        seen: set = set()
        attempts = 0
        while len(leads) < cap and attempts < cap * 8:
            seed = f"{task.client_id}|{query}|{attempts}"
            attempts += 1
            company, domain = _COMPANIES[_h(seed + "c") % len(_COMPANIES)]
            role = _ROLES[_h(seed + "r") % len(_ROLES)]
            if company in seen:                  # one lead per company
                continue
            seen.add(company)
            first = ["maria", "diego", "javier", "camila", "rodrigo", "valentina"][_h(seed + "n") % 6]
            channel = channels[_h(seed + "ch") % len(channels)]
            # Simulate imperfect enrichment: ~1 in 6 leads lacks an email.
            has_email = _h(seed + "e") % 6 != 0
            leads.append({
                "company": company,
                "domain": domain,
                "name": first.capitalize(),
                "role": role,
                "email": f"{first}@{domain}" if has_email else None,
                "phone": f"+569{_h(seed + 'p') % 90000000 + 10000000}",
                "channel": channel,
                "source": "mock_discovery",
            })

        status = "done" if len(leads) >= cap else "partial"
        return {"leads": leads}, status, f"discovered {len(leads)} unique leads (mock)"
