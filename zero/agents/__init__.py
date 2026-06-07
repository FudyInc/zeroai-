"""Sub-agent registry. ZERO looks agents up by name here."""
from __future__ import annotations

from .base import BaseAgent
from .prospector import Prospector
from .qualifier import Qualifier
from .outreach import Outreach
from .tracker import Tracker
from .analyst import Analyst

AGENT_CLASSES = {
    "PROSPECTOR": Prospector,
    "QUALIFIER": Qualifier,
    "OUTREACH": Outreach,
    "TRACKER": Tracker,
    "ANALYST": Analyst,
}


def build_agents(backend=None, mock: bool = False, source=None):
    """Instantiate every registered agent sharing one backend (and discovery source)."""
    return {
        name: cls(backend=backend, mock=mock, source=source)
        for name, cls in AGENT_CLASSES.items()
    }


__all__ = [
    "BaseAgent", "Prospector", "Qualifier", "Outreach", "Tracker", "Analyst",
    "AGENT_CLASSES", "build_agents",
]
