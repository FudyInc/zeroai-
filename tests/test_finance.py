"""zero/finance.py — finanzas de la agencia (entra / sale / margen).

Solo stdlib, como test_core.py: el módulo es puro (la única I/O es leer
finance.json vía persistence, que ya tiene su propio manejo de corrupción).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from zero.finance import (current_month, finance_summary, load_finance,
                          normalize_costs, summary, valid_month)


class TestValidMonth(unittest.TestCase):
    def test_accepts_yyyy_mm(self):
        self.assertTrue(valid_month("2026-07"))
        self.assertTrue(valid_month("2025-12"))

    def test_rejects_everything_else(self):
        for bad in ("2026-7", "07-2026", "2026-13", "2026-00", "julio", "", None):
            self.assertFalse(valid_month(bad), bad)


class TestNormalizeCosts(unittest.TestCase):
    def test_discards_garbage(self):
        raw = [None, "x", {}, {"category": "vapi"},                 # sin monto
               {"category": "vapi", "amount_clp": "nope"},          # monto no numérico
               {"category": "vapi", "amount_clp": -5},              # negativo
               {"category": "vapi", "amount_clp": 45_000}]
        self.assertEqual(normalize_costs(raw),
                         [{"category": "vapi", "amount_clp": 45_000, "note": None}])

    def test_unknown_category_folds_to_otros_keeping_name(self):
        out = normalize_costs([{"category": "Notion", "amount_clp": 8_000, "note": "docs"}])
        self.assertEqual(out[0]["category"], "otros")
        self.assertIn("notion", out[0]["note"])
        self.assertIn("docs", out[0]["note"])

    def test_category_is_case_insensitive(self):
        out = normalize_costs([{"category": " Vapi ", "amount_clp": 1_000}])
        self.assertEqual(out[0]["category"], "vapi")

    def test_not_a_list_is_empty(self):
        self.assertEqual(normalize_costs({"vapi": 1}), [])
        self.assertEqual(normalize_costs(None), [])


class TestSummaryMock(unittest.TestCase):
    """Sin finance.json (data=None): cifras de ejemplo, mismo contrato."""

    def test_mock_shape_and_math(self):
        s = summary(None, mrr_clp=250_000)
        self.assertEqual(s["source"], "mock")
        self.assertEqual(s["month"], current_month())
        self.assertEqual(s["mrr_clp"], 250_000)          # el MRR es real igual
        self.assertEqual(s["costs_clp"], sum(c["amount_clp"] for c in s["costs"]))
        self.assertEqual(s["margin_clp"], 250_000 - s["costs_clp"])
        self.assertEqual(s["history"], [])

    def test_mock_past_month_has_no_mrr(self):
        # El MRR vivo es del mes en curso; inventarlo para un mes cerrado sería mentir.
        s = summary(None, mrr_clp=250_000, month="2020-01")
        self.assertIsNone(s["mrr_clp"])
        self.assertIsNone(s["margin_clp"])
        self.assertIsNone(s["margin_pct"])


class TestSummaryReal(unittest.TestCase):
    DATA = {"months": {
        "2026-06": {"costs": [{"category": "vapi", "amount_clp": 30_000}],
                    "mrr_clp": 200_000},
        "2026-07": {"costs": [{"category": "vapi", "amount_clp": 45_000},
                              {"category": "elevenlabs", "amount_clp": 12_000}]},
    }}

    def test_month_math(self):
        s = summary(self.DATA, mrr_clp=250_000, month="2026-06")
        self.assertEqual(s["source"], "real")
        self.assertEqual(s["mrr_clp"], 200_000)          # manda la foto del archivo
        self.assertEqual(s["costs_clp"], 30_000)
        self.assertEqual(s["margin_clp"], 170_000)
        self.assertEqual(s["margin_pct"], 85.0)

    def test_month_without_snapshot_and_not_current_has_none_mrr(self):
        s = summary(self.DATA, mrr_clp=250_000, month="2026-07")
        if current_month() == "2026-07":
            self.assertEqual(s["mrr_clp"], 250_000)      # mes en curso → MRR vivo
        else:
            self.assertIsNone(s["mrr_clp"])
        self.assertEqual(s["costs_clp"], 57_000)

    def test_history_is_sorted_and_slim(self):
        s = summary(self.DATA, mrr_clp=250_000)
        self.assertEqual([h["month"] for h in s["history"]], ["2026-06", "2026-07"])
        self.assertEqual(set(s["history"][0]),
                         {"month", "mrr_clp", "costs_clp", "margin_clp"})

    def test_empty_month_is_zero_costs_not_error(self):
        s = summary({"months": {}}, mrr_clp=250_000, month="2026-05")
        self.assertEqual(s["source"], "real")
        self.assertEqual(s["costs"], [])
        self.assertEqual(s["costs_clp"], 0)


class TestLoadFinance(unittest.TestCase):
    def test_missing_file_is_none_mock_mode(self):
        self.assertIsNone(load_finance(Path(tempfile.mkdtemp()) / "finance.json"))

    def test_corrupt_file_raises_and_is_not_touched(self):
        # Regla de la casa: datos locales corruptos → avisar, nunca sobrescribir.
        path = Path(tempfile.mkdtemp()) / "finance.json"
        path.write_text("{esto no es json", "utf-8")
        with self.assertRaises(RuntimeError):
            load_finance(path)
        self.assertEqual(path.read_text("utf-8"), "{esto no es json")

    def test_wrong_shape_raises(self):
        path = Path(tempfile.mkdtemp()) / "finance.json"
        path.write_text(json.dumps([1, 2, 3]), "utf-8")
        with self.assertRaises(RuntimeError):
            load_finance(path)

    def test_finance_summary_end_to_end(self):
        path = Path(tempfile.mkdtemp()) / "finance.json"
        path.write_text(json.dumps(
            {"months": {"2026-06": {"costs": [{"category": "dominio", "amount_clp": 12_000}],
                                    "mrr_clp": 100_000}}}), "utf-8")
        s = finance_summary(path, mrr_clp=250_000, month="2026-06")
        self.assertEqual((s["source"], s["margin_clp"]), ("real", 88_000))


if __name__ == "__main__":
    unittest.main()
