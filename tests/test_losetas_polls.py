import unittest

from zero.losetas_polls import (COLOR_POLL_QUESTION, DELIVERY_POLL_FACTORY_PICKUP,
                                PRODUCT_POLL_QUESTION, canonical_choice,
                                numbered_choices, paver_order_details)


class PaverOrderDetailsTest(unittest.TestCase):
    def setUp(self):
        self.history = [
            {"role": "agent", "text": "¿Qué modelo del catálogo te interesa y cuántos m² necesitas cubrir?"},
        ]

    def test_collects_model_and_area_in_either_order(self):
        self.assertEqual(paver_order_details("Laja española", self.history),
                         {"model": "Laja española", "area_m2": None})
        history = [*self.history, {"role": "lead", "text": "Laja española"}]
        self.assertEqual(paver_order_details("18 m²", history),
                         {"model": "Laja española", "area_m2": "18"})

    def test_area_alone_does_not_count_as_model(self):
        self.assertEqual(paver_order_details("18 m²", self.history),
                         {"model": None, "area_m2": "18"})

    def test_ignores_details_from_before_the_prompt(self):
        history = [
            {"role": "lead", "text": "Necesito Laja española para 20 m²"},
            *self.history,
        ]
        self.assertEqual(paver_order_details("Hola", history),
                         {"model": None, "area_m2": None})



class NumberedChoiceTest(unittest.TestCase):
    def test_number_name_and_keycap_map_to_the_option(self):
        history = [{"role": "agent", "text": "¡Hola! " + numbered_choices("product")}]
        for answer in ("1", "1.", "opción 1", "1️⃣", "bordes de piscina", "BORDES DE PISCINA"):
            with self.subTest(answer=answer):
                self.assertEqual(canonical_choice(answer, history), "Bordes de piscina")
        self.assertEqual(canonical_choice("2", history), "Pastelones")

    def test_out_of_range_or_free_text_is_left_alone(self):
        history = [{"role": "agent", "text": numbered_choices("product")}]
        for answer in ("3", "0", "quiero 2 bordes", "6x3", "hola"):
            with self.subTest(answer=answer):
                self.assertIsNone(canonical_choice(answer, history))

    def test_only_the_latest_agent_prompt_counts(self):
        history = [{"role": "agent", "text": numbered_choices("product")},
                   {"role": "lead", "text": "1"},
                   {"role": "agent", "text": "¿Cuáles son las medidas de tu piscina?"}]
        self.assertIsNone(canonical_choice("2", history))

    def test_delivery_number_and_accentless_name(self):
        history = [{"role": "agent", "text": numbered_choices("delivery")}]
        self.assertEqual(canonical_choice("3", history), DELIVERY_POLL_FACTORY_PICKUP)
        self.assertEqual(canonical_choice("retiro en fabrica", history), DELIVERY_POLL_FACTORY_PICKUP)

    def test_question_is_not_repeated_when_reply_already_asks_it(self):
        text = numbered_choices("color", "Te comparto la gama. " + COLOR_POLL_QUESTION)
        self.assertNotIn(COLOR_POLL_QUESTION, text)
        self.assertIn("7. Amarillo", text)
        self.assertTrue(numbered_choices("product").startswith(PRODUCT_POLL_QUESTION))


if __name__ == "__main__":
    unittest.main()
