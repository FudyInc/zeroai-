"""Contratos locales del puente Web; nunca inicia WhatsApp ni envía mensajes."""
import unittest
from unittest import mock

from zero.config import LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE
from zero.whatsapp_web import (parse_message, send_catalog_document, send_catalog_image,
                               send_delivery_poll, send_group_text,
                               WhatsAppWebSender)


class WhatsAppWebCatalogTest(unittest.TestCase):
    @mock.patch("zero.whatsapp_web.bridge_request")
    def test_catalog_text_disables_link_preview(self, bridge):
        bridge.side_effect = [{"state": "ready", "account": "56987654321"},
                              {"id": "message-1", "ack": 0}]
        result = WhatsAppWebSender().send({
            "client_id": "losetaschile", "whatsapp_from": "56987654321",
            "to": "56912345678", "body": LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE,
            "whatsapp_chat_id": "56912345678@c.us",
        })
        self.assertEqual(result["status"], "sent")
        self.assertEqual(bridge.call_args.args[0], "/send")
        self.assertEqual(bridge.call_args.args[1]["text"],
                         LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE)
        self.assertIs(bridge.call_args.args[1]["link_preview"], False)

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

    @mock.patch("zero.whatsapp_web.bridge_request")
    def test_document_send_uses_structured_prices_and_verifies_account(self, bridge):
        pricing = {"items": [
            {"id": "borde-ballena-50x40", "unit_price": 5500},
            {"id": "borde-recto-nariz-50x50", "unit_price": 6000},
        ]}
        bridge.side_effect = [{"state": "ready", "account": "56987654321"},
                              {"id": "document-1", "ack": 0}]
        result = send_catalog_document("losetaschile", "56987654321", "56912345678",
                                       "bordes", pricing, chat_id="56912345678@c.us")
        self.assertEqual(result["id"], "document-1")
        self.assertEqual(bridge.call_args.args[0], "/send-catalog-document")
        self.assertEqual(bridge.call_args.args[1]["prices"]["borde-ballena-50x40"], 5500)
        bridge.reset_mock()
        with self.assertRaises(ValueError):
            send_catalog_document("losetaschile", "56987654321", "56912345678",
                                  "otros", pricing)
        bridge.assert_not_called()

    @mock.patch("zero.whatsapp_web.bridge_request")
    def test_delivery_poll_uses_verified_losetas_account(self, bridge):
        bridge.side_effect = [{"state": "ready", "account": "56987654321"},
                              {"id": "poll-1", "ack": 0}]
        result = send_delivery_poll("losetaschile", "56987654321", "56912345678",
                                    "56912345678@c.us")
        self.assertEqual(result["status"], "sent")
        self.assertEqual(bridge.call_args.args[0], "/send-delivery-poll")
        bridge.reset_mock()
        with self.assertRaises(ValueError):
            send_delivery_poll("otro", "56987654321", "56912345678",
                               "56912345678@c.us")
        bridge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
