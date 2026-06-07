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

    @classmethod
    def from_dict(
        cls,
        d: Dict[str, Any],
        task_id: Optional[str] = None,
        agent: Optional[str] = None,
    ) -> "AgentResponse":
        return cls(
            task_id=d.get("task_id") or task_id or "",
            agent=d.get("agent") or agent or "",
            status=d.get("status", "error"),
            result=d.get("result") or {},
            notes=d.get("notes"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
