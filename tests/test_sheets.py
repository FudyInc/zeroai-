"""Tests de zero/sheets.py — sincronización a Google Sheets. Nunca pega
contra Google de verdad: firma un JWT real con una llave RSA generada
localmente (misma técnica que SupabaseES256AuthTest para Supabase) y
mockea urllib.request.urlopen para toda la conversación HTTP.
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


class BuildRowsTest(unittest.TestCase):
    """Las funciones puras que aplanan los datos a filas — sin red."""

    def test_finance_rows_include_summary_costs_and_history(self):
        data = {
            "month": "2026-07", "source": "real", "mrr_clp": 1_000_000,
            "costs_clp": 52_000, "margin_clp": 948_000, "margin_pct": 94.8,
            "costs": [{"category": "vapi", "amount_clp": 40_000, "note": None}],
            "history": [{"month": "2026-06", "mrr_clp": 900_000,
                        "costs_clp": 45_000, "margin_clp": 855_000}],
        }
        rows = sheets.build_finance_rows(data)
        flat = [str(c) for row in rows for c in row]
        self.assertIn("1000000", flat)
        self.assertIn("vapi", flat)
        self.assertIn("40000", flat)
        self.assertIn("2026-06", flat)

    def test_finance_rows_never_write_the_literal_none(self):
        """Un valor faltante (mes sin MRR conocido, etc.) debe quedar como
        celda vacía, nunca como el string "None" pegado en el Sheet."""
        data = {"month": "2026-07", "source": "mock", "mrr_clp": None,
               "costs_clp": 0, "margin_clp": None, "margin_pct": None,
               "costs": [], "history": []}
        rows = sheets.build_finance_rows(data)
        for row in rows:
            for cell in row:
                self.assertNotEqual(cell, "None")
                self.assertIsNotNone(cell)

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
    """sync_finance/sync_leads/sync_all — con un token ya en mano (no repite
    la parte de autenticación, ya cubierta arriba)."""

    def _put_call_body(self, mock_urlopen):
        put_call = [c for c in mock_urlopen.call_args_list
                   if c.args and getattr(c.args[0], "get_method", lambda: "")() == "PUT"]
        self.assertEqual(len(put_call), 1)
        return _json.loads(put_call[0].args[0].data.decode("utf-8"))

    def test_sync_finance_writes_to_existing_tab(self):
        meta = _mock_response({"sheets": [{"properties": {"title": "Finanzas"}}]})
        clear = _mock_response({})
        put = _mock_response({})
        with mock.patch("zero.sheets.urllib.request.urlopen",
                        side_effect=[meta, clear, put]) as m:
            ok = sheets.sync_finance("sheet123", {"month": "2026-07", "source": "mock",
                                                   "mrr_clp": 1, "costs_clp": 1,
                                                   "margin_clp": 0, "margin_pct": 0,
                                                   "costs": [], "history": []},
                                     token="fake-token")
        self.assertTrue(ok)
        self.assertEqual(m.call_count, 3)   # GET meta, POST clear, PUT values — sin addSheet
        body = self._put_call_body(m)
        self.assertIn("values", body)

    def test_sync_creates_tab_when_missing(self):
        meta = _mock_response({"sheets": [{"properties": {"title": "Sheet1"}}]})   # sin "Leads"
        add_sheet = _mock_response({})
        clear = _mock_response({})
        put = _mock_response({})
        with mock.patch("zero.sheets.urllib.request.urlopen",
                        side_effect=[meta, add_sheet, clear, put]) as m:
            ok = sheets.sync_leads("sheet123", [{"company": "Acme", "score": 80}], token="fake-token")
        self.assertTrue(ok)
        self.assertEqual(m.call_count, 4)   # GET meta, POST addSheet, POST clear, PUT values

    def test_sync_returns_false_on_http_error_not_raise(self):
        import urllib.error
        err = urllib.error.HTTPError("url", 403, "forbidden", {}, None)
        err.read = lambda: b'{"error": "no access"}'
        with mock.patch("zero.sheets.urllib.request.urlopen", side_effect=err):
            ok = sheets.sync_finance("sheet123", {"month": "2026-07", "source": "mock",
                                                   "mrr_clp": None, "costs_clp": 0,
                                                   "margin_clp": None, "margin_pct": None,
                                                   "costs": [], "history": []},
                                     token="fake-token")
        self.assertFalse(ok)

    def test_sync_all_without_token_reports_both_false(self):
        with mock.patch("zero.sheets.get_access_token", return_value=None):
            result = sheets.sync_all("sheet123", {}, [])
        self.assertEqual(result["finance"], False)
        self.assertEqual(result["leads"], False)
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
