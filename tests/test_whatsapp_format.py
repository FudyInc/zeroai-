"""Readable WhatsApp copy must preserve factual and structured content."""
import unittest

from zero.whatsapp_format import format_whatsapp_reply
from zero.config import LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE


class WhatsAppFormatTest(unittest.TestCase):
    def test_short_catalog_link_is_unchanged(self):
        link = "https://wa.me/c/56964537891"
        self.assertEqual(format_whatsapp_reply(link), link)
        self.assertEqual(format_whatsapp_reply(LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE),
                         LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE)

    def test_separates_two_ideas_without_changing_words(self):
        original = ("Tenemos varios modelos de bordes para piscina y te puedo mostrar "
                    "los que figuran en el catálogo. ¿Qué modelo te interesa revisar?")
        self.assertEqual(format_whatsapp_reply(original), original.replace(". ¿", ".\n\n¿"))

    def test_adds_missing_terminal_punctuation_but_preserves_structured_quote(self):
        self.assertEqual(format_whatsapp_reply("Te puedo ayudar con eso"),
                         "Te puedo ayudar con eso.")
        quote = "Detalle calculado:\n\n2 unidades × $3.000\nTotal: $6.000"
        self.assertEqual(format_whatsapp_reply(quote), quote)


if __name__ == "__main__":
    unittest.main()
