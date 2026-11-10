"""Tests unitarios para zero/pooledge_orders.py — lógica pura, sin red."""
from __future__ import annotations

import datetime
import unittest
from zero import pooledge_orders as po


class NextOrderIdTest(unittest.TestCase):
    def test_basic(self):
        phone = "+56 9 1234 5678"
        issued = datetime.date(2026, 11, 9)
        self.assertEqual(po.next_order_id(phone, issued), "PE-091126-5678")

    def test_short_phone(self):
        self.assertEqual(po.next_order_id("123", datetime.date(2026, 1, 2)), "PE-020126-0123")


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
        out = po.build_order_rows(self.draft, self.fields)
        self.assertEqual(out["order_id"], "PE-091126-5678")
        # info_row: A..J
        info = out["info_row"]
        self.assertEqual(info[0], "Juan Pérez")          # A NOMBRE
        self.assertEqual(info[1], "56912345678")        # B TELEFONO
        self.assertEqual(info[2], "15-11-2026")         # C FECHA DESPACHO
        self.assertEqual(info[3], "No")                 # D RETIRO
        self.assertEqual(info[4], "Av. Siempre Viva 742, Santiago")  # E DIRECCION
        self.assertEqual(info[5], "Entregar en bodega trasera")       # F DETALLES
        self.assertFalse(info[6])                       # G ENTREGADO
        self.assertEqual(info[7], 25_000)               # H PRECIO DESPACHO
        self.assertEqual(info[8], 0)                    # I ABONO
        self.assertEqual(info[9], "PE-091126-5678")     # J ID PEDIDO
        # platas_row: A..F
        pl = out["platas_row"]
        self.assertEqual(pl[0], "PE-091126-5678")       # A ID
        self.assertEqual(pl[1], "15-11-2026")           # B FECHA
        self.assertEqual(pl[2], "Juan Pérez")           # C CLIENTE
        self.assertEqual(pl[3], "100 x Loseta Gris 40x40\n20 x Arena Polimérica")  # D DETALLE
        self.assertEqual(pl[4], 150_000)                # E VENTA NETA
        self.assertEqual(pl[5], "")                     # F vacío

    def test_pickup_true_no_shipping_needed(self):
        f = dict(self.fields, pickup=True, address="", shipping=None)
        out = po.build_order_rows(self.draft, f)
        self.assertEqual(out["info_row"][3], "Sí")
        self.assertEqual(out["info_row"][7], 0)

    def test_missing_delivery_raises(self):
        f = dict(self.fields, delivery=[])
        with self.assertRaises(po.OrderError):
            po.build_order_rows(self.draft, f)

    def test_missing_address_on_despacho_raises(self):
        f = dict(self.fields, address="")
        with self.assertRaises(po.OrderError):
            po.build_order_rows(self.draft, f)

    def test_missing_shipping_on_despacho_raises(self):
        f = dict(self.fields, shipping=None)
        with self.assertRaises(po.OrderError):
            po.build_order_rows(self.draft, f)

    def test_missing_phone_raises(self):
        d = dict(self.draft, phone="")
        with self.assertRaises(po.OrderError):
            po.build_order_rows(d, self.fields)

    def test_issued_as_date_object(self):
        d = dict(self.draft, issued=datetime.date(2026, 11, 9))
        out = po.build_order_rows(d, self.fields)
        self.assertEqual(out["order_id"], "PE-091126-5678")


if __name__ == "__main__":
    unittest.main()