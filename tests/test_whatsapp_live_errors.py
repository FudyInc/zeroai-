"""Errores vistos en vivo en el WhatsApp de LosetasChile (2026-10-26/27)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zero.agents import build_agents
from zero.crm import CRM
from zero.losetas_polls import (COLOR_POLL_OPTIONS, COLOR_POLL_QUESTION,
                                CHOICE_SLIP_MARK, DELIVERY_POLL_FACTORY_PICKUP,
                                MENU_ASIDE_CLOSING, PAVER_MODEL_QUESTION, invalid_choice,
                                reasks_open_choice)
from zero.contracts import AgentResponse
from zero.memory import SessionMemory
from zero.orchestrator import Zero


class _LiveChat(unittest.TestCase):
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


class LiveErrorsTest(_LiveChat):
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

    def test_reasks_open_choice_only_when_the_step_would_send_the_menu_again(self):
        history = [{"role": "agent", "text": f"Anoté 20 m². {PAVER_MODEL_QUESTION}"}]
        again = {"reply": f"Anoté 20 m². {PAVER_MODEL_QUESTION}", "customer_poll": "paver_model"}
        self.assertEqual(reasks_open_choice(again, "Tiene otros modelos?", history), "paver_model")
        self.assertIsNone(reasks_open_choice(again, "2", history))  # a real choice
        self.assertIsNone(reasks_open_choice({"reply": "¿Qué color prefieres?"},
                                             "Tiene otros modelos?", history))
        self.assertIsNone(reasks_open_choice(again, "hola", [{"role": "agent", "text": "Hola"}]))

    def test_question_mid_menu_is_answered_and_the_menu_stays_open(self):
        # Live 2026-10-27: «Tiene otros modelos?» got the same list three times.
        sent = []
        self.zero._deliver.side_effect = lambda *a, **k: (
            sent.append(a[3]["body"]) or {"status": "sent", "via": "whatsapp_web"})
        answer = AgentResponse(agent="CONCIERGE", task_id="t", status="ok", result={
            "reply": "También hay Sol rústico y Flor de lis. ¿Te interesa alguno?",
            "intent": "info"})
        with mock.patch("zero.whatsapp_web.send_catalog_document", return_value={"id": "d"}), \
             mock.patch("zero.whatsapp_web.send_catalog_image", return_value={"id": "i"}), \
             mock.patch.object(self.zero, "dispatch", return_value=answer) as dispatch:
            for text in ("Hola", "2", "20"):
                self.inbound(text)
            dispatch.assert_not_called()
            sent.clear()
            self.inbound("Tiene otros modelos?")
            self.assertEqual(len(sent), 1)
            self.assertIn("Flor de lis", sent[0])
            self.assertTrue(sent[0].endswith(MENU_ASIDE_CLOSING))
            self.assertNotIn("¿", sent[0])  # neither the menu nor a question of its own
            self.assertIn(PAVER_MODEL_QUESTION, dispatch.call_args.args[1].instructions)
            result = self.inbound("2")  # still answers the model menu
        self.assertEqual(dispatch.call_count, 1)
        self.assertIn("¿Qué color prefieres?", result["reply"])

    def test_steps_keep_the_menu_open_after_an_aside_or_a_review_notice(self):
        from zero.config import WHATSAPP_REVIEW_NOTICES
        from zero.losetas_polls import open_choice, without_choice_slips
        menu = {"role": "agent", "text": f"Anoté 20 m². {PAVER_MODEL_QUESTION}"}
        history = [menu, {"role": "lead", "text": "mejor 30 m2, ¿tiene otros?"},
                   {"role": "agent", "text": f"Hay Flor de lis.\n\n{MENU_ASIDE_CLOSING}"},
                   {"role": "lead", "text": "y cuánto demora?"},
                   {"role": "agent", "text": WHATSAPP_REVIEW_NOTICES[0]}]
        kept = without_choice_slips(history)
        self.assertEqual(open_choice(kept), "paver_model")
        # The customer's own words stay: they may carry m² or measurements.
        self.assertIn("mejor 30 m2, ¿tiene otros?", [t["text"] for t in kept])

    def test_a_slip_after_an_aside_drops_only_the_wrong_number(self):
        from zero.losetas_polls import open_choice, without_choice_slips
        history = [{"role": "agent", "text": PAVER_MODEL_QUESTION},
                   {"role": "lead", "text": "son 4x8"},
                   {"role": "agent", "text": f"Anotado.\n\n{MENU_ASIDE_CLOSING}"},
                   {"role": "lead", "text": "9"},
                   {"role": "agent", "text": f"El 9 {CHOICE_SLIP_MARK}."}]
        kept = [t["text"] for t in without_choice_slips(history)]
        self.assertEqual(kept, [PAVER_MODEL_QUESTION, "son 4x8"])
        self.assertEqual(open_choice(without_choice_slips(history)), "paver_model")

    def test_a_fixed_shipping_answer_on_the_delivery_menu_is_not_replaced(self):
        from zero.losetas_polls import DELIVERY_POLL_QUESTION
        history = [{"role": "agent", "text": DELIVERY_POLL_QUESTION}]
        result = {"reply": "El despacho se cotiza por separado.", "delivery_poll": True}
        self.assertIsNone(reasks_open_choice(result, "¿cuánto sale el despacho?", history))

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



class SecondLiveTestErrors(_LiveChat):
    """Prueba en vivo del 2026-10-28: m² corregidos, «6 perdón» y un color viejo."""

    def paver_menu(self, area="30"):
        from zero.losetas_polls import PAVER_AREA_QUESTION, PRODUCT_POLL_QUESTION
        return (("agent", f"¡Buenas noches! ¿En qué puedo ayudarte?\n\n{PRODUCT_POLL_QUESTION}"),
                ("lead", "Pastelones"), ("agent", PAVER_AREA_QUESTION), ("lead", area),
                ("agent", f"Anoté {area} m². {PAVER_MODEL_QUESTION}"))

    def history(self):
        return self.memory.get_conversation("losetaschile", "56933333333")

    def test_a_larger_number_on_the_model_menu_corrects_the_area(self):
        from zero.losetas_polls import paver_order_details
        self.turns(*self.paver_menu())
        result = self.zero.converse_result("losetaschile", "80", history=self.history())
        self.assertTrue(result["reply"].startswith("Anoté 80 m²."))
        self.assertEqual(result.get("customer_poll"), "paver_model")
        self.turns(("lead", "80"), ("agent", result["reply"]))
        self.assertEqual(paver_order_details("6", self.history())["area_m2"], "80")

    def test_a_pick_with_an_apology_is_still_a_pick(self):
        from zero.losetas_polls import canonical_choice
        history = [{"role": "agent", "text": PAVER_MODEL_QUESTION}]
        for text in ("6 perdon", "6 perdón", "el 6, disculpa"):
            self.assertEqual(canonical_choice(text, history), "Octagonal Piedra", text)

    def test_a_colour_from_an_earlier_order_does_not_skip_the_colour_question(self):
        self.turns(("agent", COLOR_POLL_QUESTION), ("lead", "Gris"),
                   ("agent", "Gracias, recibí los datos de entrega."), *self.paver_menu())
        result = self.zero.converse_result("losetaschile", "6", history=self.history())
        self.assertEqual(result.get("customer_poll"), "color")

    def test_the_message_that_opened_the_order_stays_in_it(self):
        from zero.losetas_polls import PRODUCT_POLL_QUESTION, current_order
        history = [{"role": "lead", "text": "Gris"}, {"role": "agent", "text": "Gracias."},
                   {"role": "lead", "text": "hola, piscina de 4x8"},
                   {"role": "agent", "text": PRODUCT_POLL_QUESTION}]
        self.assertEqual([t["text"] for t in current_order(history)][0], "hola, piscina de 4x8")

    def test_area_correction_leaves_slips_and_named_models_alone(self):
        from zero.losetas_polls import area_correction
        history = [{"role": "agent", "text": f"Anoté 30 m². {PAVER_MODEL_QUESTION}"}]
        self.assertIsNone(area_correction("7", history))
        self.assertIsNone(area_correction("laja española, 40 m2", history))
        self.assertIsNone(area_correction("el 2, son 30 m2", history))
        self.assertEqual(area_correction("mejor 80", history), "80")

    def test_two_area_corrections_still_reach_the_colour(self):
        self.turns(*self.paver_menu())
        for area in ("80", "100"):
            reply = self.zero.converse_result("losetaschile", area, history=self.history())["reply"]
            self.turns(("lead", area), ("agent", reply))
        result = self.zero.converse_result("losetaschile", "2", history=self.history())
        self.assertEqual(result.get("customer_poll"), "color")


if __name__ == "__main__":
    unittest.main()
