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
        # Antes acá decía: "No backend means we cannot do a live call — fall back to
        # mock", y `self.mock = mock or backend is None`. O sea que pedir `mock=False`
        # sin backend devolvía un mock lo mismo, en silencio:
        #
        #     build_agents(mock=False)["PROSPECTOR"].mock  → True
        #
        # Es la misma puerta que se cerró en api.py el 2026-09-08, una capa más abajo y
        # como comportamiento POR DEFECTO de todo agente. Hoy nadie la alcanza —todas
        # las llamadas de producción pasan backend o piden `mock=True` a propósito— pero
        # es la que se cuela sola el día que alguien agregue un sitio y olvide el
        # backend, y se colaría sin ruido.
        #
        # Ahora pedir un agente real sin con qué serlo es un error, no un mock.
        if backend is None and not mock:
            raise ValueError(
                f"{type(self).name if hasattr(type(self), 'name') else 'agente'}: se pidió "
                "un agente real (mock=False) sin backend. Pasa un backend o pide mock=True "
                "explícitamente — ZERO no cae a mock en silencio (ver CLAUDE.md, principio 1)."
            )
        self.mock = mock
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
