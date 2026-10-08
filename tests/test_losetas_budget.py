import unittest

from zero.losetas_budget import format_internal_budget


class LosetasBudgetTest(unittest.TestCase):
    def setUp(self):
        self.quote = {"currency": "CLP", "total": 230400, "lines": [
            {"name": "Borde recto con nariz 50x50", "qty": 36,
             "unit_price": 6000, "subtotal": 216000},
            {"name": "Esquina piscina 50x50", "qty": 4,
             "unit_price": 3600, "subtotal": 14400},
        ]}

    def test_display_name_above_number_and_internal_only(self):
        message = format_internal_budget(self.quote, profile_name="  María  Pérez  ",
                                         phone="56912345678", tone="beige")
        self.assertIn("Cliente: María Pérez\nNúmero: +56912345678", message)
        self.assertIn("Color indicado por cliente: beige", message)
        self.assertIn("*Total productos: $230.400*", message)
        self.assertIn("Despacho: por cotizar", message)
        self.assertIn("enviar manualmente", message)

    def test_no_display_name_omits_name_but_keeps_number(self):
        message = format_internal_budget(self.quote, profile_name="", phone="56912345678",
                                         tone="gris")
        self.assertNotIn("Cliente:", message)
        self.assertIn("Número: +56912345678", message)
        self.assertIn("Color indicado por cliente: gris", message)

    def test_missing_number_blocks_budget(self):
        self.assertIsNone(format_internal_budget(self.quote, profile_name="Ana",
                                                 phone="", tone="rojo"))


if __name__ == "__main__":
    unittest.main()
