"""Base sub-agent: same JSON contract on every backend.

A real run loads the agent's system prompt, sends the task payload as the user
turn, and parses the JSON reply. A mock run calls `_mock_result` instead, so the
pipeline is fully exercisable offline.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from ..backends import extract_json
from ..config import SONNET
from ..contracts import AgentResponse, TaskPayload

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"


class BaseAgent:
    name: str = "BASE"
    model: str = SONNET
    prompt_file: Optional[str] = None

    def __init__(self, backend: Any = None, mock: bool = False, source: Any = None):
        self.backend = backend
        # No backend means we cannot do a live call — fall back to mock.
        self.mock = mock or backend is None
        # Optional discovery source; only PROSPECTOR uses it.
        self.source = source

    def system_prompt(self) -> str:
        if self.prompt_file:
            p = PROMPT_DIR / self.prompt_file
            if p.exists():
                return p.read_text("utf-8")
        return f"You are {self.name}, a sub-agent of ZERO. Reply only with JSON."

    def run(self, task: TaskPayload) -> AgentResponse:
        if self.mock:
            result, status, notes = self._mock_result(task)
            return AgentResponse(task.task_id, self.name, status, result, notes)

        try:
            raw = self.backend.complete(self.system_prompt(), task.to_json(), self.model)
        except Exception as e:  # backend down / timeout / API error → degrade, don't crash
            return AgentResponse(task.task_id, self.name, "error", {}, f"backend falló: {e}")

        data = extract_json(raw)
        if data is None:
            return AgentResponse(
                task.task_id, self.name, "error", {}, "el modelo no devolvió JSON parseable"
            )
        return AgentResponse.from_dict(data, task.task_id, self.name)

    # Each agent supplies deterministic offline output: (result, status, notes).
    def _mock_result(self, task: TaskPayload) -> Tuple[Dict[str, Any], str, Optional[str]]:
        raise NotImplementedError(f"{self.name} has no mock implementation")
