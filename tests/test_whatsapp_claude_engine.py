"""Claude contesta WhatsApp y Groq queda de respaldo (decisión de Diego, 2026-11-11).

Sin red: el cliente de Anthropic y la nube se simulan. Lo que se fija:
- la política vive en `config.WHATSAPP_ENGINE["anthropic"]`;
- el modelo de WhatsApp gana sobre el que pide el agente (CONCIERGE pide Opus);
- la URL de la API va explícita (el entorno puede apuntar a un proxy ajeno);
- si se acaba el saldo, contesta Groq y el dueño recibe un aviso propio;
- sin key de Anthropic, WhatsApp sigue con la nube como antes.
"""
import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from zero import config
from zero.backends import AnthropicBackend, FallbackBackend, LocalBackend


class _FakeMessages:
    def __init__(self, outer):
        self.outer = outer

    def create(self, **kw):
        self.outer.requests.append(kw)
        if self.outer.error is not None:
            raise self.outer.error
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.outer.text)],
            stop_reason=self.outer.stop_reason,
            usage=SimpleNamespace(input_tokens=100, output_tokens=20,
                                  cache_creation_input_tokens=0,
                                  cache_read_input_tokens=3000),
        )


class _FakeAnthropic:
    """Reemplaza `anthropic.Anthropic`; guarda cómo se construyó y qué se pidió."""
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.requests = []
        self.error = None
        self.text = '{"reply": "claude"}'
        self.stop_reason = "end_turn"
        self.messages = _FakeMessages(self)
        _FakeAnthropic.instances.append(self)


class _Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _groq_ok(*a, **kw):
    return _Resp(json.dumps({"choices": [{"message": {"content": '{"reply": "groq"}'}}]}).encode())


KEYS = {"ANTHROPIC_API_KEY": "sk-ant-falsa", "GROQ_API_KEY": "gsk_falsa",
        "ANTHROPIC_BASE_URL": "http://localhost:20128"}


def _agents(env=KEYS, engine=None):
    import api
    _FakeAnthropic.instances = []
    with mock.patch.object(config, "WHATSAPP_ENGINE", engine or copy.deepcopy(config.WHATSAPP_ENGINE)), \
         mock.patch.dict(os.environ, env, clear=False), \
         mock.patch("anthropic.Anthropic", _FakeAnthropic):
        return api._agents_whatsapp()


class ClaudePolicyTest(unittest.TestCase):

    def test_policy_lives_in_config(self):
        eng = config.WHATSAPP_ENGINE
        self.assertEqual(eng["primary"], "anthropic")
        cfg = eng["anthropic"]
        self.assertTrue(cfg["enabled"])
        self.assertEqual(cfg["model"], "claude-sonnet-5-5")
        self.assertEqual(cfg["key_env"], "ANTHROPIC_API_KEY")
        self.assertEqual(cfg["base_url"], "https://api.anthropic.com")
        # Sonnet 5.5 rechaza {"type": "disabled"} con 400.
        self.assertEqual(cfg["thinking"], {"type": "between_tools"})
        self.assertTrue(cfg["cache_system"])
        self.assertLessEqual(cfg["timeout_s"], 60)
        # Groq sigue encendido: es el respaldo.
        self.assertTrue(eng["cloud"]["enabled"])
        self.assertFalse(eng["local_backup"])


class ClaudeWiringTest(unittest.TestCase):

    def test_claude_first_groq_behind(self):
        agents, mode = _agents()
        self.assertEqual(mode, "anthropic")
        backend = agents["CONCIERGE"].backend
        self.assertIsInstance(backend, FallbackBackend)
        self.assertIsInstance(backend.primary, AnthropicBackend)
        self.assertEqual(backend.primary.model, "claude-sonnet-5-5")
        cloud = backend.secondary
        self.assertIsInstance(cloud, FallbackBackend)
        self.assertIsInstance(cloud.primary, LocalBackend)
        self.assertEqual(cloud.primary.model, config.WHATSAPP_ENGINE["cloud"]["model"])
        self.assertEqual(agents["CONCIERGE"].prompt_file, "concierge-whatsapp-local.md")

    def test_ignores_a_proxy_in_the_environment(self):
        _agents()
        kwargs = _FakeAnthropic.instances[-1].kwargs
        self.assertEqual(kwargs["base_url"], "https://api.anthropic.com")
        self.assertEqual(kwargs["api_key"], "sk-ant-falsa")

    def test_request_shape(self):
        agents, _ = _agents()
        claude = agents["CONCIERGE"].backend.primary
        out = claude.complete("SISTEMA", "usuario", "claude-opus-4-8", max_tokens=4096)
        self.assertEqual(out, '{"reply": "claude"}')
        req = _FakeAnthropic.instances[-1].requests[-1]
        self.assertEqual(req["model"], "claude-sonnet-5-5")       # gana el de WhatsApp
        self.assertEqual(req["thinking"], {"type": "between_tools"})
        self.assertEqual(req["max_tokens"], config.WHATSAPP_ENGINE["anthropic"]["max_tokens"])
        self.assertEqual(req["system"], [{"type": "text", "text": "SISTEMA",
                                          "cache_control": {"type": "ephemeral"}}])
        self.assertEqual(claude.last_usage["cache_read_input_tokens"], 3000)

    def test_without_anthropic_key_groq_answers(self):
        agents, mode = _agents({**KEYS, "ANTHROPIC_API_KEY": ""})
        self.assertEqual(mode, "cloud")
        self.assertIsInstance(agents["CONCIERGE"].backend.primary, LocalBackend)

    def test_disabled_policy_groq_answers(self):
        eng = copy.deepcopy(config.WHATSAPP_ENGINE)
        eng["anthropic"]["enabled"] = False
        _, mode = _agents(engine=eng)
        self.assertEqual(mode, "cloud")

    def test_the_rest_of_the_system_is_untouched(self):
        """El AnthropicBackend sin argumentos sigue igual que antes."""
        _FakeAnthropic.instances = []
        with mock.patch("anthropic.Anthropic", _FakeAnthropic):
            b = AnthropicBackend(api_key="sk-ant-falsa")
            b.complete("s", "u", "claude-opus-4-8", max_tokens=4096)
        req = _FakeAnthropic.instances[-1].requests[-1]
        self.assertEqual(req["model"], "claude-opus-4-8")
        self.assertEqual(req["system"], "s")
        self.assertNotIn("thinking", req)
        self.assertEqual(req["max_tokens"], 4096)


class ClaudeFallbackTest(unittest.TestCase):

    def _run(self, error=None, text='{"reply": "claude"}', stop_reason="end_turn"):
        agents, _ = _agents()
        backend = agents["CONCIERGE"].backend
        fake = _FakeAnthropic.instances[-1]
        fake.error, fake.text, fake.stop_reason = error, text, stop_reason
        sent = []
        with mock.patch("urllib.request.urlopen", side_effect=_groq_ok), \
             mock.patch("zero.alerts.notify_owner",
                        side_effect=lambda text, **kw: sent.append((kw.get("kind"), text))):
            out = backend.complete("s", "u", "m")
        return out, sent

    def test_no_credit_falls_to_groq_and_warns_with_its_own_kind(self):
        err = Exception("Error code: 400 - Your credit balance is too low to access the Anthropic API.")
        out, sent = self._run(error=err)
        self.assertEqual(out, '{"reply": "groq"}')
        self.assertEqual([k for k, _ in sent], ["whatsapp_claude_sin_saldo"])
        self.assertIn("saldo", sent[0][1])
        self.assertIn("console.anthropic.com/settings/billing", sent[0][1])

    def test_other_failure_falls_to_groq(self):
        out, sent = self._run(error=TimeoutError("timeout"))
        self.assertEqual(out, '{"reply": "groq"}')
        self.assertEqual([k for k, _ in sent], ["whatsapp_engine_fallback"])

    def test_empty_reply_falls_to_groq(self):
        out, _ = self._run(text="   ")
        self.assertEqual(out, '{"reply": "groq"}')

    def test_refusal_falls_to_groq(self):
        out, _ = self._run(text="", stop_reason="refusal")
        self.assertEqual(out, '{"reply": "groq"}')

    def test_claude_ok_does_not_warn(self):
        out, sent = self._run()
        self.assertEqual(out, '{"reply": "claude"}')
        self.assertEqual(sent, [])


class ClaudeStatusTest(unittest.TestCase):

    def test_status_reports_claude_without_leaking_the_key(self):
        import api
        with mock.patch.dict(os.environ, {**KEYS, "ANTHROPIC_API_KEY": "sk-ant-secreta"}, clear=False):
            st = api._whatsapp_engine_status()
        self.assertEqual(st["primary"], "anthropic")
        self.assertTrue(st["anthropic"]["active"])
        self.assertEqual(st["anthropic"]["model"], "claude-sonnet-5-5")
        self.assertNotIn("sk-ant-secreta", repr(st))

    def test_status_without_key_says_groq(self):
        import api
        with mock.patch.dict(os.environ, {**KEYS, "ANTHROPIC_API_KEY": ""}, clear=False):
            st = api._whatsapp_engine_status()
        self.assertEqual(st["primary"], "cloud")
        self.assertFalse(st["anthropic"]["active"])


if __name__ == "__main__":
    unittest.main()
