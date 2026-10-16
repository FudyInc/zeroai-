import unittest

from zero.losetas_polls import paver_order_details


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


if __name__ == "__main__":
    unittest.main()
