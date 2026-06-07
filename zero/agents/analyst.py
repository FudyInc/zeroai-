"""ANALYST — conversion-rate judgment for the forecast.

ANALYST does NOT do the funnel arithmetic: that is deterministic and lives in
`config.project_funnel`, so the numbers are exact on every backend (small local
models are unreliable at multiplication). ANALYST's job is the judgment call —
keep or adjust the baseline conversion rates given the metrics, and explain why.
ZERO then computes the projection from the rates ANALYST returns.

Mock mode returns the baseline rates unchanged with a short rationale.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from ..contracts import TaskPayload
from .base import BaseAgent


class Analyst(BaseAgent):
    name = "ANALYST"
    prompt_file = "analyst.md"

    def _mock_result(self, task: TaskPayload) -> Tuple[Dict[str, Any], str, Optional[str]]:
        rates: Dict[str, float] = dict(task.data.get("rates") or {})
        m: Dict[str, Any] = dict(task.data.get("metrics") or {})
        # Mock keeps the baseline rates; a live model may adjust them.
        return (
            {
                "rates": {
                    "reply_rate": rates.get("reply_rate"),
                    "meeting_rate": rates.get("meeting_rate"),
                    "win_rate": rates.get("win_rate"),
                },
                "commentary": (
                    f"Tasas base sin ajuste; muestra pequeña "
                    f"({m.get('contacted', 0)} contactados), conviene más volumen (mock)."
                ),
            },
            "done",
            "rates baseline sin ajuste (mock)",
        )
