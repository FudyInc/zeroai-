"""El motor en la nube de WhatsApp: delante del local, nunca en lugar de él.

Decisión de Diego (2026-11-08): un modelo gratis en la nube (Groq) contesta
WhatsApp y el local queda de respaldo. La cuenta gratis permite ~1 conversación
por minuto, así que el respaldo no es teórico: el segundo mensaje de un minuto
lo contesta el local. Estos tests fijan eso. Sin red.
"""
from __future__ import annotations

import copy
import os
import unittest
from unittest import mock

from zero import config
from zero.backends import FallbackBackend, LocalBackend


class _Boom:
    def __init__(self):
        self.calls = 0

    def complete(self, system, user, model, max_tokens=4096):
        self.calls += 1
        raise RuntimeError("HTTP Error 429: Too Many Requests")


class _Down(_Boom):
    def complete(self, system, user, model, max_tokens=4096):
        self.calls += 1
        raise RuntimeError("timed out")


class _Echo:
    def __init__(self, reply="respuesta del local"):
        self.reply, self.calls = reply, 0

    def complete(self, system, user, model, max_tokens=4096):
        self.calls += 1
        return self.reply


def _engine(enabled: bool):
    eng = copy.deepcopy(config.WHATSAPP_ENGINE)
    eng["cloud"]["enabled"] = enabled
    return eng


class CloudPolicyTest(unittest.TestCase):

    def test_policy_lives_in_config_and_starts_off(self):
        cloud = config.WHATSAPP_ENGINE["cloud"]
        # Se enciende solo tras medirlo; encender es cambiar config, no código.
        self.assertFalse(cloud["enabled"])
        self.assertTrue(cloud["model"])
        self.assertTrue(cloud["base_url"].startswith("https://"))
        self.assertEqual(cloud["key_env"], "GROQ_API_KEY")
        # La nube no abre la puerta al gasto: el respaldo pago sigue apagado.
        self.assertFalse(config.WHATSAPP_ENGINE["fallback_to_paid"])


class CloudWiringTest(unittest.TestCase):

    def _agents(self, enabled: bool, key: str):
        import api
        with mock.patch.object(config, "WHATSAPP_ENGINE", _engine(enabled)), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": key}, clear=False):
            return api._agents_whatsapp()

    def test_off_keeps_the_local_engine(self):
        agents, mode = self._agents(False, "gsk_falsa")
        self.assertEqual(mode, "local")
        backend = agents["CONCIERGE"].backend
        self.assertIsInstance(backend.primary, LocalBackend)
        self.assertIn("localhost", backend.primary.base_url)

    def test_on_without_key_keeps_the_local_engine(self):
        agents, mode = self._agents(True, "")
        self.assertEqual(mode, "local")
        self.assertIn("localhost", agents["CONCIERGE"].backend.primary.base_url)

    def test_on_with_key_puts_cloud_first_and_local_behind(self):
        agents, mode = self._agents(True, "gsk_falsa")
        self.assertEqual(mode, "nube")
        backend = agents["CONCIERGE"].backend
        self.assertIsInstance(backend, FallbackBackend)
        cloud = backend.primary
        self.assertEqual(cloud.base_url, config.WHATSAPP_ENGINE["cloud"]["base_url"])
        self.assertEqual(cloud.model, config.WHATSAPP_ENGINE["cloud"]["model"])
        self.assertEqual(cloud.api_key, "gsk_falsa")
        self.assertLessEqual(cloud.timeout, 60)
        # Detrás está el camino local de siempre, con su propio respaldo.
        self.assertIsInstance(backend.secondary, FallbackBackend)
        self.assertIn("localhost", backend.secondary.primary.base_url)

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


class CloudFallbackTest(unittest.TestCase):

    def test_rate_limited_cloud_is_answered_by_local_and_warns(self):
        seen = []
        local = _Echo()
        b = FallbackBackend(_Boom(), secondary=local, on_fallback=seen.append)
        self.assertEqual(b.complete("s", "u", "m"), "respuesta del local")
        self.assertEqual(local.calls, 1)
        self.assertEqual(len(seen), 1)

    def test_cloud_warning_says_local_not_paid(self):
        import api
        sent = []
        with mock.patch.object(config, "WHATSAPP_ENGINE", _engine(True)), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_falsa"}, clear=False), \
             mock.patch("zero.alerts.notify_owner",
                        side_effect=lambda text, **kw: sent.append((text, kw))):
            agents, _ = api._agents_whatsapp()
            backend = agents["CONCIERGE"].backend
            backend.primary = _Down()
            backend.secondary = _Echo()
            self.assertEqual(backend.complete("s", "u", "m"), "respuesta del local")
        self.assertEqual(len(sent), 1)
        texto, kw = sent[0]
        self.assertIn("local", texto)
        self.assertNotIn("paga", texto)
        self.assertEqual(kw.get("kind"), "whatsapp_cloud_fallback")


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
    import json
    return _Resp(json.dumps({"choices": [{"message": {"content": content}}]}).encode())


class CloudRealPathTest(unittest.TestCase):
    """Por el LocalBackend real (urlopen simulado), no por dobles que lanzan solos."""

    def _wired(self):
        import api
        with mock.patch.object(config, "WHATSAPP_ENGINE", _engine(True)), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_falsa"}, clear=False):
            agents, _ = api._agents_whatsapp()
        backend = agents["CONCIERGE"].backend
        backend.secondary = _Echo('{"reply": "local"}')
        return backend

    def _http(self, code):
        import io
        import urllib.error
        return urllib.error.HTTPError("https://api.groq.com", code, "x", {}, io.BytesIO(b""))

    def test_cloud_caps_max_tokens_from_policy(self):
        cloud = self._wired().primary
        cap = config.WHATSAPP_ENGINE["cloud"]["max_tokens"]
        self.assertEqual(cloud._build_payload("s", "u", 4096)["max_tokens"], cap)
        self.assertEqual(cloud._build_payload("s", "u", 100)["max_tokens"], 100)
        # El local no se toca.
        self.assertIsNone(LocalBackend(model="qwen3:14b").max_tokens_cap)

    def test_cap_plus_typical_prompt_fits_the_free_minute(self):
        # ~5700 tokens de prompt medidos el 2026-11-08; límite gratis 8000/min.
        self.assertLess(5700 + config.WHATSAPP_ENGINE["cloud"]["max_tokens"], 8000)

    def test_http_errors_and_timeouts_fall_to_local(self):
        import socket
        for err in (self._http(429), self._http(403), self._http(413),
                    socket.timeout("timed out")):
            backend = self._wired()
            with mock.patch("urllib.request.urlopen", side_effect=err), \
                 mock.patch("zero.alerts.notify_owner"):
                self.assertEqual(backend.complete("s", "u", "m"), '{"reply": "local"}', err)
            self.assertEqual(backend.fallbacks, 1)

    def test_empty_or_non_json_cloud_reply_falls_to_local(self):
        for content in ("", None, "lo siento, no puedo"):
            backend = self._wired()
            with mock.patch("urllib.request.urlopen", return_value=_ok(content)), \
                 mock.patch("zero.alerts.notify_owner"):
                self.assertEqual(backend.complete("s", "u", "m"), '{"reply": "local"}')

    def test_good_cloud_reply_is_used(self):
        backend = self._wired()
        with mock.patch("urllib.request.urlopen", return_value=_ok('{"reply": "nube"}')):
            self.assertEqual(backend.complete("s", "u", "m"), '{"reply": "nube"}')
        self.assertEqual(backend.fallbacks, 0)

    def test_rate_limit_does_not_page_the_owner(self):
        backend = self._wired()
        with mock.patch("urllib.request.urlopen", side_effect=self._http(429)), \
             mock.patch("zero.alerts.notify_owner") as notify:
            backend.complete("s", "u", "m")
        notify.assert_not_called()


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


if __name__ == "__main__":
    unittest.main()
