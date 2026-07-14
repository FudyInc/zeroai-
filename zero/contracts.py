"""The JSON contract every agent speaks — independent of the backend.

These dataclasses *are* the interface between ZERO and its sub-agents. An agent
backed by the Anthropic API and one backed by a local Llama endpoint exchange the
exact same shapes, so a backend swap needs zero contract changes.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _as_int(value: Any) -> Optional[int]:
    """Coerce a score to int. A live model may return "85" or 85.0; bad input → None.
    Keeps the gate's numeric comparison from crashing on a stringified score."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


@dataclass
class Constraints:
    max_items: int = 0
    channels: List[str] = field(default_factory=list)
    deadline: Optional[str] = None


@dataclass
class TaskPayload:
    """A unit of work dispatched from ZERO to a sub-agent (schema: task out)."""
    agent: str
    client_id: str
    client_tier: str
    instructions: str
    data: Dict[str, Any] = field(default_factory=dict)
    constraints: Constraints = field(default_factory=Constraints)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "client_id": self.client_id,
            "client_tier": self.client_tier,
            "instructions": self.instructions,
            "data": self.data,
            "constraints": asdict(self.constraints),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


@dataclass
class AgentResponse:
    """A sub-agent's structured reply (schema: agent response in)."""
    task_id: str
    agent: str
    status: str  # done | partial | error
    result: Dict[str, Any] = field(default_factory=dict)
    notes: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == "done"

    # "intent" (CONCIERGE): sin esto, el modelo real siempre lo devuelve pero
    # from_dict lo descartaba en silencio (no había envoltorio "result" en su
    # esquema plano) — encontrado en vivo (2026-07-13) contra el modelo real:
    # `converse_result` SIEMPRE devolvía intent=None, aunque el modelo sí
    # incluía el campo correcto ("pricing", "optout", etc. — confirmado
    # comparando la salida cruda del modelo contra el resultado ya parseado).
    # Esto rompía en silencio el flujo de "oferta pendiente" en
    # `handle_inbound` (Zero.converse_result → set_pending_offer si intent es
    # "info"/"objection"): nunca se activaba con el motor real, solo en mock
    # (el mock nunca pasa por from_dict). Justo el caso que el CLAUDE.md de
    # este repo advierte: un mock que diverge del contrato real da falsa
    # confianza — los tests en verde no lo detectaban porque todos usan mock.
    _RESULT_KEYS = ("leads", "messages", "rates", "reply", "recommendations", "plan", "subject", "body", "intent")

    @classmethod
    def from_dict(
        cls,
        d: Dict[str, Any],
        task_id: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> "AgentResponse":
        """Build a response from a model's (possibly messy) JSON.

        Defensive on purpose — real models drift from the contract:
        - `result` may be a bare list (→ wrap as {"leads": [...]}) or missing
          entirely while the payload itself holds leads/messages/rates (→ lift
          those up as the result);
        - `status` may be absent or invalid (→ infer from whether we got a result).
        """
        if not isinstance(d, dict):
            return cls(task_id or "", agent or "", "error", {}, "respuesta no es un objeto")

        result = d.get("result")
        if isinstance(result, list):
            result = {"leads": result}
        elif not isinstance(result, dict):
            result = {}

        # Envelope missing but the body carries the payload directly.
        if not result:
            lifted = {k: d[k] for k in cls._RESULT_KEYS if k in d}
            if lifted:
                result = lifted

        status = d.get("status")
        if status not in ("done", "partial", "error"):
            status = "done" if result else "error"

        return cls(
            task_id=d.get("task_id") or task_id or "",
            agent=d.get("agent") or agent or "",
            status=status,
            result=result,
            notes=d.get("notes"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Placeholder PROSPECTOR uses when web discovery can't find a named decision-maker
# on the company's site (zero/agents/prospector.py) — an honest "no sabemos quién
# decide todavía", never a real role. Anything that reads it as a real title (ej.
# OUTREACH escribiendo "vi que lideras como por verificar en...") debe tratarlo
# igual que un rol vacío/desconocido.
ROLE_UNVERIFIED = "por verificar"


@dataclass
class Lead:
    """A normalized lead as it flows through the pipeline."""
    company: str
    role: str
    channel: str
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    domain: Optional[str] = None
    source: Optional[str] = None
    score: Optional[int] = None
    icp_reasons: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Lead":
        return cls(
            company=d.get("company", ""),
            role=d.get("role", ""),
            channel=d.get("channel", ""),
            name=d.get("name"),
            email=d.get("email"),
            phone=d.get("phone"),
            domain=d.get("domain"),
            source=d.get("source"),
            score=_as_int(d.get("score")),
            icp_reasons=list(d.get("icp_reasons") or []),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def key(self) -> str:
        """Stable identity for de-dup and recontact checks."""
        return (self.email or self.phone or f"{self.company}|{self.role}").lower()
