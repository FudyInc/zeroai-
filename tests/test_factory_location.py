"""La pregunta por la ubicación de la fábrica se responde con la dirección confirmada."""
import unittest
from unittest import mock

from zero.agents import build_agents
from zero.crm import CRM
from zero.losetas_polls import FACTORY_ADDRESS, FACTORY_MAP_URL
from zero.losetas_shipping import factory_location_question, factory_location_reply
from zero.memory import SessionMemory
from zero.orchestrator import Zero


class FactoryLocationQuestionTest(unittest.TestCase):
    def test_questions_about_the_factory(self):
        for text in ("Cuál es su ubicación ?", "¿Cuál es su dirección?",
                     "¿Dónde están ubicados?", "donde quedan?", "Dónde está la fábrica",
                     "¿Dónde puedo retirar?", "¿Dónde retiro?", "Dirección de la fábrica?",
                     "¿Tienen local?", "Hola, donde se encuentran?", "dónde está su fábrica",
                     "Dónde está ubicada la fábrica", "¿Dónde retiro mi pedido?",
                     "en qué comuna están?", "de dónde son?", "Donde estan ubicados"):
            with self.subTest(text=text):
                self.assertTrue(factory_location_question(text))

    def test_not_the_customer_address_nor_shipping(self):
        for text in ("Mi dirección es Pasaje 3, Maipú", "estoy en La Florida",
                     "[location] https://www.google.com/maps?q=-33.5,-70.6",
                     "¿Hacen despacho a Puente Alto?", "¿Dónde lo envían?",
                     "¿Cuánto cuesta el envío a mi dirección?", "¿Dónde está mi pedido?",
                     "Ubicación?", "📍 Despacho · compartir ubicación",
                     "✍️ Despacho · escribir dirección", "¿Cuál es el precio?", "",
                     # Revisión 2026-11-03: pedido, catálogo, trámites y sucursales.
                     "dónde están mis losetas", "¿Dónde están las fotos?",
                     "Dónde quedan los precios", "Dónde retiro el comprobante",
                     "tienen tienda online?", "tienen local en Puente Alto?",
                     "¿Cuál es la dirección?", "¿Dónde retiro? vivo en Maipú"):
            with self.subTest(text=text):
                self.assertFalse(factory_location_question(text))

    def test_reply_carries_address_and_map(self):
        reply = factory_location_reply()
        self.assertIn("Los Granados 029, La Pintana", reply)
        self.assertEqual(FACTORY_ADDRESS, "Los Granados 029, La Pintana")
        self.assertTrue(FACTORY_MAP_URL.startswith("https://maps.app.goo.gl/"))
        self.assertIn(FACTORY_MAP_URL, reply)


class FactoryLocationReplyTest(unittest.TestCase):
    def setUp(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        self.zero = Zero(build_agents(mock=True), memory=memory)

    def test_answer_never_reaches_the_model(self):
        with mock.patch.object(self.zero, "dispatch") as dispatch:
            result = self.zero.converse_result(
                "losetaschile", "Cuál es su ubicación ?",
                lead={"key": "test-lead"}, channel="whatsapp", history=[])
        dispatch.assert_not_called()
        self.assertEqual(result["reply"], factory_location_reply())
        self.assertEqual(result["aside"], "verbatim")
        self.assertNotIn("Santiago, Chile", result["reply"])

    def test_mid_order_question_keeps_the_order(self):
        history = [{"role": "lead", "text": "Quiero pastelones"},
                   {"role": "agent", "text": "¿Cuántos m² necesitas cubrir?"}]
        with mock.patch.object(self.zero, "dispatch") as dispatch:
            result = self.zero.converse_result(
                "losetaschile", "¿Dónde están ubicados?",
                lead={"key": "test-lead"}, channel="whatsapp", history=history)
        dispatch.assert_not_called()
        self.assertIn(FACTORY_ADDRESS, result["reply"])
        self.assertTrue(result.get("flow_step"))


class ReturningCustomerGreetingTest(unittest.TestCase):
    def setUp(self):
        self.memory = SessionMemory(None)
        self.memory.register_client("losetaschile", "STARTER")
        self.memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        self.phone = "56900000077"
        crm = CRM(None)
        crm.upsert("losetaschile", {"phone": self.phone, "source": "test"})
        self.zero = Zero(build_agents(mock=True), memory=self.memory, crm=crm)
        self.sent = []
        def deliver(client, key, to, message, **kwargs):
            self.sent.append(message["body"])
            return {"status": "sent", "via": "test"}
        self.zero._deliver = deliver

    def ask(self, text, previous=True):
        if previous:
            self.memory.add_turn("losetaschile", self.phone, "lead", "Bordes de piscina")
            self.memory.add_turn("losetaschile", self.phone, "agent",
                                 "¿Cómo prefiere recibir su pedido?")
        with mock.patch("zero.orchestrator.whatsapp_greeting", return_value="Buenas tardes"):
            self.zero.handle_inbound(self.phone, text, to_phone_id="56911111111",
                                     whatsapp_chat_id=self.phone + "@c.us")
        return self.sent[-1]

    def test_returning_customer_greeting_with_location_question_gets_a_greeting(self):
        for text in ("Hola de donde son?", "Buenas tardes, ¿dónde están ubicados?"):
            with self.subTest(text=text):
                reply = self.ask(text)
                self.assertRegex(reply, r"^¡Buenas tardes!")
                self.assertIn("Los Granados 029, La Pintana", reply)
                self.assertIn(FACTORY_MAP_URL, reply)
                self.assertEqual(reply.count("Buenas tardes"), 1)

    def test_mid_order_location_question_without_greeting_does_not_restart_chat(self):
        reply = self.ask("¿Dónde están ubicados?")
        self.assertTrue(reply.startswith("Nuestra fábrica"))
        self.assertNotIn("Buenas tardes", reply)

    def test_first_location_question_still_greets(self):
        reply = self.ask("¿Dónde están ubicados?", previous=False)
        self.assertRegex(reply, r"^¡Buenas tardes!")
        self.assertIn(FACTORY_MAP_URL, reply)


if __name__ == "__main__":
    unittest.main()
