"""Tests for the preventive pause when switching from manual to automatic mode."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from zero.config import WHATSAPP_ACTIVATION_PAUSE_DAYS, WHATSAPP_ACTIVATION_PAUSE_REASON
from zero.memory import SessionMemory
from zero.whatsapp_web import chats_to_pause_on_activation


class ChatsToPauseTest(unittest.TestCase):
    def test_keeps_only_private_chats_with_recent_activity(self):
        now = datetime.now(timezone.utc).timestamp()
        chats = [
            {"id": "56900000011@c.us", "timestamp": now - 100},
            {"id": "56900000022@c.us", "timestamp": now - 999999},
            {"id": "123456789@g.us", "timestamp": now - 100},
            {"id": "56900000033@lid", "timestamp": now - 50000},
            {"id": "not-a-chat-id", "timestamp": now - 100},
        ]
        paused = chats_to_pause_on_activation(chats, now - 86400)
        self.assertEqual(paused, ["56900000011@c.us", "56900000033@lid"])

    def test_empty_list(self):
        self.assertEqual(chats_to_pause_on_activation([], 0), [])

    def test_none_input(self):
        self.assertEqual(chats_to_pause_on_activation(None, 0), [])

    def test_non_numeric_timestamp_is_skipped(self):
        now = datetime.now(timezone.utc).timestamp()
        chats = [
            {"id": "56900000011@c.us", "timestamp": "nope"},
            {"id": "56900000022@c.us", "timestamp": now - 100},
        ]
        self.assertEqual(chats_to_pause_on_activation(chats, now - 86400), ["56900000022@c.us"])


class ActivationPauseTest(unittest.TestCase):
    """Tests for _pause_chats_on_activation in api.py - only runs when manual→automatic."""
    PHONE = "56900000077"
    BOT = "56911111111"
    CHAT = PHONE + "@c.us"
    CHAT2 = "56900000088@c.us"
    GROUP = "123456789@g.us"

    def setUp(self):
        self.memory = SessionMemory(None)
        self.memory.register_client("losetaschile", "STARTER")
        self.memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": self.BOT, "response_mode": "manual"})
        self.memory.clients["losetaschile"]["manual_since"] = (
            datetime.now(timezone.utc) - timedelta(days=3)).isoformat()

    def _bridge_chats(self, chats):
        return {"chats": chats}

    @mock.patch("api._whatsapp_web_inbox_request")
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_switch_manual_to_automatic_pauses_recent_chats(self, mock_provider, mock_chats):
        now = datetime.now(timezone.utc).timestamp()
        mock_chats.return_value = self._bridge_chats([
            {"id": self.CHAT, "timestamp": now - 1000},
            {"id": self.CHAT2, "timestamp": now - 86400 * 2},
            {"id": self.GROUP, "timestamp": now - 1000},
        ])
        from api import _pause_chats_on_activation
        paused = _pause_chats_on_activation(self.memory, "losetaschile")
        self.assertEqual(paused, [self.CHAT, self.CHAT2])
        for chat_id in [self.CHAT, self.CHAT2]:
            handoff = self.memory.get_whatsapp_handoff("losetaschile", chat_id)
            self.assertIsNotNone(handoff)
            self.assertEqual(handoff["reason"], WHATSAPP_ACTIVATION_PAUSE_REASON)
            self.assertNotIn("expires", handoff)

    @mock.patch("api._whatsapp_web_inbox_request")
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_existing_handoff_is_kept_not_overwritten(self, mock_provider, mock_chats):
        now = datetime.now(timezone.utc).timestamp()
        mock_chats.return_value = self._bridge_chats([
            {"id": self.CHAT, "timestamp": now - 1000},
        ])
        self.memory.set_whatsapp_handoff("losetaschile", self.CHAT, "motivo previo")
        from api import _pause_chats_on_activation
        paused = _pause_chats_on_activation(self.memory, "losetaschile")
        self.assertEqual(paused, [])
        handoff = self.memory.get_whatsapp_handoff("losetaschile", self.CHAT)
        self.assertEqual(handoff["reason"], "motivo previo")

    @mock.patch("api._whatsapp_web_inbox_request")
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_bridge_down_raises_error(self, mock_provider, mock_chats):
        from api import _pause_chats_on_activation
        mock_chats.side_effect = RuntimeError("Puente WhatsApp Web sin conexión")
        with self.assertRaises(RuntimeError):
            _pause_chats_on_activation(self.memory, "losetaschile")

    @mock.patch("api._whatsapp_web_inbox_request")
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_chats_older_than_window_are_not_paused(self, mock_provider, mock_chats):
        now = datetime.now(timezone.utc).timestamp()
        mock_chats.return_value = self._bridge_chats([
            {"id": self.CHAT, "timestamp": now - 86400 * 10},
        ])
        from api import _pause_chats_on_activation
        paused = _pause_chats_on_activation(self.memory, "losetaschile")
        self.assertEqual(paused, [])

    @mock.patch("api._whatsapp_web_inbox_request")
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_manual_since_limits_window(self, mock_provider, mock_chats):
        # manual_since = 3 days ago → cutoff = 3 days (max of 7 and 3)
        # chat at 2 days → paused; chat at 5 days → NOT paused
        now = datetime.now(timezone.utc).timestamp()
        mock_chats.return_value = self._bridge_chats([
            {"id": self.CHAT, "timestamp": now - 86400 * 2},
            {"id": self.CHAT2, "timestamp": now - 86400 * 5},
        ])
        from api import _pause_chats_on_activation
        paused = _pause_chats_on_activation(self.memory, "losetaschile")
        self.assertEqual(paused, [self.CHAT])

    @mock.patch("api._whatsapp_web_inbox_request")
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_manual_since_older_than_default_extends_window(self, mock_provider, mock_chats):
        # manual_since = 10 days ago → cutoff = 10 days (max of 7 and 10)
        # chat at 5 days → paused (within 10 days)
        self.memory.clients["losetaschile"]["manual_since"] = (
            datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        now = datetime.now(timezone.utc).timestamp()
        mock_chats.return_value = self._bridge_chats([
            {"id": self.CHAT, "timestamp": now - 86400 * 5},
        ])
        from api import _pause_chats_on_activation
        paused = _pause_chats_on_activation(self.memory, "losetaschile")
        self.assertEqual(paused, [self.CHAT])

    @mock.patch("api._whatsapp_web_inbox_request")
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="meta")
    def test_non_web_provider_is_skipped(self, mock_provider, mock_chats):
        from api import _pause_chats_on_activation
        paused = _pause_chats_on_activation(self.memory, "losetaschile")
        self.assertEqual(paused, [])
        mock_chats.assert_not_called()


class SetAgentProfileActivationPauseTest(unittest.TestCase):
    """Integration test for set_agent_profile endpoint."""
    PHONE = "56900000077"
    BOT = "56911111111"
    CHAT = PHONE + "@c.us"
    GROUP = "123456789@g.us"

    def setUp(self):
        self.memory = SessionMemory(None)
        self.memory.register_client("losetaschile", "STARTER")
        self.memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": self.BOT, "response_mode": "manual"})
        self.memory.clients["losetaschile"]["manual_since"] = (
            datetime.now(timezone.utc) - timedelta(days=3)).isoformat()

    @mock.patch("api.make_memory")
    @mock.patch("api._whatsapp_web_inbox_request")
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_endpoint_pauses_chats_and_returns_count(self, mock_provider, mock_chats, mock_make_memory):
        from api import set_agent_profile, AgentProfileBody
        now = datetime.now(timezone.utc).timestamp()
        mock_chats.return_value = {"chats": [
            {"id": self.CHAT, "timestamp": now - 1000},
            {"id": self.GROUP, "timestamp": now - 1000},
        ]}
        mock_make_memory.return_value = self.memory
        body = AgentProfileBody(
            tone="profesional",
            instructions="",
            whatsapp_number=self.BOT,
            quote_mode="automatic",
            response_mode="automatic")
        result = set_agent_profile("losetaschile", body)
        self.assertEqual(result["paused_chats"], 1)
        self.assertEqual(self.memory.get_client_agent_profile("losetaschile")["response_mode"], "automatic")
        self.assertNotIn("manual_since", self.memory.clients.get("losetaschile", {}))

    @mock.patch("api.make_memory")
    @mock.patch("api._whatsapp_web_inbox_request")
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_endpoint_refuses_on_bridge_error(self, mock_provider, mock_chats, mock_make_memory):
        from api import set_agent_profile, AgentProfileBody
        mock_chats.side_effect = RuntimeError("Puente WhatsApp Web sin conexión")
        mock_make_memory.return_value = self.memory
        body = AgentProfileBody(
            tone="profesional",
            instructions="",
            whatsapp_number=self.BOT,
            quote_mode="automatic",
            response_mode="automatic")
        with self.assertRaises(RuntimeError):
            set_agent_profile("losetaschile", body)
        # profile NOT saved
        self.assertEqual(self.memory.get_client_agent_profile("losetaschile")["response_mode"], "manual")

    @mock.patch("api.make_memory")
    @mock.patch("api._whatsapp_web_inbox_request")
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_endpoint_manual_to_manual_no_pause(self, mock_provider, mock_chats, mock_make_memory):
        from api import set_agent_profile, AgentProfileBody
        mock_make_memory.return_value = self.memory
        body = AgentProfileBody(
            tone="profesional",
            instructions="",
            whatsapp_number=self.BOT,
            quote_mode="automatic",
            response_mode="manual")
        result = set_agent_profile("losetaschile", body)
        self.assertEqual(result["paused_chats"], 0)
        mock_chats.assert_not_called()

    @mock.patch("api.make_memory")
    @mock.patch("api._whatsapp_web_inbox_request")
    @mock.patch("zero.client_integrations.whatsapp_provider", return_value="web")
    def test_endpoint_automatic_to_automatic_no_pause(self, mock_provider, mock_chats, mock_make_memory):
        from api import set_agent_profile, AgentProfileBody
        self.memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": self.BOT, "response_mode": "automatic"})
        self.memory.clients["losetaschile"].pop("manual_since", None)
        mock_make_memory.return_value = self.memory
        body = AgentProfileBody(
            tone="profesional",
            instructions="",
            whatsapp_number=self.BOT,
            quote_mode="automatic",
            response_mode="automatic")
        result = set_agent_profile("losetaschile", body)
        self.assertEqual(result["paused_chats"], 0)
        mock_chats.assert_not_called()


if __name__ == "__main__":
    unittest.main()
