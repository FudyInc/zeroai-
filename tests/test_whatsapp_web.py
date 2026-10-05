import hashlib
import hmac
import json
import asyncio
import os
import tempfile
import time
import unittest
from unittest import mock

from fastapi import BackgroundTasks, HTTPException

from zero.channels import make_outbox
from zero.contracts import AgentResponse
from zero.whatsapp_web import (WhatsAppWebSender, claim_event, inbox_stats, parse_message,
                               start_inbox_worker, stop_inbox_worker, verify_signature)


class WhatsAppWebBridgeTest(unittest.TestCase):
    def test_sender_uses_client_bridge_and_rejects_wrong_account(self):
        msg = {"channel": "whatsapp", "client_id": "losetaschile",
               "whatsapp_from": "56964537891", "to": "56911111111", "body": "hola",
               "whatsapp_chat_id": "123456789012345@lid"}
        with mock.patch("zero.whatsapp_web.bridge_request", return_value={
            "state": "ready", "account": "56922222222"}) as bridge:
            failed = WhatsAppWebSender().send(msg)
        self.assertEqual(failed["status"], "error")
        bridge.assert_called_once_with("/status", client_id="losetaschile")
        with mock.patch("zero.whatsapp_web.bridge_request", side_effect=[
            {"state": "ready", "account": "56964537891"}, {"id": "sent", "ack": 1}]) as bridge:
            sent = WhatsAppWebSender().send(msg)
        self.assertEqual(sent["status"], "sent")
        self.assertEqual(bridge.call_args.kwargs["client_id"], "losetaschile")
        self.assertEqual(bridge.call_args.args[1]["chat_id"], "123456789012345@lid")

    def test_concierge_accepts_observed_local_model_envelopes(self):
        for payload in (
            {"response": "Hola, ¿en qué te ayudo?"},
            {"response": {"message": "Hola, ¿en qué te ayudo?"}},
            {"reply": "Hola, ¿en qué te ayudo?"},
        ):
            with self.subTest(payload=payload):
                response = AgentResponse.from_dict(payload, agent="CONCIERGE")
                self.assertEqual(response.status, "done")
                self.assertEqual(response.result["reply"], "Hola, ¿en qué te ayudo?")
        self.assertEqual(AgentResponse.from_dict({"response": "otro"}, agent="ANALYST").status, "error")

    def test_concierge_retries_once_when_model_returns_no_reply(self):
        from zero.agents import build_agents
        from zero.memory import SessionMemory
        from zero.orchestrator import Zero

        backend = mock.Mock()
        backend.complete.side_effect = [
            '{"status":"done","result":{"intent":"general"}}',
            '{"reply":"Hola, ¿en qué te ayudo?","intent":"general"}',
        ]
        zero = Zero(build_agents(backend=backend), memory=SessionMemory(None))
        result = zero.converse_result('', 'hola', channel='whatsapp')
        self.assertEqual(result['reply'], 'Hola, ¿en qué te ayudo?')
        self.assertEqual(backend.complete.call_count, 2)

    def test_signature_and_persistent_deduplication(self):
        secret = "s" * 48
        raw = b'{"id":"wamid-test","from":"56911111111","to_phone_id":"56964537891","text":"hola"}'
        sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {
            "WHATSAPP_WEB_BRIDGE_TOKEN": secret,
            "WHATSAPP_WEB_EVENT_DB": folder + "/events.sqlite3",
        }):
            self.assertTrue(verify_signature(raw, sig))
            self.assertFalse(verify_signature(raw + b" ", sig))
            self.assertEqual(parse_message(json.loads(raw))["text"], "hola")
            self.assertTrue(claim_event("wamid-test"))
            self.assertFalse(claim_event("wamid-test"))

    def test_inbound_requires_a_valid_receiving_number(self):
        base = {"id": "msg-1", "from": "56911111111", "text": "hola"}
        for destination in (None, "", "otro", "123"):
            with self.subTest(destination=destination):
                self.assertIsNone(parse_message({**base, "to_phone_id": destination}))
        self.assertEqual(parse_message({**base, "to_phone_id": "56964537891"})["to_phone_id"],
                         "56964537891")
        self.assertEqual(parse_message({**base, "to_phone_id": "56964537891",
                                        "chat_id": "123456789012345@lid"})["chat_id"],
                         "123456789012345@lid")
        self.assertIsNone(parse_message({**base, "to_phone_id": "56964537891",
                                          "chat_id": "123456789012345@g.us"}))

    def test_default_client_cannot_start_a_second_session(self):
        from zero.whatsapp_web import _client_ports
        from zero.config import DEFAULT_INBOUND_CLIENT_ID
        with mock.patch.dict(os.environ, {"WHATSAPP_WEB_CLIENT_PORTS": json.dumps({DEFAULT_INBOUND_CLIENT_ID: 8811})}):
            with self.assertRaisesRegex(RuntimeError, "WHATSAPP_WEB_CLIENT_PORTS"):
                _client_ports()

    def test_inbox_checks_client_number_before_reading_or_sending(self):
        import api
        memory = mock.Mock()
        memory.get_client_agent_profile.return_value = {"whatsapp_number": "56964537891"}
        with mock.patch.dict(os.environ, {"WHATSAPP_PROVIDER": "web"}), \
             mock.patch.object(api, "make_memory", return_value=memory), \
             mock.patch("zero.whatsapp_web.bridge_request", return_value={
                 "state": "ready", "account": "56922222222"}) as bridge:
            with self.assertRaises(HTTPException) as rejected:
                api.whatsapp_web_chats("losetaschile")
            self.assertEqual(rejected.exception.status_code, 409)
            bridge.assert_called_once_with("/status", client_id="losetaschile")

    def test_manual_reply_uses_confirmed_send_and_rejects_group_chats(self):
        import api
        memory = mock.Mock()
        memory.get_client_agent_profile.return_value = {"whatsapp_number": "56964537891"}
        with mock.patch.dict(os.environ, {"WHATSAPP_PROVIDER": "web"}), \
             mock.patch.object(api, "make_memory", return_value=memory), \
             mock.patch.object(api, "make_crm") as crm, \
             mock.patch("zero.whatsapp_web.bridge_request", side_effect=[
                 {"state": "ready", "account": "56964537891"},
                 {"id": "wamid-confirmed", "ack": 1},
             ]) as bridge:
            result = api.whatsapp_web_reply("56911111111@c.us", api.WhatsAppWebReply(text=" hola "), client="losetaschile")
            self.assertEqual(result["id"], "wamid-confirmed")
            bridge.assert_any_call("/send", {"to": "56911111111", "text": "hola",
                                             "chat_id": "56911111111@c.us"}, client_id="losetaschile")
            crm.return_value.find_by_contact.assert_called_once_with(phone="56911111111", client_id="losetaschile")
        with self.assertRaises(HTTPException) as rejected:
            api.whatsapp_web_reply("123456789@g.us", api.WhatsAppWebReply(text="hola"), client="losetaschile")
        self.assertEqual(rejected.exception.status_code, 400)

    def test_manual_reply_requires_bridge_acceptance(self):
        import api
        memory = mock.Mock()
        memory.get_client_agent_profile.return_value = {"whatsapp_number": "56964537891"}
        with mock.patch.dict(os.environ, {"WHATSAPP_PROVIDER": "web"}), \
             mock.patch.object(api, "make_memory", return_value=memory), \
             mock.patch.object(api, "make_crm") as crm, \
             mock.patch("zero.whatsapp_web.bridge_request", side_effect=[
                 {"state": "ready", "account": "56964537891"}, {"ack": -1},
             ]):
            with self.assertRaises(HTTPException) as rejected:
                api.whatsapp_web_reply("56911111111@c.us", api.WhatsAppWebReply(text="hola"), client="losetaschile")
            self.assertEqual(rejected.exception.status_code, 502)
            crm.assert_not_called()

    def test_inbox_upgrade_preserves_existing_messages(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {
            "WHATSAPP_WEB_EVENT_DB": folder + "/events.sqlite3",
        }):
            with sqlite3.connect(folder + "/events.sqlite3") as db:
                db.execute("CREATE TABLE received (id TEXT PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP)")
                db.execute("INSERT INTO received(id) VALUES ('old-message')")
            self.assertEqual(inbox_stats()["counts"], {"completed": 1})
            with sqlite3.connect(folder + "/events.sqlite3") as db:
                self.assertEqual(db.execute("SELECT updated FROM received WHERE id='old-message'").fetchone()[0],
                                 db.execute("SELECT created FROM received WHERE id='old-message'").fetchone()[0])
            self.assertFalse(claim_event("old-message"))

    def test_webhook_rejects_unsigned_and_processes_only_once(self):
        import api
        class Request:
            def __init__(self, raw, signature=None):
                self.raw = raw
                self.headers = {"x-zero-signature": signature} if signature else {}

            async def body(self):
                return self.raw

        secret = "s" * 48
        raw = b'{"id":"wamid-test","from":"56911111111","to_phone_id":"56964537891","text":"hola"}'
        sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {
            "WHATSAPP_PROVIDER": "web", "WHATSAPP_WEB_BRIDGE_TOKEN": secret,
            "WHATSAPP_WEB_EVENT_DB": folder + "/events.sqlite3",
        }):
            with self.assertRaises(HTTPException) as rejected:
                asyncio.run(api.whatsapp_web_inbound(Request(raw), BackgroundTasks()))
            self.assertEqual(rejected.exception.status_code, 403)
            no_destination = b'{"id":"missing-destination","from":"56911111111","text":"hola"}'
            signed = "sha256=" + hmac.new(secret.encode(), no_destination, hashlib.sha256).hexdigest()
            with self.assertRaises(HTTPException) as rejected:
                asyncio.run(api.whatsapp_web_inbound(Request(no_destination, signed), BackgroundTasks()))
            self.assertEqual(rejected.exception.status_code, 400)
            tasks = BackgroundTasks()
            first = asyncio.run(api.whatsapp_web_inbound(Request(raw, sig), tasks))
            self.assertEqual(first["received"], 1)
            self.assertEqual(len(tasks.tasks), 0)
            self.assertEqual(inbox_stats()["counts"].get("pending"), 1)
            second = asyncio.run(api.whatsapp_web_inbound(Request(raw, sig), BackgroundTasks()))
            self.assertTrue(second["duplicate"])

    def test_pending_message_survives_and_failed_send_needs_review(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {
            "WHATSAPP_PROVIDER": "web", "WHATSAPP_WEB_EVENT_DB": folder + "/events.sqlite3",
        }):
            self.assertTrue(claim_event("one", {"id": "one", "from": "56911111111", "text": "hola"}))
            seen = []
            def process(messages):
                seen.extend(messages)
                return [{"matched": True, "delivery": {"status": "error", "error": "puente caído"}}]
            start_inbox_worker(process)
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not inbox_stats()["counts"].get("needs_review"):
                    time.sleep(0.02)
                self.assertEqual([m["id"] for m in seen], ["one"])
                self.assertEqual(inbox_stats()["counts"].get("needs_review"), 1)
                self.assertFalse(claim_event("one", seen[0]))
            finally:
                stop_inbox_worker()

    def test_worker_completes_accepted_message(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {
            "WHATSAPP_PROVIDER": "web", "WHATSAPP_WEB_EVENT_DB": folder + "/events.sqlite3",
        }):
            claim_event("two", {"id": "two", "from": "56911111111", "text": "hola"})
            start_inbox_worker(lambda messages: [{"matched": True, "delivery": {"status": "sent", "via": "whatsapp_web"}}])
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and not inbox_stats()["counts"].get("completed"):
                    time.sleep(0.02)
                self.assertEqual(inbox_stats()["counts"].get("completed"), 1)
            finally:
                stop_inbox_worker()

    def test_web_provider_blocks_campaigns_and_ignores_meta_vendor_credentials(self):
        with mock.patch.dict(os.environ, {
            "OUTBOX_LIVE": "1", "WHATSAPP_PROVIDER": "web",
            "WHATSAPP_WEB_BRIDGE_TOKEN": "s" * 48,
            "WHATSAPP_TOKEN": "meta-token", "WHATSAPP_PHONE_ID": "123",
        }):
            outbox = make_outbox()
            self.assertEqual(outbox.retry_attempts, 1)
            self.assertIsInstance(outbox._sender_for("whatsapp", ("123", "meta-token")), WhatsAppWebSender)
            result = outbox.send({"channel": "whatsapp", "to": "+56911111111", "body": "hola",
                                  "whatsapp_send_type": "template"}, wa_creds=("123", "meta-token"))
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["via"], "whatsapp_web")
            with mock.patch("zero.whatsapp_web.bridge_request", side_effect=TimeoutError("confirmación tardía")) as bridge:
                failed = outbox.send({"channel": "whatsapp", "to": "+56911111111", "body": "hola"})
            self.assertEqual(failed["status"], "error")
            self.assertEqual(bridge.call_count, 1)
            with mock.patch("zero.whatsapp_web.bridge_request", return_value={"id": "msg-1", "ack": 1}):
                accepted = outbox.send({"channel": "whatsapp", "to": "+56911111111", "body": "hola"})
            self.assertEqual(accepted["delivery_status"], "accepted")
            self.assertEqual(accepted["ack"], 1)
            with mock.patch("zero.whatsapp_web.bridge_request", return_value={"id": "msg-2", "ack": -1}):
                rejected = outbox.send({"channel": "whatsapp", "to": "+56911111111", "body": "hola"})
            self.assertEqual(rejected["status"], "error")


if __name__ == "__main__":
    unittest.main()
