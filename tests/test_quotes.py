"""zero/quotes.py — presupuestos deterministas, la aritmética nunca la hace el LLM.

Sin tests dedicados hasta hoy (2026-07-06) — encontrado auditando CONCIERGE con
el modelo real (Ollama qwen2.5:7b) contra un caso real de PoolEdge: un pedido
con la cantidad separada del nombre del ítem por una palabra de unidad
("30 m2 de pastelón...") caía silenciosamente a qty=1, sin ningún error visible
— la cotización que se le mostraba al lead estaba simplemente mal calculada.
"""
from __future__ import annotations

import unittest

from zero.quotes import compute_quote, extract_request, format_quote, normalize_pricing


def _pricing(**overrides):
    base = {
        "currency": "CLP", "iva_rate": 0.19,
        "items": [
            {"id": "borde-recto", "name": "Borde recto", "unit_price": 12000, "unit": "metro lineal"},
            {"id": "pastelon-antideslizante", "name": "Pastelon antideslizante",
             "unit_price": 9500, "unit": "m2"},
        ],
    }
    base.update(overrides)
    return normalize_pricing(base)


class NormalizePricingTest(unittest.TestCase):
    def test_drops_items_without_name_or_positive_price(self):
        p = normalize_pricing({"items": [
            {"name": "", "unit_price": 1000},
            {"name": "Sin precio", "unit_price": 0},
            {"name": "Precio negativo", "unit_price": -500},
            {"name": "Precio no numerico", "unit_price": "gratis"},
            {"name": "Valido", "unit_price": 1000},
        ]})
        self.assertEqual([it["name"] for it in p["items"]], ["Valido"])

    def test_dedupes_by_slug(self):
        p = normalize_pricing({"items": [
            {"name": "Borde Recto", "unit_price": 1000},
            {"name": "borde   recto", "unit_price": 2000},  # mismo slug, se descarta
        ]})
        self.assertEqual(len(p["items"]), 1)

    def test_invalid_iva_rate_falls_back_to_default(self):
        from zero.config import IVA_RATE
        p = normalize_pricing({"iva_rate": 5, "items": []})   # fuera de [0,1]
        self.assertEqual(p["iva_rate"], IVA_RATE)
        p2 = normalize_pricing({"iva_rate": "no-numero", "items": []})
        self.assertEqual(p2["iva_rate"], IVA_RATE)

    def test_non_dict_input_returns_empty_catalog(self):
        p = normalize_pricing(None)
        self.assertEqual(p["items"], [])


class ExtractRequestTest(unittest.TestCase):
    def setUp(self):
        self.pricing = _pricing()

    def test_qty_adjacent_to_item_name(self):
        req = extract_request("necesito 30 pastelon antideslizante", self.pricing)
        self.assertEqual(req, [{"id": "pastelon-antideslizante", "qty": 30}])

    def test_qty_with_unit_word_and_de_between_number_and_item(self):
        """Regresión (2026-07-06): "30 m2 de X" — antes caía a qty=1 en silencio."""
        req = extract_request(
            "necesito 50 metros de borde recto y 30 m2 de pastelon antideslizante, cuanto sale?",
            self.pricing,
        )
        by_id = {r["id"]: r["qty"] for r in req}
        self.assertEqual(by_id.get("pastelon-antideslizante"), 30)
        self.assertEqual(by_id.get("borde-recto"), 50)

    def test_qty_suffix_style_x30(self):
        req = extract_request("pastelon antideslizante x30", self.pricing)
        self.assertEqual(req, [{"id": "pastelon-antideslizante", "qty": 30}])

    def test_word_based_quantity(self):
        req = extract_request("necesito dos pastelon antideslizante", self.pricing)
        self.assertEqual(req, [{"id": "pastelon-antideslizante", "qty": 2}])

    def test_absurd_quantity_ignored(self):
        # "2026 pastelon antideslizante" — un año pegado por casualidad, no un pedido real.
        req = extract_request("en el 2026 quiero pastelon antideslizante", self.pricing)
        self.assertEqual(req, [])

    def test_bare_mention_without_price_intent_triggers_nothing(self):
        req = extract_request("me interesa el pastelon antideslizante para mi casa", self.pricing)
        self.assertEqual(req, [])

    def test_bare_mention_with_price_intent_defaults_to_qty_one(self):
        req = extract_request("cuanto cuesta el pastelon antideslizante?", self.pricing)
        self.assertEqual(req, [{"id": "pastelon-antideslizante", "qty": 1}])

    def test_empty_message_returns_nothing(self):
        self.assertEqual(extract_request("", self.pricing), [])
        self.assertEqual(extract_request(None, self.pricing), [])


class ComputeQuoteTest(unittest.TestCase):
    def setUp(self):
        self.pricing = _pricing()

    def test_math_is_exact(self):
        q = compute_quote(self.pricing, [{"id": "pastelon-antideslizante", "qty": 30}])
        self.assertEqual(q["subtotal"], 285000.0)
        self.assertEqual(q["iva"], round(285000 * 0.19, 2))
        self.assertEqual(q["total"], round(285000 + 285000 * 0.19, 2))

    def test_multiple_items_sum_correctly(self):
        q = compute_quote(self.pricing, [
            {"id": "borde-recto", "qty": 50}, {"id": "pastelon-antideslizante", "qty": 30},
        ])
        self.assertEqual(q["subtotal"], 50 * 12000 + 30 * 9500)

    def test_unmatched_item_id_goes_to_unmatched_not_crash(self):
        q = compute_quote(self.pricing, [
            {"id": "pastelon-antideslizante", "qty": 1}, {"id": "no-existe", "qty": 5},
        ])
        self.assertIn("no-existe", q["unmatched"])
        self.assertEqual(len(q["lines"]), 1)

    def test_nothing_requested_or_all_unmatched_returns_none(self):
        self.assertIsNone(compute_quote(self.pricing, []))
        self.assertIsNone(compute_quote(self.pricing, [{"id": "no-existe", "qty": 1}]))


class FormatQuoteTest(unittest.TestCase):
    def test_shows_multiplier_only_when_qty_is_not_one(self):
        pricing = _pricing()
        single = format_quote(compute_quote(pricing, [{"id": "pastelon-antideslizante", "qty": 1}]))
        multi = format_quote(compute_quote(pricing, [{"id": "pastelon-antideslizante", "qty": 30}]))
        self.assertNotIn("×", single)
        self.assertIn("30 ×", multi)

    def test_clp_formatting_uses_dot_thousands_no_decimals(self):
        pricing = _pricing()
        text = format_quote(compute_quote(pricing, [{"id": "pastelon-antideslizante", "qty": 30}]))
        self.assertIn("$285.000", text)


if __name__ == "__main__":
    unittest.main()
