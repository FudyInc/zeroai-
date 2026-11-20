import os
import unittest
from unittest.mock import patch

from tests.test_paver_order_review import _chat, PHONE, BOT, CHAT, GROUP, LOCATION
from tests.test_losetas_review import KNOWLEDGE
from zero.losetas_review import handle_review_message


class OrderChangesTest(unittest.TestCase):
    def setUp(self):
        self.zero = _chat()
        self.mem = self.zero.memory
        self.mem.clients["losetaschile"]["knowledge"] = KNOWLEDGE
        self.group = self.enterContext(patch("zero.whatsapp_web.send_group_text",
            side_effect=lambda *args: {"id": f"g{self.group.call_count}"}))
        self.enterContext(patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": GROUP}))
        for name in ("send_catalog_document", "send_catalog_image"):
            self.enterContext(patch("zero.whatsapp_web." + name, return_value={"id": "cat", "ack": 0}))

    def inbound(self, text):
        return self.zero.handle_inbound(PHONE, text, to_phone_id=BOT, whatsapp_chat_id=CHAT)

    def order(self):
        for text in ("Hola", "Pastelones", "40", "Gregoriano", "amarillo", LOCATION):
            self.inbound(text)
        self.assertEqual(self.group.call_count, 1)

    def review(self, quoted, text):
        handle_review_message(self.mem, {"client":"losetaschile", "quoted_id":quoted,
            "chat_id":GROUP, "to_phone_id":BOT, "text":text})

    def test_corrected_pickup_requires_new_review(self):
        self.order()
        self.inbound("mejor gris y lo retiro yo")
        self.assertEqual(self.group.call_count, 2)
        self.review("g1", "ok")
        self.review("g1", "retiro\nfecha 28/12")
        self.assertEqual(self.group.call_count, 2)
        self.review("g2", "fecha 28/12")
        budget = self.group.call_args_list[2].args[-1]
        for value in ("Gris", "Gregoriano", "Retiro en fábrica: sin costo", "$384.000", "$374.000"):
            self.assertIn(value, budget)

    def test_deposit_requires_human_confirmation(self):
        self.order()
        self.inbound("ya transferí las diez lucas")
        self.assertIn("verificar", self.zero._deliver.call_args.args[3]["body"].lower())
        self.review("g1", "retiro\nfecha 28/12")
        self.assertEqual(self.group.call_count, 2)
        self.assertNotIn("Abono para confirmar", self.group.call_args.args[-1])
        self.review("g1", "abono confirmado $10.000")
        self.assertIn("$374.000", self.group.call_args.args[-1])

    def test_extra_row_preserves_border_context(self):
        self.mem.add_turn("losetaschile", PHONE, "lead", "Bordes para piscina de 8x4")
        self.inbound("quiero una corrida más")
        self.assertIn("un lado", self.zero._deliver.call_args.args[3]["body"])
        self.inbound("solo en un lado")
        self.assertTrue(self.mem.list_knowledge_gaps("losetaschile"))

    def test_manual_payment_report_keeps_manual_mode_and_suppresses_reminder(self):
        self.order()
        self.mem.set_whatsapp_handoff("losetaschile", CHAT, "Atiende el equipo")
        self.zero._deliver.reset_mock()
        self.inbound("ya transferí las diez lucas")
        self.zero._deliver.assert_not_called()
        self.review("g1", "retiro\nfecha 28/12")
        self.assertEqual(self.group.call_count, 2)
        self.assertNotIn("Abono para confirmar", self.group.call_args.args[-1])

    def test_failed_replacement_goes_to_attention_and_old_approval_stays_blocked(self):
        self.order()
        self.group.side_effect = RuntimeError("envío incierto")
        self.inbound("mejor gris y lo retiro yo")
        self.group.reset_mock()
        self.review("g1", "retiro\nfecha 28/12")
        self.group.assert_not_called()
        self.assertTrue(any("reemplazo" in str(gap) for gap in self.mem.list_knowledge_gaps("losetaschile")))

    def test_row_after_border_draft_blocks_old_approval_even_before_answer(self):
        from tests.test_border_review_state import ORDER, PRICING
        self.mem.set_client_pricing("losetaschile", PRICING)
        for text in ORDER:
            self.inbound(text)
        self.assertEqual(self.group.call_count, 1)
        self.inbound("Agréguele otra corrida de pastelones")
        self.assertIn("un lado", self.zero._deliver.call_args.args[3]["body"])
        self.review("g1", "retiro\nfecha 28/12")
        self.assertEqual(self.group.call_count, 1)
        self.inbound("solo en la curva")
        self.assertIn("foto", self.zero._deliver.call_args.args[3]["body"].lower())
        self.assertTrue(self.mem.list_knowledge_gaps("losetaschile"))

    def test_row_with_scope_already_given_goes_directly_to_review(self):
        self.mem.add_turn("losetaschile", PHONE, "lead", "Bordes para piscina de 8x4")
        self.inbound("Quiero una corrida más solo en un lado")
        self.zero._deliver.assert_not_called()
        self.assertTrue(self.mem.list_knowledge_gaps("losetaschile"))

    def test_question_about_price_of_an_extra_row_keeps_draft_valid(self):
        from tests.test_border_review_state import ORDER, PRICING
        self.mem.set_client_pricing("losetaschile", PRICING)
        for text in ORDER:
            self.inbound(text)
        self.inbound("¿Cuánto sale otra corrida?")
        self.review("g1", "retiro\nfecha 28/12")
        self.assertEqual(self.group.call_count, 3)
