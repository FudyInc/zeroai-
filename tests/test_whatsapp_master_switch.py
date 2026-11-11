"""Interruptor maestro del agente de WhatsApp (pedido de Diego, 2026-11-11).

Cambia solo el modo de respuesta. Apagar (manual) nunca depende del puente:
es el freno de emergencia. Encender pausa los chats del período manual."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi import HTTPException

from zero.memory import SessionMemory

PROFILE = {"tone": "cercana", "instructions": "pide medidas", "whatsapp_number": "56911111111",
           "quote_mode": "manual", "response_mode": "manual", "offer_flow": False}


class MasterSwitchTest(unittest.TestCase):

    def setUp(self):
        self.memory = SessionMemory(None)
        self.memory.register_client("losetaschile", "STARTER")
        self.memory.set_client_agent_profile("losetaschile", dict(PROFILE))
        self.memory.clients["losetaschile"]["manual_since"] = (
            datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        p = mock.patch("api.make_memory", return_value=self.memory)
        p.start()
        self.addCleanup(p.stop)

    def _switch(self, mode, client="losetaschile"):
        from api import set_whatsapp_response_mode, ResponseModeBody
        return set_whatsapp_response_mode(client, ResponseModeBody(response_mode=mode))

    def _profile(self):
        return self.memory.get_client_agent_profile("losetaschile")

    @mock.patch("api._whatsapp_web_inbox_request")
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_turn_on_pauses_manual_period_chats_and_keeps_the_rest(self, _prov, chats):
        now = datetime.now(timezone.utc).timestamp()
        chats.return_value = {"chats": [{"id": "56900000077@c.us", "timestamp": now - 100},
                                        {"id": "123@g.us", "timestamp": now - 100}]}
        out = self._switch("automatic")
        self.assertEqual(out["paused_chats"], 1)
        self.assertEqual(self._profile(), {**PROFILE, "response_mode": "automatic"})
        self.assertNotIn("manual_since", self.memory.clients["losetaschile"])

    @mock.patch("api._whatsapp_web_inbox_request", side_effect=RuntimeError("puente caído"))
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_turn_on_without_bridge_stays_manual(self, _prov, _chats):
        with self.assertRaises(RuntimeError):
            self._switch("automatic")
        self.assertEqual(self._profile()["response_mode"], "manual")

    @mock.patch("api._whatsapp_web_inbox_request", side_effect=RuntimeError("puente caído"))
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_emergency_stop_works_with_the_bridge_down(self, _prov, chats):
        self.memory.set_client_agent_profile("losetaschile", {**PROFILE, "response_mode": "automatic"})
        self.memory.clients["losetaschile"].pop("manual_since")
        out = self._switch("manual")
        self.assertEqual(out["paused_chats"], 0)
        chats.assert_not_called()
        self.assertEqual(self._profile(), PROFILE)
        self.assertIn("manual_since", self.memory.clients["losetaschile"])
        self.assertEqual(self.memory.actions[-1]["action"], "whatsapp_response_mode")

    def test_unknown_client_is_404_and_not_created(self):
        with self.assertRaises(HTTPException) as cm:
            self._switch("manual", client="no-existe")
        self.assertEqual(cm.exception.status_code, 404)
        self.assertNotIn("no-existe", self.memory.clients)


if __name__ == "__main__":
    unittest.main()
