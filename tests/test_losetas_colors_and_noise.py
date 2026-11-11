"""Dos respuestas que no pasan por el modelo (prueba de motores del 2026-11-11).

- «¿Qué colores tienen?» recibe la gama con su imagen. Sonnet 5.5 contestó
  «no tengo confirmados los colores», con la gama ya definida.
- Un mensaje que no se entiende («asdkj 3e ...») se deriva a una persona.
  Sonnet 5.5 le pidió aclarar al cliente; la regla es derivar.
"""
import unittest
from unittest import mock

from zero.agents import build_agents
from zero.losetas_color import (COLOR_CATALOG_IMAGE_PATH, COLOR_NAMES, asks_for_colors,
                                color_preference, color_range_reply)
from zero.memory import SessionMemory
from zero.orchestrator import Zero, _unreadable_whatsapp_message


class ColorsQuestionTest(unittest.TestCase):

    def test_questions_about_the_range(self):
        for text in ("qué colores tienen los bordes?", "Qué colores tienen?", "colores?",
                     "y los colores?", "en qué colores vienen", "hay otros colores?",
                     "cuáles son los colores disponibles", "me muestras los colores",
                     "que colores hay", "los colores que tienen"):
            with self.subTest(text=text):
                self.assertTrue(asks_for_colors(text))

    def test_other_questions_keep_their_flow(self):
        for text in ("blanco", "quiero color gris", "el color se destiñe?",
                     "qué colores tienen y cuánto cuestan?", "tienen stock en gris?",
                     "de qué color es el ballena 1?", "colores para 8x4", "", "hola",
                     "mejor con otro color", "cambio a otro color"):
            with self.subTest(text=text):
                self.assertFalse(asks_for_colors(text))

    def test_reply_lists_every_color_without_claiming_stock(self):
        reply = color_range_reply()
        for name in COLOR_NAMES:
            self.assertIn(name, reply)
        self.assertNotRegex(reply.casefold(), r"stock|disponib|tenemos")

    def test_a_color_after_the_range_is_the_customer_choice(self):
        history = [{"role": "agent", "text": color_range_reply()}]
        self.assertEqual(color_preference("el gris", history), "gris")


class ColorsReplyTest(unittest.TestCase):
    def setUp(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        self.zero = Zero(build_agents(mock=True), memory=memory)

    def _ask(self, text, history):
        with mock.patch.object(self.zero, "dispatch") as dispatch:
            result = self.zero.converse_result(
                "losetaschile", text, lead={"key": "test-lead"}, channel="whatsapp",
                history=history)
        dispatch.assert_not_called()
        return result

    def test_first_message_gets_the_image(self):
        result = self._ask("qué colores tienen los bordes?", [])
        self.assertEqual(result["reply"], color_range_reply())
        self.assertEqual(result["media_asset"], COLOR_CATALOG_IMAGE_PATH)
        self.assertEqual(result["aside"], "verbatim")

    def test_mid_order_question_keeps_the_order(self):
        history = [{"role": "lead", "text": "Quiero bordes"},
                   {"role": "agent", "text": "¿Cuáles son las medidas de tu piscina?"}]
        result = self._ask("¿Qué colores hay?", history)
        self.assertEqual(result["media_asset"], COLOR_CATALOG_IMAGE_PATH)
        self.assertTrue(result.get("flow_step"))

    def test_other_businesses_are_untouched(self):
        memory = SessionMemory(None)
        memory.register_client("petlabs", "STARTER")
        zero = Zero(build_agents(mock=True), memory=memory)
        result = zero.converse_result("petlabs", "qué colores tienen?",
                                      lead={"key": "x"}, channel="whatsapp", history=[])
        self.assertNotIn("media_asset", result)


class KeyboardNoiseTest(unittest.TestCase):

    def test_noise_is_unreadable(self):
        for text in ("asdkj 3e ...", "asdgfhj 123 ??", "sdfsdf", "kjhkjh", "ñlkj ñlkj"):
            with self.subTest(text=text):
                self.assertTrue(_unreadable_whatsapp_message(text, "losetaschile"))

    def test_real_messages_are_readable(self):
        for text in ("hola", "ok", "mmmm", "jajaja", "xd", "pff", "Gracias", "bordes",
                     "ballena", "construyen piscinas?", "instrucciones", "qwerty",
                     "9,60x4,00", "10,5 x 4 mts", "Quiero más información", "BPL50",
                     "ok 👍", "si", "Rompeolas", "boldes", "Pucón", "Ñuñoa"):
            with self.subTest(text=text):
                self.assertFalse(_unreadable_whatsapp_message(text, "losetaschile"))


if __name__ == "__main__":
    unittest.main()
