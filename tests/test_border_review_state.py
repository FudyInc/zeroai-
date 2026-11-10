"""A border budget in review answers follow-ups with its status, not with the model.

Live chat 2026-11-09 (Diego testing): bordes, 7x3,50, recto, beige, location. The
acknowledgment said «pendiente de revisión por nuestro equipo», which nothing read:
the «1» right after it went to the model, which asked «¿a qué te refieres con 1?»;
«Estabamos en un presupuesto» later restarted the catalog.
"""
import os
import unittest
from unittest import mock

from zero.agents import build_agents
from zero.crm import CRM
from zero.losetas_polls import border_review_sentence, paver_review_reply, review_thanks
from zero.memory import SessionMemory
from zero.orchestrator import Zero

PHONE = "56900000002"
BOT = "56911111111"
GROUP = "123456789@g.us"
CHAT = PHONE + "@c.us"
LOCATION = "[location] https://www.google.com/maps?q=-33.437248,-70.577911"
STATUS = "Tu presupuesto de bordes de piscina beige con despacho está en revisión del equipo"
PRICING = {"currency": "CLP", "iva_rate": 0, "items": [
    {"id": "borde-recto-nariz-50x50", "name": "Borde recto con nariz 50x50",
     "unit_price": 3000, "unit": "unidad"},
    {"id": "borde-ballena-50x40", "name": "Borde ballena 50x40", "unit_price": 2800,
     "unit": "unidad"},
    {"id": "esquina-piscina-50x50", "name": "Esquina piscina 50x50", "unit_price": 3600,
     "unit": "unidad"}]}
ORDER = ["Hola", "1", "7x3,50", "1", "5", LOCATION]


class BorderReviewStateTest(unittest.TestCase):
    def run_chat(self, messages):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": BOT, "response_mode": "automatic"})
        memory.set_client_pricing("losetaschile", PRICING)
        crm = CRM(None)
        crm.upsert("losetaschile", {"phone": PHONE, "source": "test"})
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web"})
        sent = {"id": "x", "ack": 0}
        bodies = []
        with mock.patch("zero.whatsapp_web.send_catalog_document", return_value=sent), \
                mock.patch("zero.whatsapp_web.send_catalog_image", return_value=sent), \
                mock.patch("zero.whatsapp_web.send_choice_poll", return_value=sent), \
                mock.patch("zero.whatsapp_web.send_delivery_poll", return_value=sent), \
                mock.patch("zero.whatsapp_web.send_group_text",
                           return_value={"id": "group-1", "ack": 0}) as group, \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": GROUP}), \
                mock.patch.object(zero, "dispatch"):
            for text in messages:
                before = zero._deliver.call_count
                zero.handle_inbound(PHONE, text, to_phone_id=BOT, whatsapp_chat_id=CHAT)
                bodies.append(zero._deliver.call_args.args[3]["body"]
                              if zero._deliver.call_count > before else "")
        self.zero, self.group = zero, group
        return bodies

    def test_the_order_reaches_the_group_and_the_ack_states_the_review(self):
        bodies = self.run_chat(ORDER)
        self.assertEqual(self.group.call_count, 1)
        self.assertIn(STATUS, bodies[-1])

    def test_live_follow_ups_get_the_status_not_the_model(self):
        follow_ups = ["1", "No entendi", "Estabamos en un presupuesto", "Alo?", "Hola"]
        bodies = self.run_chat(ORDER + follow_ups)
        for text, body in zip(follow_ups, bodies[len(ORDER):]):
            with self.subTest(text=text):
                self.assertIn(STATUS, body)
                self.assertNotIn("¿Qué producto estás buscando?", body)
                self.assertNotIn("Gracias, lo anoté", body)
        self.assertEqual(self.group.call_count, 1)

    def test_thanks_after_the_status_is_not_taken_as_accepting_an_offer(self):
        # The status reply used to leave a pending «info» offer: «Okay gracias» then
        # got the generic info summary instead of the status.
        bodies = self.run_chat(ORDER + ["1", "Okay gracias", "Bkn"])
        for body in bodies[-2:]:
            self.assertTrue(body.startswith("Gracias, lo anoté."), body)
            self.assertIn(STATUS, body)

    def test_a_new_request_still_goes_through_the_flow(self):
        bodies = self.run_chat(ORDER + ["quiero cotizar pastelones"])
        self.assertNotIn(STATUS, bodies[-1])


class ReviewHelpersTest(unittest.TestCase):
    def test_border_sentence_mentions_delivery_only_when_known(self):
        self.assertEqual(border_review_sentence("Gris", None),
                         "Tu presupuesto de bordes de piscina gris está en revisión del equipo;"
                         " te escribimos por este chat.")
        self.assertIn("con retiro en fábrica",
                      border_review_sentence(None, "Retiro en fábrica: Los Granados 029"))

    def test_thanks_only_for_acknowledgements(self):
        for text in ("ok gracias", "Bkn", "Fantástico", "👍", "listo"):
            self.assertTrue(review_thanks(text), text)
        for text in ("1", "no entendí", "alo?", "quiero pastelones"):
            self.assertFalse(review_thanks(text), text)

    def test_without_review_state_nothing_is_answered(self):
        self.assertIsNone(paver_review_reply("1", [{"role": "agent", "text": "Hola"}]))


if __name__ == "__main__":
    unittest.main()
