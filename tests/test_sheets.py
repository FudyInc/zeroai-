"""Tests de zero/sheets.py — sincronización a Google Sheets (datos, formato,
gráfico). Nunca pega contra Google de verdad: firma un JWT real con una
llave RSA generada localmente (misma técnica que SupabaseES256AuthTest para
Supabase) y simula la API con un backend falso en memoria en vez de una
lista fija de respuestas — así probar formato/gráfico no depende de saber
de antemano el orden exacto de las llamadas HTTP.
"""
import json as _json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from zero import sheets


def _mock_response(body):
    cm = mock.MagicMock()
    cm.__enter__.return_value.read.return_value = _json.dumps(body).encode("utf-8")
    cm.__exit__.return_value = False
    return cm


class _FakeSheetsBackend:
    """Simula lo mínimo de la Sheets API real que sync_finance/sync_leads
    necesitan: metadata, crear pestañas, limpiar/escribir valores, aplicar
    formato y agregar gráficos. Se comporta como un servidor de verdad
    (estado propio) en vez de una lista fija de respuestas — permite probar
    el flujo completo, incluida la idempotencia entre corridas."""

    def __init__(self):
        self.sheets = {}   # title -> {"sheetId": int, "charts": [...]}
        self.values = {}   # title -> [[...]]
        self._next_id = 100

    def __call__(self, req, timeout=None):
        method = req.get_method()
        path = req.full_url.split("/v4/spreadsheets/", 1)[1]
        base = path.split("?")[0]

        if method == "GET" and base == "sheet123":
            body = {"sheets": [
                {"properties": {"sheetId": v["sheetId"], "title": t}, "charts": v["charts"]}
                for t, v in self.sheets.items()
            ]}
            return _mock_response(body)

        if method == "POST" and base == "sheet123:batchUpdate":
            payload = _json.loads(req.data.decode("utf-8"))
            for r in payload["requests"]:
                if "addSheet" in r:
                    title = r["addSheet"]["properties"]["title"]
                    self.sheets.setdefault(title, {"sheetId": self._next_id, "charts": []})
                    self._next_id += 1
                if "addChart" in r:
                    sid = r["addChart"]["chart"]["spec"]["basicChart"]["domains"][0]["domain"]["sourceRange"]["sources"][0]["sheetId"]
                    for v in self.sheets.values():
                        if v["sheetId"] == sid:
                            v["charts"].append(r["addChart"]["chart"])
            return _mock_response({})

        if method == "POST" and base.endswith(":clear"):
            title = base.split("/values/")[1].rsplit(":clear", 1)[0]
            self.values[title] = []
            return _mock_response({})

        if method == "PUT" and "/values/" in base:
            title = base.split("/values/")[1].split("!")[0]
            payload = _json.loads(req.data.decode("utf-8"))
            self.values[title] = payload["values"]
            return _mock_response({})

        raise AssertionError(f"llamada inesperada al fake backend: {method} {path}")

    def ensure_tab(self, title):
        """Atajo para tests que quieren partir con una pestaña ya creada."""
        self.sheets.setdefault(title, {"sheetId": self._next_id, "charts": []})
        self._next_id += 1


_SAMPLE_FINANCE = {
    "month": "2026-07", "source": "real", "mrr_clp": 1_000_000,
    "costs_clp": 52_000, "margin_clp": 948_000, "margin_pct": 94.8,
    "costs": [{"category": "vapi", "amount_clp": 40_000, "note": None},
             {"category": "elevenlabs", "amount_clp": 12_000, "note": "voz"}],
    "history": [
        {"month": "2026-05", "mrr_clp": 800_000, "costs_clp": 40_000, "margin_clp": 760_000},
        {"month": "2026-06", "mrr_clp": 900_000, "costs_clp": 45_000, "margin_clp": 855_000},
        {"month": "2026-07", "mrr_clp": 1_000_000, "costs_clp": 52_000, "margin_clp": 948_000},
    ],
}


class BuildRowsTest(unittest.TestCase):
    """Las funciones puras que aplanan los datos a filas — sin red."""

    def test_finance_rows_include_summary_costs_and_history(self):
        rows, layout = sheets.build_finance_rows(_SAMPLE_FINANCE)
        flat = [str(c) for row in rows for c in row]
        self.assertIn("1000000", flat)
        self.assertIn("vapi", flat)
        self.assertIn("40000", flat)
        self.assertIn("2026-06", flat)
        # el layout apunta a las filas correctas de verdad
        self.assertEqual(rows[layout["costs_start_row"]][0], "vapi")
        self.assertEqual(rows[layout["historico_start_row"]][0], "2026-05")
        self.assertEqual(rows[layout["margin_pct_row"]][0], "Margen (%)")

    def test_finance_rows_never_write_the_literal_none(self):
        """Un valor faltante (mes sin MRR conocido, etc.) debe quedar como
        celda vacía, nunca como el string "None" pegado en el Sheet."""
        data = {"month": "2026-07", "source": "mock", "mrr_clp": None,
               "costs_clp": 0, "margin_clp": None, "margin_pct": None,
               "costs": [], "history": []}
        rows, _ = sheets.build_finance_rows(data)
        for row in rows:
            for cell in row:
                self.assertNotEqual(cell, "None")
                self.assertIsNotNone(cell)

    def test_layout_indices_shift_correctly_with_more_cost_categories(self):
        data = dict(_SAMPLE_FINANCE, costs=[{"category": c, "amount_clp": 1000, "note": None}
                                            for c in ("vapi", "elevenlabs", "supabase", "otros")])
        rows, layout = sheets.build_finance_rows(data)
        self.assertEqual(layout["costs_end_row"] - layout["costs_start_row"], 4)
        self.assertEqual(rows[layout["historico_header_row"]][0], "Histórico mensual")

    def test_leads_rows_sorted_by_score_descending(self):
        leads = [
            {"client_id": "acme", "company": "Bajo", "score": 40},
            {"client_id": "acme", "company": "Alto", "score": 90},
        ]
        rows = sheets.build_leads_rows(leads)
        self.assertEqual(rows[0], sheets._LEADS_HEADER)
        self.assertEqual(rows[1][1], "Alto")
        self.assertEqual(rows[2][1], "Bajo")

    def test_leads_rows_empty_list_is_just_the_header(self):
        self.assertEqual(sheets.build_leads_rows([]), [sheets._LEADS_HEADER])


class AccessTokenTest(unittest.TestCase):
    def setUp(self):
        sheets._TOKEN_CACHE["token"] = None
        sheets._TOKEN_CACHE["expires_at"] = 0.0
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")
        self.key_dict = {
            "type": "service_account",
            "client_email": "zeroai-sheets@zeroai-sheets.iam.gserviceaccount.com",
            "private_key": pem,
        }

    def tearDown(self):
        sheets._TOKEN_CACHE["token"] = None
        sheets._TOKEN_CACHE["expires_at"] = 0.0

    def _write_key(self, tmp_dir):
        path = str(Path(tmp_dir) / "key.json")
        with open(path, "w", encoding="utf-8") as f:
            _json.dump(self.key_dict, f)
        return path

    def test_returns_none_without_a_key_file(self):
        self.assertIsNone(sheets.get_access_token("/tmp/esto-no-existe-nunca.json"))

    def test_returns_none_for_malformed_key_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "bad.json")
            with open(path, "w") as f:
                f.write('{"type": "service_account"}')   # sin private_key ni client_email
            self.assertIsNone(sheets.get_access_token(path))

    def test_fetches_and_caches_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_key(tmp)
            resp = _mock_response({"access_token": "fake-token-123", "expires_in": 3600})
            with mock.patch("zero.sheets.urllib.request.urlopen", return_value=resp) as m:
                tok1 = sheets.get_access_token(path)
                tok2 = sheets.get_access_token(path)   # dentro del cache -> no pide de nuevo
            self.assertEqual(tok1, "fake-token-123")
            self.assertEqual(tok2, "fake-token-123")
            self.assertEqual(m.call_count, 1)

    def test_network_failure_returns_none_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_key(tmp)
            with mock.patch("zero.sheets.urllib.request.urlopen", side_effect=OSError("red caída")):
                self.assertIsNone(sheets.get_access_token(path))


class SyncTest(unittest.TestCase):
    """sync_finance/sync_leads/sync_all contra el backend falso — con un
    token ya en mano (la autenticación se prueba aparte, arriba)."""

    def setUp(self):
        self.backend = _FakeSheetsBackend()
        self.patcher = mock.patch("zero.sheets.urllib.request.urlopen", side_effect=self.backend)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()

    def test_sync_finance_creates_tab_writes_data_and_formats(self):
        ok = sheets.sync_finance("sheet123", _SAMPLE_FINANCE, token="fake-token")
        self.assertTrue(ok)
        self.assertIn("Finanzas", self.backend.sheets)
        self.assertGreater(len(self.backend.values.get("Finanzas", [])), 5)

    def test_sync_finance_adds_exactly_one_chart_even_after_two_syncs(self):
        sheets.sync_finance("sheet123", _SAMPLE_FINANCE, token="fake-token")
        sheets.sync_finance("sheet123", _SAMPLE_FINANCE, token="fake-token")   # segunda corrida
        charts = self.backend.sheets["Finanzas"]["charts"]
        self.assertEqual(len(charts), 1)
        self.assertEqual(charts[0]["spec"]["title"], sheets._FINANCE_CHART_TITLE)

    def test_sync_finance_skips_chart_with_less_than_two_months_of_history(self):
        data = dict(_SAMPLE_FINANCE, history=[_SAMPLE_FINANCE["history"][-1]])   # 1 solo mes
        sheets.sync_finance("sheet123", data, token="fake-token")
        self.assertEqual(self.backend.sheets["Finanzas"]["charts"], [])

    def test_sync_leads_writes_header_and_rows_to_existing_tab(self):
        self.backend.ensure_tab("Leads")
        ok = sheets.sync_leads("sheet123", [{"company": "Acme", "score": 80}], token="fake-token")
        self.assertTrue(ok)
        rows = self.backend.values["Leads"]
        self.assertEqual(rows[0], sheets._LEADS_HEADER)
        self.assertEqual(len(rows), 2)

    def test_sync_rewrites_from_scratch_each_time_no_leftover_rows(self):
        sheets.sync_leads("sheet123", [{"company": "A", "score": 1}, {"company": "B", "score": 2}],
                          token="fake-token")
        sheets.sync_leads("sheet123", [{"company": "Solo uno", "score": 1}], token="fake-token")
        rows = self.backend.values["Leads"]
        self.assertEqual(len(rows), 2)   # header + 1, no quedan A/B de la corrida anterior

    def test_sync_returns_false_on_http_error_not_raise(self):
        import urllib.error
        err = urllib.error.HTTPError("url", 403, "forbidden", {}, None)
        err.read = lambda: b'{"error": "no access"}'
        with mock.patch("zero.sheets.urllib.request.urlopen", side_effect=err):
            ok = sheets.sync_finance("sheet123", _SAMPLE_FINANCE, token="fake-token")
        self.assertFalse(ok)

    def test_sync_all_without_token_reports_both_false(self):
        with mock.patch("zero.sheets.get_access_token", return_value=None):
            result = sheets.sync_all("sheet123", {}, [])
        self.assertEqual(result["finance"], False)
        self.assertEqual(result["leads"], False)
        self.assertIn("error", result)

    def test_sync_all_writes_both_tabs(self):
        with mock.patch("zero.sheets.get_access_token", return_value="fake-token"):
            result = sheets.sync_all("sheet123", _SAMPLE_FINANCE, [{"company": "Acme", "score": 80}])
        self.assertTrue(result["finance"])
        self.assertTrue(result["leads"])
        self.assertIn("Finanzas", self.backend.sheets)
        self.assertIn("Leads", self.backend.sheets)


if __name__ == "__main__":
    unittest.main()
