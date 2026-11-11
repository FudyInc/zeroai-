"""El motor en la nube de WhatsApp: respaldo del local, nunca en lugar de él.

Decisión de Diego (2026-11-08), después de medir con el set de evaluación: la nube
gratis (Groq) no contesta mejor que qwen3:14b local, pero sirve para cubrir las
caídas de Ollama (WSL lo mata por falta de memoria). Por eso el local contesta
primero y la nube solo entra si el local falla. Estos tests fijan eso. Sin red.
"""
from __future__ import annotations

import copy
import io
import json
import os
import socket
import unittest
import urllib.error
from http.client import RemoteDisconnected
from unittest import mock

from zero import config
from zero.backends import FallbackBackend, LocalBackend


class _Boom:
    def __init__(self):
        self.calls = 0

    def complete(self, system, user, model, max_tokens=4096):
        self.calls += 1
        raise RuntimeError("HTTP Error 429: Too Many Requests")


class _Echo:
    def __init__(self, reply="respuesta"):
        self.reply, self.calls = reply, 0

    def complete(self, system, user, model, max_tokens=4096):
        self.calls += 1
        return self.reply


class _Resp:
    def __init__(self, body: bytes):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _ok(content):
    return _Resp(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


def _http(code):
    return urllib.error.HTTPError("http://x", code, "x", {}, io.BytesIO(b""))


def _engine(enabled: bool, primary: str = "local"):
    """Las clases de abajo fijan el modo «local adelante» (2026-11-08, mañana);
    `CloudPrimaryTest` fija el modo vigente, «nube adelante»."""
    eng = copy.deepcopy(config.WHATSAPP_ENGINE)
    eng["cloud"]["enabled"] = enabled
    eng["primary"] = primary
    return eng


def _agents(enabled: bool, key: str, primary: str = "local"):
    import api
    with mock.patch.object(config, "WHATSAPP_ENGINE", _engine(enabled, primary)), \
         mock.patch.dict(os.environ, {"GROQ_API_KEY": key}, clear=False):
        return api._agents_whatsapp()


class CloudPolicyTest(unittest.TestCase):

    def test_policy_lives_in_config(self):
        cloud = config.WHATSAPP_ENGINE["cloud"]
        self.assertTrue(cloud["enabled"])           # encendida como respaldo (2026-11-08)
        self.assertTrue(cloud["model"])
        self.assertTrue(cloud["base_url"].startswith("https://"))
        self.assertEqual(cloud["key_env"], "GROQ_API_KEY")
        # La nube no abre la puerta al gasto: el respaldo pago sigue apagado.
        self.assertFalse(config.WHATSAPP_ENGINE["fallback_to_paid"])
        # 2026-11-11: contesta Claude y la nube queda detrás (test_whatsapp_claude_engine).
        # El local sigue fuera: el PC se cayó por él.
        self.assertEqual(config.WHATSAPP_ENGINE["primary"], "anthropic")
        self.assertFalse(config.WHATSAPP_ENGINE["local_backup"])


class CloudWiringTest(unittest.TestCase):

    def test_off_keeps_the_local_engine_alone(self):
        agents, mode = _agents(False, "gsk_falsa")
        self.assertEqual(mode, "local")
        backend = agents["CONCIERGE"].backend
        self.assertIn("localhost", backend.primary.base_url)
        self.assertIsNone(backend.secondary)
        self.assertFalse(backend.primary.require_json)   # sin respaldo, como siempre

    def test_on_without_key_keeps_the_local_engine_alone(self):
        agents, mode = _agents(True, "")
        self.assertEqual(mode, "local")
        self.assertIsNone(agents["CONCIERGE"].backend.secondary)

    def test_on_with_key_puts_local_first_and_cloud_behind(self):
        agents, mode = _agents(True, "gsk_falsa")
        self.assertEqual(mode, "local")
        backend = agents["CONCIERGE"].backend
        self.assertIsInstance(backend, FallbackBackend)
        self.assertIn("localhost", backend.primary.base_url)
        self.assertTrue(backend.primary.require_json)
        cloud = backend.secondary
        self.assertIsInstance(cloud, LocalBackend)
        self.assertEqual(cloud.base_url, config.WHATSAPP_ENGINE["cloud"]["base_url"])
        self.assertEqual(cloud.model, config.WHATSAPP_ENGINE["cloud"]["model"])
        self.assertEqual(cloud.api_key, "gsk_falsa")
        self.assertLessEqual(cloud.timeout, 60)
        self.assertTrue(cloud.require_json)

    def test_status_reports_cloud_without_leaking_the_key(self):
        import api
        with mock.patch.object(config, "WHATSAPP_ENGINE", _engine(True)), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_secreta"}, clear=False):
            st = api._whatsapp_engine_status()
        self.assertTrue(st["cloud"]["active"])
        self.assertNotIn("gsk_secreta", repr(st))
        with mock.patch.object(config, "WHATSAPP_ENGINE", _engine(True)), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}, clear=False):
            self.assertFalse(api._whatsapp_engine_status()["cloud"]["active"])

    def test_with_backup_local_does_not_wait_ten_minutes(self):
        agents, _ = _agents(True, "gsk_falsa")
        local = agents["CONCIERGE"].backend.primary
        self.assertEqual(local.timeout, config.WHATSAPP_ENGINE["local_timeout_with_backup_s"])
        self.assertLessEqual(local.timeout, 180)
        # Sin respaldo se espera lo de siempre: no hay a quién más preguntarle.
        agents, _ = _agents(False, "gsk_falsa")
        self.assertEqual(agents["CONCIERGE"].backend.primary.timeout, 600.0)

    def test_cloud_then_paid_warns_each_step(self):
        import api
        eng = _engine(True)
        eng["fallback_to_paid"] = True
        sent = []
        paid = _Echo('{"reply": "paga"}')
        with mock.patch.object(config, "WHATSAPP_ENGINE", eng), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_falsa",
                                          "ANTHROPIC_API_KEY": "sk-falsa"}, clear=False), \
             mock.patch("zero.backends.AnthropicBackend", return_value=paid):
            backend = api._agents_whatsapp()[0]["CONCIERGE"].backend
        with mock.patch("urllib.request.urlopen", side_effect=_http(500)), \
             mock.patch("zero.alerts.notify_owner",
                        side_effect=lambda text, **kw: sent.append(kw.get("kind"))):
            self.assertEqual(backend.complete("s", "u", "m"), '{"reply": "paga"}')
        self.assertEqual(sent, ["whatsapp_engine_fallback", "whatsapp_paid_fallback"])


class CloudFallbackTest(unittest.TestCase):
    """Por el LocalBackend real (urlopen simulado según el host), no por dobles."""

    def _run(self, local, cloud=lambda: _ok('{"reply": "nube"}')):
        """`local`/`cloud`: excepción a lanzar o fábrica de respuesta."""
        backend = _agents(True, "gsk_falsa")[0]["CONCIERGE"].backend
        calls = {"local": 0, "nube": 0}

        def _urlopen(req, timeout=None):
            which = "local" if "localhost" in req.full_url else "nube"
            calls[which] += 1
            out = local if which == "local" else cloud
            if isinstance(out, BaseException):
                raise out
            return out()

        sent = []
        with mock.patch("urllib.request.urlopen", side_effect=_urlopen), \
             mock.patch("zero.alerts.notify_owner",
                        side_effect=lambda text, **kw: sent.append((text, kw))):
            try:
                result = backend.complete("s", "u", "m")
            except Exception as e:      # noqa: BLE001
                result = e
        return result, calls, sent, backend

    def test_healthy_local_answers_and_cloud_is_not_touched(self):
        result, calls, sent, _ = self._run(lambda: _ok('{"reply": "local"}'))
        self.assertEqual(result, '{"reply": "local"}')
        self.assertEqual(calls["nube"], 0)
        self.assertEqual(sent, [])

    def test_ollama_down_or_broken_is_covered_by_cloud(self):
        for err in (urllib.error.URLError(ConnectionRefusedError(111, "refused")),
                    _http(500), RemoteDisconnected("closed"), socket.timeout("timed out")):
            result, calls, sent, backend = self._run(err)
            self.assertEqual(result, '{"reply": "nube"}', err)
            self.assertEqual(calls["nube"], 1)
            self.assertEqual(backend.fallbacks, 1)

    def test_empty_or_non_json_local_reply_is_covered_by_cloud(self):
        for content in ("", None, "lo siento"):
            result, *_ = self._run(lambda c=content: _ok(c))
            self.assertEqual(result, '{"reply": "nube"}')

    def test_fallback_warns_the_owner_naming_the_free_cloud(self):
        _, _, sent, _ = self._run(_http(500))
        self.assertEqual(len(sent), 1)
        texto, kw = sent[0]
        self.assertIn("Groq", texto)
        self.assertNotIn("paga", texto)
        self.assertEqual(kw.get("kind"), "whatsapp_engine_fallback")

    def test_both_down_raises_instead_of_inventing(self):
        result, *_ = self._run(_http(500), cloud=_http(429))
        self.assertIsInstance(result, Exception)   # el agente lo vuelve status=error

    def test_cloud_caps_max_tokens_from_policy(self):
        backend = _agents(True, "gsk_falsa")[0]["CONCIERGE"].backend
        cloud = backend.secondary
        cap = config.WHATSAPP_ENGINE["cloud"]["max_tokens"]
        self.assertEqual(cloud._build_payload("s", "u", 4096)["max_tokens"], cap)
        self.assertEqual(cloud._build_payload("s", "u", 100)["max_tokens"], 100)
        self.assertEqual(backend.primary._build_payload("s", "u", 4096)["max_tokens"], 4096)

    def test_cap_plus_largest_prompt_fits_the_free_minute(self):
        # Prompt máximo medido el 2026-11-08: ~3 100 tokens (cota holgada: 5 700).
        self.assertLess(5700 + config.WHATSAPP_ENGINE["cloud"]["max_tokens"], 8000)


class EngineTelemetryTest(unittest.TestCase):
    """La telemetría dice qué modelo contestó de verdad, no cuál iba primero."""

    def _agent(self, backend):
        return type("A", (), {"mock": False, "backend": backend})()

    def test_reports_local_when_cloud_failed(self):
        from zero.orchestrator import _nombre_motor
        cloud = _Boom(); cloud.model = "openai/gpt-oss-120b"
        local = _Echo(); local.model = "qwen3:14b"
        b = FallbackBackend(cloud, secondary=local)
        self.assertEqual(_nombre_motor(self._agent(b)), "openai/gpt-oss-120b")  # aún sin llamadas
        b.complete("s", "u", "m")
        self.assertEqual(_nombre_motor(self._agent(b)), "qwen3:14b")

    def test_nested_fallback_reports_innermost_answer(self):
        from zero.orchestrator import _nombre_motor
        cloud = _Boom(); cloud.model = "nube"
        local = _Echo(); local.model = "qwen3:14b"
        inner = FallbackBackend(local)
        b = FallbackBackend(cloud, secondary=inner)
        b.complete("s", "u", "m")
        self.assertEqual(_nombre_motor(self._agent(b)), "qwen3:14b")

    def test_reports_cloud_when_cloud_answered(self):
        from zero.orchestrator import _nombre_motor
        cloud = _Echo(); cloud.model = "openai/gpt-oss-120b"
        b = FallbackBackend(cloud, secondary=_Echo())
        b.complete("s", "u", "m")
        self.assertEqual(_nombre_motor(self._agent(b)), "openai/gpt-oss-120b")


class CloudPrimaryTest(unittest.TestCase):
    """Modo vigente: contesta la nube; respaldo otro modelo de la nube; el local
    nunca recibe una llamada (cargarlo es lo que tumbaba el PC)."""

    def _backend(self, key="gsk_falsa", local_backup=False):
        import api
        eng = _engine(True, "cloud")
        eng["local_backup"] = local_backup
        with mock.patch.object(config, "WHATSAPP_ENGINE", eng), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": key}, clear=False):
            return api._agents_whatsapp()

    def test_cloud_answers_with_cloud_backup_and_no_local(self):
        agents, mode = self._backend()
        self.assertEqual(mode, "cloud")
        b = agents["CONCIERGE"].backend
        cfg = config.WHATSAPP_ENGINE["cloud"]
        self.assertEqual(b.primary.model, cfg["model"])
        self.assertEqual(b.secondary.model, cfg["backup_model"])
        self.assertNotIn("localhost", b.secondary.base_url)

    def test_local_is_never_called(self):
        agents, _ = self._backend()
        b = agents["CONCIERGE"].backend
        hosts = []

        def _urlopen(req, timeout=None):
            hosts.append(req.full_url)
            raise _http(500)
        with mock.patch("urllib.request.urlopen", side_effect=_urlopen), \
             mock.patch("zero.alerts.notify_owner"):
            with self.assertRaises(Exception):
                b.complete("s", "u", "m")
        self.assertEqual(len(hosts), 2)                  # principal y respaldo
        self.assertFalse(any("localhost" in h or "127.0.0.1" in h for h in hosts))

    def test_backup_answers_and_owner_is_warned(self):
        agents, _ = self._backend()
        b = agents["CONCIERGE"].backend
        calls, sent = [], []

        def _urlopen(req, timeout=None):
            model = json.loads(req.data)["model"]
            calls.append(model)
            if model == config.WHATSAPP_ENGINE["cloud"]["model"]:
                raise _http(429)
            return _ok('{"reply": "respaldo"}')
        with mock.patch("urllib.request.urlopen", side_effect=_urlopen), \
             mock.patch("zero.alerts.notify_owner",
                        side_effect=lambda text, **kw: sent.append(kw.get("kind"))):
            self.assertEqual(b.complete("s", "u", "m"), '{"reply": "respaldo"}')
        self.assertEqual(sent, ["whatsapp_engine_fallback"])

    def test_local_backup_flag_puts_local_last(self):
        agents, _ = self._backend(local_backup=True)
        b = agents["CONCIERGE"].backend
        self.assertIn("localhost", b.secondary.secondary.base_url)

    def test_without_any_backup_the_owner_is_still_warned(self):
        import api
        eng = _engine(True, "cloud")
        eng["cloud"]["backup_model"] = ""
        with mock.patch.object(config, "WHATSAPP_ENGINE", eng), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_falsa"}, clear=False):
            agents, _ = api._agents_whatsapp()
        b = agents["CONCIERGE"].backend
        sent = []
        with mock.patch("urllib.request.urlopen", side_effect=_http(429)), \
             mock.patch("zero.alerts.notify_owner",
                        side_effect=lambda text, **kw: sent.append(kw.get("kind"))):
            with self.assertRaises(Exception):
                b.complete("s", "u", "m")
        self.assertEqual(sent, ["whatsapp_engine_fallback"])

    def test_local_backup_uses_the_short_timeout(self):
        agents, _ = self._backend(local_backup=True)
        local = agents["CONCIERGE"].backend.secondary.secondary
        self.assertEqual(local.timeout, config.WHATSAPP_ENGINE["local_timeout_with_backup_s"])

    def test_without_key_falls_back_to_the_local_mode(self):
        agents, mode = self._backend(key="")
        self.assertEqual(mode, "local")


if __name__ == "__main__":
    unittest.main()
