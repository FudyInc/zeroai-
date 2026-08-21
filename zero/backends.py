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
        # Holgado a propósito: un modelo razonador (DeepSeek-R1) en CPU puede tardar
        # varios minutos en un lote; mejor lento que un pipeline caído por timeout.
        timeout: float = 600.0,
        temperature: float = 0.2,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature
        # Modelos razonadores (DeepSeek-R1, QwQ) piensan antes de responder — bien
        # para calidad, pero mucho más lento. `think: false` (Ollama 0.9+) le pide
        # que se salte ese razonamiento por completo. Verificado en vivo
        # (2026-07-06) contra deepseek-r1:7b real, vía este mismo endpoint
        # (/v1/chat/completions): sin el flag, la respuesta trajo 97 tokens de
        # razonamiento (en un campo `reasoning` aparte, no embebido en el texto —
        # `content` ya venía limpio de todos modos); con el flag, solo 10 — ahorro
        # real de tiempo, no un fix de parseo. Sin efecto en modelos no
        # razonadores (qwen2.5, etc.) — Ollama ignora el campo si no aplica.
        self.no_think = any(tag in model.lower() for tag in ("r1", "qwq", "deepseek"))

    def _build_payload(self, system: str, user: str, max_tokens: int) -> Dict[str, Any]:
        """Separado de complete() para poder probarlo sin tocar la red."""
        payload: Dict[str, Any] = {
            "model": self.model,  # local model wins over the per-agent Anthropic id
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": self.temperature,
            # Coax small models into clean JSON; honored by Ollama and vLLM.
            "response_format": {"type": "json_object"},
        }
        if self.no_think:
            payload["think"] = False
        return payload

    def complete(self, system: str, user: str, model: str, max_tokens: int = 4096) -> str:
        body = json.dumps(self._build_payload(system, user, max_tokens)).encode("utf-8")

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


class FallbackBackend:
    """Un cerebro principal con suplente: si el principal falla, contesta el otro.

    Existe por el motor de WhatsApp (ver `config.WHATSAPP_ENGINE`): el modelo local
    es gratis pero vive en esta máquina, así que un Ollama caído no puede dejar a un
    lead sin respuesta. El suplente es la API paga — respaldo, no camino normal.

    Por qué envolver y no chequear salud antes: el local puede estar arriba al armar
    los agentes y caerse a mitad de la conversación (modelo descargándose de VRAM,
    timeout bajo carga). Un chequeo previo no ve eso; envolver la llamada real, sí.

    `on_fallback(err)` se dispara en cada cambio, para avisar que se está gastando.
    Si ese aviso falla, se ignora: avisar jamás puede romper la respuesta al lead.
    """

    def __init__(self, primary: Any, secondary: Optional[Any] = None,
                 on_fallback: Optional[Any] = None):
        self.primary = primary
        self.secondary = secondary
        self.on_fallback = on_fallback
        self.fallbacks = 0          # cuántas veces se usó el suplente (para /status y tests)

    def complete(self, system: str, user: str, model: str, max_tokens: int = 4096) -> str:
        try:
            return self.primary.complete(system, user, model, max_tokens=max_tokens)
        except Exception as primary_error:   # noqa: BLE001 — cualquier falla activa el suplente
            if self.secondary is None:
                raise
            self.fallbacks += 1
            if self.on_fallback is not None:
                try:
                    self.on_fallback(primary_error)
                except Exception:            # noqa: BLE001
                    pass
            return self.secondary.complete(system, user, model, max_tokens=max_tokens)


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort: pull a JSON object out of a model's text reply.

    Real models (especially small local ones) wrap JSON in prose, code fences, or
    return a bare array instead of the response envelope. This is deliberately
    liberal so a slightly messy reply never crashes the pipeline:
      - strips ```json fences,
      - tolerates text before/after the JSON,
      - accepts a top-level array (wrapped as {"leads": [...]}),
      - falls back to brace/bracket matching when a plain parse fails.
    Returns a dict (arrays are wrapped) or None if nothing usable is found.
    """
    if not text:
        return None
    text = text.strip()

    # 0) Drop the reasoning block that thinking models (DeepSeek-R1, QwQ) prepend,
    #    so a JSON-looking fragment inside the reasoning never wins over the answer.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()

    # 1) Strip a code fence if present (```json ... ``` or ``` ... ```).
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()

    # 2) Straight parse.
    obj = _try_load(text)
    if obj is not None:
        return obj

    # 3) Balanced-delimiter scan. Try whichever delimiter appears *first* in the
    #    text, so prose before a bare array doesn't make us grab its first inner
    #    object instead of the whole array.
    pos_obj, pos_arr = text.find("{"), text.find("[")
    spans = sorted(
        (p, o, c) for p, (o, c) in ((pos_obj, ("{", "}")), (pos_arr, ("[", "]"))) if p != -1
    )
    for _, open_ch, close_ch in spans:
        snippet = _balanced(text, open_ch, close_ch)
        if snippet is not None:
            obj = _try_load(snippet)
            if obj is not None:
                return obj
    return None


def _try_load(text: str) -> Optional[Dict[str, Any]]:
    """json.loads, wrapping a top-level array as {"leads": [...]}."""
    try:
        data = json.loads(text)
    except Exception:
        return None
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"leads": data}
    return None


def _balanced(text: str, open_ch: str, close_ch: str) -> Optional[str]:
    """Return the first balanced open_ch..close_ch span, ignoring delimiters
    inside JSON strings. None if there is no complete span."""
    start = text.find(open_ch)
    if start == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None
