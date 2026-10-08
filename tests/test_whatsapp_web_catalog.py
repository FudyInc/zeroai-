"""Contratos locales del puente Web; nunca inicia WhatsApp ni envía mensajes."""
import unittest
from unittest import mock

from zero.whatsapp_web import parse_message, send_catalog_image, send_group_text


class WhatsAppWebCatalogTest(unittest.TestCase):
    def test_profile_name_is_optional_and_requires_letters(self):
        base = {"id": "event", "from": "56912345678", "to_phone_id": "56987654321",
                "chat_id": "56912345678@c.us", "text": "Hola"}
        self.assertNotIn("profile_name", parse_message(base))
        self.assertNotIn("profile_name", parse_message({**base, "profile_name": " 1234 "}))
        self.assertEqual(parse_message({**base, "profile_name": "  María  Pérez "})["profile_name"],
                         "María Pérez")

    @mock.patch("zero.whatsapp_web.bridge_request")
    def test_group_send_checks_account_and_group_id(self, bridge):
        bridge.side_effect = [{"state": "ready", "account": "56987654321"},
                              {"id": "message-1", "ack": 0}]
        result = send_group_text("losetaschile", "56987654321", "123456789@g.us", "Pedido")
        self.assertEqual(result["id"], "message-1")
        self.assertEqual(bridge.call_args.args[0], "/send-group")
        bridge.reset_mock()
        with self.assertRaises(ValueError):
            send_group_text("losetaschile", "56987654321", "56912345678@c.us", "Pedido")
        bridge.assert_not_called()
        with self.assertRaisesRegex(ValueError, "no coincide"):
            send_catalog_image("losetaschile", "56987654321", "56912345678",
                               "gama-bordes-piscina.jpeg", "Foto",
                               chat_id="56900000000@c.us")
        bridge.assert_not_called()

    @mock.patch("zero.whatsapp_web.bridge_request")
    def test_image_send_allowlist_and_uncertain_result(self, bridge):
        with self.assertRaises(ValueError):
            send_catalog_image("losetaschile", "56987654321", "56912345678",
                               "../../secrets.txt", "Foto")
        bridge.assert_not_called()
        bridge.side_effect = [{"state": "ready", "account": "56987654321"}, {}]
        with self.assertRaisesRegex(RuntimeError, "sin confirmación"):
            send_catalog_image("losetaschile", "56987654321", "56912345678",
                               "borde-recto-nariz-50x50.png", "Modelo de borde")
        self.assertEqual(bridge.call_args.args[0], "/send-catalog-image")

    @mock.patch("zero.whatsapp_web.bridge_request")
    def test_account_mismatch_never_sends(self, bridge):
        bridge.return_value = {"state": "ready", "account": "56911111111"}
        with self.assertRaisesRegex(RuntimeError, "no coincide"):
            send_group_text("losetaschile", "56987654321", "123456789@g.us", "Pedido")
        self.assertEqual(bridge.call_count, 1)


if __name__ == "__main__":
    unittest.main()
