"""Entrega humana por WhatsApp: partición, tiempos de tecleo, variantes y envío."""
import unittest
from unittest import mock

from zero.config import WHATSAPP_HUMAN_DELIVERY as CFG
from zero.whatsapp_format import pick_variant, split_whatsapp_parts, typing_ms
from zero.whatsapp_web import WhatsAppWebSender

LONG_A = "Hola, gracias por escribirnos y contarnos lo que necesitas para tu proyecto."
LONG_B = "Con eso puedo orientarte mejor sobre las opciones que tenemos disponibles."


class SplitTest(unittest.TestCase):
    def split(self, text):
        return split_whatsapp_parts(text, CFG["max_parts"], CFG["min_split_chars"])

    def test_short_text_is_not_split(self):
        self.assertEqual(self.split("Hola, ¿en qué te ayudo?"), ["Hola, ¿en qué te ayudo?"])

    def test_plain_paragraphs_split(self):
        parts = self.split(f"{LONG_A}\n\n{LONG_B}")
        self.assertEqual(parts, [LONG_A, LONG_B])

    def test_quote_stays_whole(self):
        quote = "Presupuesto:\n- 10 piezas\nTotal: $100"
        parts = self.split(f"{LONG_A}\n\n{LONG_B}\n\n{quote}")
        self.assertEqual(parts, [LONG_A, LONG_B, quote])
        self.assertEqual(self.split(f"{LONG_A}\n\n{quote}\n\nGracias")[-1], f"{quote}\n\nGracias")

    def test_link_stays_whole(self):
        parts = self.split(f"{LONG_A}\n\nMira el catálogo en https://ejemplo.cl/catalogo\n\n{LONG_B}")
        self.assertEqual(parts[0], LONG_A)
        self.assertEqual(len(parts), 2)
        self.assertIn(LONG_B, parts[1])

    def test_numbered_list_stays_whole(self):
        lista = "Elige una opción\n1) Uno\n2) Dos"
        parts = self.split(f"{LONG_A}\n\n{LONG_B}\n\n{lista}")
        self.assertEqual(parts, [LONG_A, LONG_B, lista])

    def test_max_parts_merges_the_excess(self):
        paragraphs = [LONG_A, LONG_B, "Cuéntame más cuando puedas.", "Quedo atento a tu respuesta."]
        parts = split_whatsapp_parts("\n\n".join(paragraphs), 3, 120)
        self.assertEqual(parts, [LONG_A, LONG_B, "\n\n".join(paragraphs[2:])])

    def test_reconstruction(self):
        for text in (f"{LONG_A}\n\n{LONG_B}", f"{LONG_A}\n\nTotal $5\n\nFin",
                     f"{LONG_A}\n\n{LONG_B}\n\n{LONG_A}\n\n{LONG_B}"):
            self.assertEqual("\n\n".join(self.split(text)), text.strip())


class TypingTest(unittest.TestCase):
    def test_bounds(self):
        self.assertEqual(typing_ms("a", CFG), CFG["min_typing_ms"])
        self.assertEqual(typing_ms("a" * 10000, CFG), CFG["max_typing_ms"])
        self.assertEqual(typing_ms("a" * 40, CFG), 40 * CFG["ms_per_char"])


class PickVariantTest(unittest.TestCase):
    VARIANTS = ("a", "b", "c")

    def test_deterministic(self):
        self.assertEqual(pick_variant(self.VARIANTS, "k:1"), pick_variant(self.VARIANTS, "k:1"))

    def test_changes_with_turn_count(self):
        picked = {pick_variant(self.VARIANTS, f"k:{n}") for n in range(12)}
        self.assertGreater(len(picked), 1)
        self.assertTrue(picked <= set(self.VARIANTS))


class SenderTest(unittest.TestCase):
    def send(self, **extra):
        calls = []

        def fake(path, body=None, client_id=None):
            calls.append((path, body))
            return {"id": f"m{len(calls)}", "ack": 1, "state": "ready", "account": "56911111111"}
        msg = {"to": "56922222222", "body": f"{LONG_A}\n\n{LONG_B}", **extra}
        with mock.patch("zero.whatsapp_web.bridge_request", side_effect=fake):
            result = WhatsAppWebSender().send(msg)
        return result, [b for p, b in calls if p == "/send"]

    def test_agent_reply_is_split_with_typing(self):
        result, sends = self.send(humanize=True)
        self.assertEqual(result["status"], "sent")
        self.assertEqual([b["text"] for b in sends], [LONG_A, LONG_B])
        self.assertTrue(all(b["typing_ms"] > 0 for b in sends))
        self.assertEqual(result["id"], "m2")

    def test_manual_reply_is_single_and_without_typing(self):
        result, sends = self.send()
        self.assertEqual(result["status"], "sent")
        self.assertEqual(len(sends), 1)
        self.assertNotIn("typing_ms", sends[0])
        self.assertEqual(sends[0]["text"], f"{LONG_A}\n\n{LONG_B}")

    def test_partial_failure_returns_error_without_raising(self):
        calls = []

        def fake(path, body=None, client_id=None):
            if path != "/send":
                return {"state": "ready", "account": "56911111111"}
            calls.append(body["text"])
            if len(calls) == 2:
                raise RuntimeError("puente caído")
            return {"id": "m1", "ack": 1}
        msg = {"to": "56922222222", "body": f"{LONG_A}\n\n{LONG_B}", "humanize": True}
        with mock.patch("zero.whatsapp_web.bridge_request", side_effect=fake):
            result = WhatsAppWebSender().send(msg)
        self.assertEqual(calls, [LONG_A, LONG_B])
        self.assertTrue(result["partial"])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["sent_text"], LONG_A)

    def test_first_part_failure_still_raises(self):
        def fake(path, body=None, client_id=None):
            if path != "/send":
                return {"state": "ready", "account": "56911111111"}
            raise RuntimeError("puente caído")
        msg = {"to": "56922222222", "body": f"{LONG_A}\n\n{LONG_B}", "humanize": True}
        with mock.patch("zero.whatsapp_web.bridge_request", side_effect=fake):
            with self.assertRaises(RuntimeError):
                WhatsAppWebSender().send(msg)


class NoRepeatTest(unittest.TestCase):
    def test_never_repeats_last_agent_text(self):
        variants = ("a {x}", "b {x}", "c {x}")
        for key in ("k1", "k2", "k3", "k4"):
            first = pick_variant(variants, key, x="!")
            second = pick_variant(variants, key, first, x="!")
            self.assertNotEqual(first, second)
            self.assertIn(second, ("a !", "b !", "c !"))


class AgentSendsHumanizedTest(unittest.TestCase):
    def test_orchestrator_agent_sends_carry_humanize(self):
        import re
        from pathlib import Path
        src = Path("zero/orchestrator.py").read_text(encoding="utf-8")
        bodies = re.findall(r'\{"channel": channel, "subject": None, "body": [^}]*\}', src, re.S)
        self.assertGreaterEqual(len(bodies), 5)
        self.assertTrue(all('"humanize": True' in b for b in bodies))


if __name__ == "__main__":
    unittest.main()
