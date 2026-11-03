"""La pregunta por la ubicación de la fábrica se responde con la dirección confirmada."""
import unittest
from unittest import mock

from zero.agents import build_agents
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


if __name__ == "__main__":
    unittest.main()
