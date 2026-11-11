"""La key de Anthropic es solo para WhatsApp (Diego, 2026-11-11: USD 5 sin recarga).

Prospección, seguimientos, acciones del dashboard y scheduler no la usan aunque
exista. WhatsApp sí.
"""
import os
import unittest
from unittest import mock

from fastapi import HTTPException

from zero import config
from zero.backends import AnthropicBackend

ENV = {"ANTHROPIC_API_KEY": "sk-ant-falsa", "OPENAI_API_KEY": "", "LOCAL_MODEL": "",
       "GROQ_API_KEY": "gsk_falsa", "ZERO_PIPELINE_MOCK_OK": ""}
# Con un modelo local declarado siempre hay motor: el test ve cuál se eligió.
ENV_LOCAL = {**ENV, "LOCAL_MODEL": "qwen-prueba"}


def _uses_anthropic(agents):
    return any(isinstance(getattr(a, "backend", None), AnthropicBackend) for a in agents.values())


class AnthropicWhatsAppOnlyTest(unittest.TestCase):

    def test_policy(self):
        self.assertTrue(config.ANTHROPIC_KEY_WHATSAPP_ONLY)

    def test_general_engine_does_not_use_the_key(self):
        import api
        with mock.patch.dict(os.environ, ENV_LOCAL, clear=False), \
             mock.patch("anthropic.Anthropic", lambda **kw: object()):
            agents, mode = api._agents_best()
        self.assertNotEqual(mode, "mock")
        self.assertFalse(_uses_anthropic(agents))

    def test_scheduler_does_not_use_the_key(self):
        import api
        with mock.patch.dict(os.environ, ENV_LOCAL, clear=False), \
             mock.patch("anthropic.Anthropic", lambda **kw: object()):
            agents, mode = api._agents_autonomous()
        self.assertNotEqual(mode, "mock")
        self.assertFalse(_uses_anthropic(agents))

    def test_pipeline_cannot_pick_anthropic(self):
        import api
        with mock.patch.dict(os.environ, ENV, clear=False):
            with self.assertRaises(HTTPException) as ctx:
                api._pipeline_agents("anthropic")
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("WhatsApp", ctx.exception.detail)

    def test_whatsapp_still_uses_it(self):
        import api
        with mock.patch.dict(os.environ, ENV, clear=False), \
             mock.patch("anthropic.Anthropic", lambda **kw: object()):
            agents, mode = api._agents_whatsapp()
        self.assertEqual(mode, "anthropic")
        self.assertIsInstance(agents["CONCIERGE"].backend.primary, AnthropicBackend)

    def test_opening_the_policy_restores_the_old_order(self):
        import api
        with mock.patch.object(config, "ANTHROPIC_KEY_WHATSAPP_ONLY", False), \
             mock.patch.dict(os.environ, ENV, clear=False), \
             mock.patch("anthropic.Anthropic", lambda **kw: object()):
            agents, _ = api._agents_best()
        self.assertTrue(_uses_anthropic(agents))


if __name__ == "__main__":
    unittest.main()
