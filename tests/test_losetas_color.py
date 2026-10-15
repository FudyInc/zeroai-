import unittest

from zero.losetas_color import (COLOR_CATALOG_IMAGE_PATH, COLOR_CATALOG_IMAGE_URL,
                                color_preference, color_question,
                                latest_color_preference)


class LosetasColorTest(unittest.TestCase):
    def test_question_uses_the_labeled_owner_image(self):
        question = color_question()
        self.assertTrue(COLOR_CATALOG_IMAGE_URL.endswith(COLOR_CATALOG_IMAGE_PATH))
        for color in ("anaranjado", "blanco", "rojo", "crema", "beige", "gris", "amarillo"):
            self.assertIn(color, question)
        self.assertNotIn("disponible", question)

    def test_color_name_after_question(self):
        history = [{"role": "agent", "text": color_question()}]
        self.assertEqual(color_preference("Quiero amarillo", history), "amarillo")
        self.assertEqual(color_preference("Me gusta el gris", history), "gris")

    def test_does_not_take_dimensions_or_other_conversation_as_tone(self):
        history = [{"role": "agent", "text": color_question()}]
        for message in ("6x3", "7", "Necesito presupuesto", "No sé", "Hola",
                        "Estoy entre blanco y gris"):
            with self.subTest(message=message):
                self.assertIsNone(color_preference(message, history))
        self.assertIsNone(color_preference("gris", []))
        self.assertIsNone(color_preference("gris", [
            *history, {"role": "agent", "text": "¿Cuánto mide tu piscina?"}]))

    def test_reads_previous_preference_after_prompt(self):
        history = [
            {"role": "lead", "text": "Piscina 6x3"},
            {"role": "agent", "text": color_question()},
            {"role": "lead", "text": "el beige"},
            {"role": "agent", "text": "Gracias, anotado."},
        ]
        self.assertEqual(latest_color_preference(history), "beige")

    def test_new_unanswered_question_clears_old_color_choice(self):
        history = [
            {"role": "agent", "text": color_question()},
            {"role": "lead", "text": "beige"},
            {"role": "agent", "text": color_question()},
        ]
        self.assertIsNone(latest_color_preference(history))


if __name__ == "__main__":
    unittest.main()
