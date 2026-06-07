"""QUALIFIER — scoring (0-100) + ICP matching.

Mock mode assigns deterministic scores spread across the 45-95 range so the
qualified-lead filter (>= 70) has real work to do.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

from ..contracts import TaskPayload
from .base import BaseAgent

_SCORING_LABEL = {
    "basic": "ICP genérico",
    "advanced": "ICP del cliente",
    "intent": "ICP + intención de compra",
    "vertical": "modelo por vertical",
}


def _h(seed: str) -> int:
    return int(hashlib.sha256(seed.encode()).hexdigest(), 16)


class Qualifier(BaseAgent):
    name = "QUALIFIER"
    prompt_file = "qualifier.md"

    def _mock_result(self, task: TaskPayload) -> Tuple[Dict[str, Any], str, Optional[str]]:
        leads: List[Dict[str, Any]] = list(task.data.get("leads") or [])
        model = _SCORING_LABEL.get(
            task.data.get("scoring", ""), task.data.get("scoring", "ICP genérico")
        )

        scored: List[Dict[str, Any]] = []
        for ld in leads:
            seed = f"{task.client_id}|{ld.get('company')}|{ld.get('role')}"
            score = 45 + _h(seed) % 51  # 45..95
            reasons = [f"Fit por rol: {ld.get('role', 'n/d')}", f"Scoring: {model}"]
            if score >= 70:
                reasons.append("Señales de intención presentes")
            else:
                reasons.append("Fit débil / sin señales de intención")
            enriched = dict(ld)
            enriched["score"] = score
            enriched["icp_reasons"] = reasons
            scored.append(enriched)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return {"leads": scored}, "done", f"scored {len(scored)} leads with {model} (mock)"
