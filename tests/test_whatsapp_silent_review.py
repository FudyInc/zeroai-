"""Pending internal work must not produce filler in a customer chat."""
import os
import unittest
from unittest import mock
from zero.contracts import AgentResponse
from zero.losetas_polls import FACTORY_ADDRESS
from tests.test_paver_order_review import _chat, PHONE, BOT, CHAT, GROUP, LOCATION


class SilentReviewTest(unittest.TestCase):
    def setUp(self):
        self.zero = _chat()
        self.memory = self.zero.memory

    def inbound(self, message):
        return self.zero.handle_inbound(PHONE, message, to_phone_id=BOT, whatsapp_chat_id=CHAT)

    def test_unknown_question_opens_internal_attention_without_a_notice(self):
        answer = AgentResponse("test", "CONCIERGE", "done", {"reply": "", "intent": "handoff"})
        with mock.patch.object(self.zero, "dispatch", return_value=answer):
            result = self.inbound("¿Qué garantía ofrecen?")
        self.assertTrue(result.get("manual_review"))
        self.zero._deliver.assert_not_called()
        self.assertTrue(self.memory.list_knowledge_gaps("losetaschile"))
        self.assertFalse(any(t["role"] == "agent" for t in self.memory.get_conversation("losetaschile", PHONE)))

    def test_plain_greeting_asks_the_needed_question_without_a_thank_you(self):
        self.inbound("Hola")
        body = self.zero._deliver.call_args.args[3]["body"]
        self.assertRegex(body, r"^¡Buenas|^¡Buenos")
        self.assertIn("¿Qué producto está buscando?", body)
        self.assertNotIn("gracias", body.casefold())

    def test_model_written_review_notice_is_also_silent(self):
        for reply in ("Recibí su mensaje. Voy a revisar su consulta y le respondo por este chat.",
                      "Gracias por escribir a PoolEdge."):
            with self.subTest(reply=reply), mock.patch.object(self.zero, "converse_result",
                    return_value={"reply": reply, "intent": "info"}):
                result = self.inbound("¿Qué pasó con mi pedido?")
                self.assertTrue(result.get("manual_review"))
                self.zero._deliver.assert_not_called()
                self.assertTrue(self.memory.list_knowledge_gaps("losetaschile"))

    def test_known_location_is_still_answered_and_greeted(self):
        self.inbound("Hola, ¿de dónde son?")
        body = self.zero._deliver.call_args.args[3]["body"]
        self.assertIn(FACTORY_ADDRESS, body)
        self.assertRegex(body, r"^¡Buenas|^¡Buenos")

    def test_requested_human_is_internal_and_pauses_without_an_ack(self):
        with mock.patch.object(self.zero, "_alert_owner_handoff"):
            result = self.inbound("Quiero hablar con una persona")
        self.assertTrue(result.get("manual_review"))
        self.zero._deliver.assert_not_called()
        self.assertTrue(self.memory.get_whatsapp_handoff("losetaschile", CHAT))
        self.assertTrue(self.memory.list_knowledge_gaps("losetaschile"))

    def test_duplicate_budget_remains_silent_after_review_metadata_expires(self):
        from datetime import datetime, timezone, timedelta
        from zero import config
        with mock.patch("zero.whatsapp_web.send_catalog_document", return_value={"id":"doc","ack":0}), \
             mock.patch("zero.whatsapp_web.send_catalog_image", return_value={"id":"img","ack":0}), \
             mock.patch("zero.whatsapp_web.send_group_text", return_value={"id":"draft","ack":0}) as group, \
             mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID":GROUP}):
            for message in ["Hola", "Pastelones", "40", "Gregoriano", "amarillo", LOCATION]:
                self.inbound(message)
            self.memory.lead_notes("losetaschile", PHONE)["budget_review"]["at"] = (
                datetime.now(timezone.utc) - timedelta(hours=config.LOSETASCHILE_PAVER_REVIEW_STATE_HOURS+1)
            ).isoformat()
            self.zero._deliver.reset_mock()
            self.inbound(LOCATION)
            self.zero._deliver.assert_not_called()
            self.assertEqual(group.call_count, 1)

    def test_review_draft_and_followup_are_silent_without_losing_order_state(self):
        with mock.patch("zero.whatsapp_web.send_catalog_document", return_value={"id":"doc","ack":0}), \
             mock.patch("zero.whatsapp_web.send_catalog_image", return_value={"id":"img","ack":0}), \
             mock.patch("zero.whatsapp_web.send_group_text", return_value={"id":"draft","ack":0}) as group, \
             mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID":GROUP}):
            for message in ["Hola", "Pastelones", "40", "Gregoriano", "amarillo"]:
                self.inbound(message)
            self.zero._deliver.reset_mock()
            result = self.inbound(LOCATION)
            self.assertEqual(result["delivery"]["status"], "accepted")
            self.zero._deliver.assert_not_called()
            self.assertEqual(group.call_count, 1)
            self.inbound("¿Cuándo me llega el presupuesto?")
            self.zero._deliver.assert_not_called()
            self.assertEqual(group.call_count, 1)
            self.assertTrue(self.memory.list_knowledge_gaps("losetaschile"))


if __name__ == "__main__":
    unittest.main()
