import unittest
from datetime import date

from zero.losetas_budget import format_customer_budget, format_internal_budget
from zero.quotes import compute_losetas_shipping_cost


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
        self.assertIn("Costo de envío: pendiente de confirmación del equipo.", message)
        self.assertIn("Fecha de entrega: pendiente de confirmación del equipo.", message)
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

    def test_route_distance_does_not_override_team_shipping_confirmation(self):
        self.quote["shipping_route_km"] = 12.5
        self.quote["delivery_detail"] = (
            "Ubicación compartida: https://www.google.com/maps?q=-33.610397,-70.643376")
        message = format_internal_budget(self.quote, profile_name="", phone="56912345678",
                                         tone="gris")
        self.assertIn("Costo de envío: pendiente de confirmación del equipo.", message)
        self.assertNotIn("$25.000", message)
        self.assertIn(self.quote["delivery_detail"], message)

    def test_invalid_route_distance_never_calculates_freight(self):
        for km in (None, "", "nan", "inf", -2, 0):
            with self.subTest(km=km):
                self.assertIsNone(compute_losetas_shipping_cost(km))
        self.assertEqual(compute_losetas_shipping_cost("12.5"), 25000)


class CustomerBudgetTest(unittest.TestCase):
    def setUp(self):
        self.quote = {"currency": "CLP", "total": 302400, "lines": [
            {"name": "Borde recto con nariz 50×50", "qty": 48,
             "unit_price": 6000, "subtotal": 288000},
            {"name": "Esquina piscina 50×50", "qty": 4,
             "unit_price": 3600, "subtotal": 14400},
        ]}
        self.data = dict(number="PE-261026-0685", issued=date(2026, 10, 26),
                         customer="marcia", phone="56933040685",
                         address="Avenida Los Laureles, poste 104, casa 25, Limache",
                         color="blanco", pool="4 × 8 m", shipping=80000,
                         shipping_label="Despacho a Limache",
                         delivery=[date(2026, 10, 30), date(2026, 10, 31)], deposit=10000,
                         map_url="https://maps.app.goo.gl/5AuWWpBpix3W7CZX9")

    def test_figures_brand_and_delivery_are_laid_out_like_an_invoice(self):
        text = format_customer_budget(self.quote, **self.data)
        self.assertTrue(text.startswith("*POOLEDGE*"))
        for line in ("*PRESUPUESTO N° PE-261026-0685*", "Emitido el 26 de octubre de 2026",
                     "Marcia", "+56 9 3304 0685", "Color: Blanco", "Piscina: 4 × 8 m",
                     "48 un. × $6.000 = *$288.000*", "Total piezas: 52",
                     "Subtotal productos: $302.400", "Despacho a Limache: $80.000",
                     "*TOTAL: $382.400*", "Abono para confirmar: $10.000",
                     "Saldo contra entrega: $372.400", "Viernes 30 o sábado 31 de octubre",
                     "Ubicación: https://maps.app.goo.gl/5AuWWpBpix3W7CZX9"):
            self.assertIn(line, text.splitlines())
        self.assertNotIn("```", text)

    def test_missing_shipping_date_and_map_are_stated_not_invented(self):
        text = format_customer_budget(self.quote, **dict(
            self.data, shipping=None, delivery=[], map_url=None))
        self.assertIn("Despacho a Limache: por cotizar", text)
        self.assertIn("Fecha por confirmar", text)
        self.assertIn("*TOTAL: $302.400*", text)
        self.assertNotIn("Ubicación", text)

    def test_incoherent_figures_or_dates_produce_no_budget(self):
        wrong_line = dict(self.quote, lines=[dict(self.quote["lines"][0], subtotal=280000),
                                             self.quote["lines"][1]])
        cases = [(wrong_line, {}), (dict(self.quote, total=300000), {}),
                 (self.quote, {"delivery": [date(2026, 10, 20)]}),
                 (self.quote, {"delivery": [date(2026, 10, 31), date(2026, 10, 30)]}),
                 (self.quote, {"deposit": 500000}), (self.quote, {"shipping": -1}),
                 (self.quote, {"customer": "  "}), (self.quote, {"phone": "123"}),
                 (dict(self.quote, unmatched=["x"]), {})]
        for quote, change in cases:
            self.assertIsNone(format_customer_budget(quote, **dict(self.data, **change)))


if __name__ == "__main__":
    unittest.main()
