"""Errores vistos en vivo en el WhatsApp de LosetasChile (2026-10-26/27)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zero.agents import build_agents
from zero.crm import CRM
from zero.losetas_polls import (COLOR_POLL_OPTIONS, COLOR_POLL_QUESTION,
                                CHOICE_SLIP_MARK, DELIVERY_POLL_FACTORY_PICKUP,
                                invalid_choice)
from zero.memory import SessionMemory
from zero.orchestrator import Zero


class LiveErrorsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.memory = SessionMemory(str(Path(tmp.name) / "state.json"))
        self.memory.register_client("losetaschile", "STARTER")
        self.memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        self.crm = CRM(None)
        self.crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
        self.zero = Zero(build_agents(mock=True), memory=self.memory, crm=self.crm)
        self.zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web"})

    def inbound(self, text):
        return self.zero.handle_inbound("56933333333", text, to_phone_id="56911111111",
                                        whatsapp_chat_id="56933333333@c.us")

    def turns(self, *pairs):
        for role, text in pairs:
            self.memory.add_turn("losetaschile", "56933333333", role, text)

    def sent(self):
        return [c.args[3]["body"] for c in self.zero._deliver.call_args_list]

    def test_number_outside_the_colour_list_asks_for_a_valid_option(self):
        self.turns(("lead", "Pastelones"),
                   ("agent", f"Te comparto la gama de colores. {COLOR_POLL_QUESTION}"))
        result = self.zero.converse_result(
            "losetaschile", "8", history=self.memory.get_conversation("losetaschile", "56933333333"))
        self.assertIn(CHOICE_SLIP_MARK, result["reply"])
        self.assertIn(f"del 1 al {len(COLOR_POLL_OPTIONS)}", result["reply"])
        self.assertNotIn(COLOR_POLL_QUESTION, result["reply"])
        self.assertIsNone(result.get("customer_poll"))

    def test_slip_notice_reads_keycaps_and_short_lists_plainly(self):
        from zero.losetas_polls import choice_slip_reply
        history = [{"role": "agent", "text": COLOR_POLL_QUESTION}]
        self.assertEqual(invalid_choice("9️⃣", history), "color")
        self.assertIsNone(invalid_choice("6️⃣", history))
        self.assertEqual(choice_slip_reply("9️⃣", "color"),
                         f"El 9 {CHOICE_SLIP_MARK}. Elige un número del 1 al 7.")
        self.assertTrue(choice_slip_reply("5", "product").endswith("Elige 1 o 2."))

    def test_after_a_slip_the_next_valid_number_answers_the_open_question(self):
        sent = []
        self.zero._deliver.side_effect = lambda *a, **k: (
            sent.append(a[3]["body"]) or {"status": "sent", "via": "whatsapp_web"})
        with mock.patch("zero.whatsapp_web.send_catalog_document", return_value={"id": "d"}), \
             mock.patch("zero.whatsapp_web.send_catalog_image", return_value={"id": "i"}), \
             mock.patch.object(self.zero, "dispatch", side_effect=AssertionError("LLM")):
            for text in ("Hola", "2", "20", "1"):
                self.inbound(text)
            sent.clear()
            self.inbound("9")
            self.assertEqual(len(sent), 1)
            self.assertIn(CHOICE_SLIP_MARK, sent[0])
            self.assertNotIn("¿", sent[0])
            sent.clear()
            self.inbound("6")
        self.assertIn("color gris", sent[0])
        self.assertIn("recibir tu pedido", sent[0])

    def test_invalid_choice_only_for_bare_numbers_outside_the_open_list(self):
        history = [{"role": "agent", "text": COLOR_POLL_QUESTION}]
        self.assertEqual(invalid_choice("8", history), "color")
        self.assertEqual(invalid_choice(" 9 ", history), "color")
        self.assertIsNone(invalid_choice("20", history))  # m² or a quantity, not a slip
        answered = [{"role": "agent", "text": COLOR_POLL_QUESTION},
                    {"role": "lead", "text": "Gris"}]
        self.assertIsNone(invalid_choice("9", answered))
        self.assertIsNone(invalid_choice(str(len(COLOR_POLL_OPTIONS)), history))
        self.assertIsNone(invalid_choice("14", [{"role": "agent", "text": "¿Cuántos m²?"}]))
        self.assertIsNone(invalid_choice("8 metros", history))

    def test_asking_for_a_superior_hands_the_chat_to_a_person(self):
        result = self.inbound("contactame con unsuperior no me servis")
        self.assertEqual(result["intent"], "handoff")
        self.assertIsNotNone(self.memory.get_whatsapp_handoff("losetaschile", "56933333333@c.us"))

    def test_an_insult_hands_the_chat_to_a_person_without_replying(self):
        result = self.inbound("en la puta que te pario")
        self.assertEqual(result["intent"], "handoff")
        self.assertEqual(self.sent(), [])

    def test_a_product_complaint_is_not_mistaken_for_anger(self):
        from zero.orchestrator import _UPSET_RE
        for text in ("no me sirve el color rojo", "el despacho llegó inútil"):
            self.assertIsNone(_UPSET_RE.search(text), text)

    def test_ordinary_mentions_of_people_are_not_handoffs(self):
        from zero.orchestrator import _HUMAN_REQUEST_RE
        for text in ("hablo con alguien de la obra", "habla con el dueño del terreno"):
            self.assertIsNone(_HUMAN_REQUEST_RE.search(text), text)
        self.assertIsNotNone(_HUMAN_REQUEST_RE.search("pásame con el encargado"))

    def test_factory_pickup_on_pastelones_does_not_mention_a_location(self):
        history = [{"role": "lead", "text": "Pastelones"},
                   {"role": "agent", "text": "¿Cuántos m² necesitas cubrir con pastelones?"},
                   {"role": "lead", "text": "14"},
                   {"role": "lead", "text": "Laja española"},
                   {"role": "lead", "text": "Anaranjado"},
                   {"role": "agent", "text": "Anoté el color anaranjado. ¿Cómo prefieres recibir tu pedido?"}]
        result = self.zero.converse_result("losetaschile", DELIVERY_POLL_FACTORY_PICKUP,
                                           history=history)
        self.assertIn("retiro en fábrica", result["reply"])
        self.assertNotIn("ubicación", result["reply"])
        self.assertNotIn("tamaño del modelo", result["reply"])


if __name__ == "__main__":
    unittest.main()
