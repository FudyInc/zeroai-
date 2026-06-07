"""LLM backends. The orchestrator and agents depend only on `.complete()`.

Three paths share one contract:
- `AnthropicBackend` — the hosted API path (dev / highest quality).
- `LocalBackend`     — any OpenAI-compatible local server (Ollama, vLLM, TGI,
  llama.cpp). This is the production target: a model like Qwen/Llama on your own
  box, no key, no per-token cost. Same prompts, same JSON contract.
- mock              — no backend at all; agents synthesize deterministic output
  locally (see each agent's `_mock_result`), so the pipeline runs offline.
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class AnthropicBackend:
    """Thin wrapper over the Anthropic Messages API."""

    def __init__(self, api_key: Optional[str] = None):
        import anthropic  # lazy: only needed on the live path

        self.client = (
            anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        )

    def complete(self, system: str, user: str, model: str, max_tokens: int = 4096) -> str:
        msg = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            block.text for block in msg.content if getattr(block, "type", None) == "text"
        )


class LocalBackend:
    """Local model via an OpenAI-compatible /chat/completions endpoint.

    Works with Ollama (`http://localhost:11434/v1`), vLLM, TGI and llama.cpp's
    server out of the box. Uses only the stdlib, so no extra install is needed.

    The per-agent Anthropic model id is ignored on purpose: one local model
    serves every role, so `self.model` (set once here) wins. Swapping the whole
    pipeline to local inference is therefore *only* this backend object.
    """

    def __init__(
        self,
        model: str = "qwen2.5-coder:7b",
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "local",
        timeout: float = 180.0,
        temperature: float = 0.2,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature

    def complete(self, system: str, user: str, model: str, max_tokens: int = 4096) -> str:
        body = json.dumps({
            "model": self.model,  # local model wins over the per-agent Anthropic id
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": self.temperature,
            # Coax small models into clean JSON; honored by Ollama and vLLM.
            "response_format": {"type": "json_object"},
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise RuntimeError(f"local backend unreachable at {self.base_url}: {e}") from e

        try:
            return payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"unexpected response from local backend: {payload!r}") from e


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort: pull the first JSON object out of a model's text reply."""
    if not text:
        return None
    text = text.strip()

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        text = fenced.group(1)

    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except Exception:
                    return None
    return None
