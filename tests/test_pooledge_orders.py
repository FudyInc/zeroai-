"""Tests unitarios para zero/pooledge_orders.py — lógica pura, sin red."""
from __future__ import annotations

import datetime
import unittest
from zero import pooledge_orders as po


class NextOrderIdTest(unittest.TestCase):
    def test_empty_starts_at_one(self):
        self.assertEqual(po.next_order_id([]), "PE-0001")

    def test_max_plus_one(self):
        self.assertEqual(po.next_order_id(["PE-0007", "PE-0041", "PE-0003"]), "PE-0042")

    def test_ignores_garbage(self):
        self.assertEqual(po.next_order_id(["", None, "xx", "PE-", "PE-12a", "PE-0005"]), "PE-0006")

    def test_grows_past_four_digits(self):
        self.assertEqual(po.next_order_id(["PE-9999"]), "PE-10000")


class RowLookupTest(unittest.TestCase):
    def test_first_empty_row_with_gap(self):
        rows = [["H"], ["a"], ["b"], [], ["d"]]
        self.assertEqual(po.first_free_row(rows, po.PLATAS_DATA_COLUMNS), 4)

    def test_first_empty_row_blank_string_cell(self):
        self.assertEqual(po.first_free_row([["H"], ["a"], [""]], (0,)), 3)

    def test_first_empty_row_after_data_with_false_tail(self):
        # La lectura de A:J trae filas con solo FALSE en G: A vacía igual cuenta como libre.
        rows = [["H"], ["a"], ["b"], ["", "", "", "", "", "", False], ["", "", "", "", "", "", False]]
        self.assertEqual(po.first_free_row(rows, po.PLATAS_DATA_COLUMNS), 4)

    def test_first_empty_row_full_and_empty_sheet(self):
        self.assertEqual(po.first_free_row([["H"], ["a"]], (0,)), 3)
        self.assertEqual(po.first_free_row([], (0,)), 2)

    def test_row_with_a_empty_but_other_data_is_skipped(self):
        rows = [["H"], ["a", "x"], ["", "dato"], ["", "", "", "det"], []]
        self.assertEqual(po.first_free_row(rows, po.PLATAS_DATA_COLUMNS), 5)
        info = [["H"], ["", "", "", "", "", "", False, "", "", "PE-0001"],
                ["", "", "", "", "", "", False, 5000], ["", "", "", "", "", "", False]]
        self.assertEqual(po.first_free_row(info, po.INFO_DATA_COLUMNS), 4)

    def test_find_order_row_is_index_plus_one(self):
        rows = [["H"], ["a"] + [""] * 8 + ["PE-0001"], ["b"] + [""] * 8 + ["PE-0002"]]
        self.assertEqual(po.find_order_row(rows, "PE-0002"), 3)
        self.assertIsNone(po.find_order_row(rows, "PE-0003"))


class BuildOrderRowsTest(unittest.TestCase):
    def setUp(self):
        self.draft = {
            "quote": {
                "subtotal": 150_000,
                "lines": [
                    {"qty": 100, "name": "Loseta Gris 40x40"},
                    {"qty": 20, "name": "Arena Polimérica"},
                ],
                "delivery_detail": "Entregar en bodega trasera",
            },
            "name": "Juan Pérez",
            "phone": "+56 9 1234 5678",
            "color": "Gris",
            "issued": "2026-11-09",
        }
        self.fields = {
            "pickup": False,
            "address": "Av. Siempre Viva 742, Santiago",
            "delivery": [datetime.date(2026, 11, 15)],
            "shipping": 25_000,
            "pool": "3 × 4 m",
            "map_url": "https://maps.app.goo.gl/xyz",
        }

    def test_complete_rows(self):
        out = po.build_order_rows(self.draft, self.fields, 'PE-0001')
        self.assertEqual(out["order_id"], "PE-0001")
        # info_row: A..J
        info = out["info_row"]
        self.assertEqual(info[0], "Juan Pérez")          # A NOMBRE
        self.assertEqual(info[1], "'56912345678")        # B TELEFONO
        self.assertEqual(info[2], "2026-11-15")         # C FECHA DESPACHO
        self.assertEqual(info[3], "No")                 # D RETIRO
        self.assertEqual(info[4], "Av. Siempre Viva 742, Santiago")  # E DIRECCION
        self.assertEqual(info[5], "Entregar en bodega trasera")       # F DETALLES
        self.assertFalse(info[6])                       # G ENTREGADO
        self.assertEqual(info[7], 25_000)               # H PRECIO DESPACHO
        self.assertEqual(info[8], 0)                    # I ABONO
        self.assertEqual(info[9], "PE-0001")     # J ID PEDIDO
        # platas_row: A..E
        pl = out["platas_row"]
        self.assertEqual(pl[0], "PE-0001")       # A ID
        self.assertEqual(pl[1], "2026-11-15")           # B FECHA
        self.assertEqual(pl[2], "Juan Pérez")           # C CLIENTE
        self.assertEqual(pl[3], "100 x Loseta Gris 40x40\n20 x Arena Polimérica")  # D DETALLE
        self.assertEqual(pl[4], 150_000)                # E VENTA NETA
        self.assertEqual(len(pl), 5)

    def test_pickup_true_no_shipping_needed(self):
        f = dict(self.fields, pickup=True, address="", shipping=None)
        out = po.build_order_rows(self.draft, f, 'PE-0001')
        self.assertEqual(out["info_row"][3], "Sí")
        self.assertEqual(out["info_row"][7], 0)

    def test_missing_delivery_raises(self):
        f = dict(self.fields, delivery=[])
        with self.assertRaises(po.OrderError):
            po.build_order_rows(self.draft, f, 'PE-0001')

    def test_missing_address_on_despacho_raises(self):
        f = dict(self.fields, address="")
        with self.assertRaises(po.OrderError):
            po.build_order_rows(self.draft, f, 'PE-0001')

    def test_missing_shipping_on_despacho_raises(self):
        f = dict(self.fields, shipping=None)
        with self.assertRaises(po.OrderError):
            po.build_order_rows(self.draft, f, 'PE-0001')

    def test_missing_phone_raises(self):
        d = dict(self.draft, phone="")
        with self.assertRaises(po.OrderError):
            po.build_order_rows(d, self.fields, 'PE-0001')

    def test_formula_injection_is_neutralized(self):
        for lead in ("\t=1", "\r=1"):
            out = po.build_order_rows(dict(self.draft, name=lead), self.fields, "PE-0001")
            self.assertEqual(out["info_row"][0], "'" + lead)
        d = dict(self.draft, name="=HYPERLINK(\"x\")")
        d["quote"] = dict(self.draft["quote"], delivery_detail="@cmd")
        out = po.build_order_rows(d, dict(self.fields, address="-2+3"), "PE-0001")
        self.assertEqual(out["info_row"][0], "'=HYPERLINK(\"x\")")
        self.assertEqual(out["info_row"][4], "'-2+3")
        self.assertEqual(out["info_row"][5], "'@cmd")
        self.assertEqual(out["platas_row"][2], "'=HYPERLINK(\"x\")")

    def test_delivery_accepts_iso_strings(self):
        f = dict(self.fields, delivery=["2026-11-20", "2026-11-15"])
        out = po.build_order_rows(self.draft, f, "PE-0001")
        self.assertEqual(out["info_row"][2], "2026-11-15")


if __name__ == "__main__":
    unittest.main()
