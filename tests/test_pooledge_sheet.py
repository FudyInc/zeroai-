"""Consulta histórica Pooledge: datos sintéticos y sin red."""
import unittest
from datetime import date
from pathlib import Path
import tempfile
import os
import io
from contextlib import redirect_stdout
from unittest import mock

from scripts import pooledge_reordenar as cli

from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit

from zero import pooledge_sheet as ps, sheets

INFO_H = ["NOMBRE", "TELEFONO", "FECHA DESPACHO", "RETIRO", "DIRECCION DESPACHO",
          "DETALLES CLIENTES", "ENTREGADO", "PRECIO DESPACHO", "ABONO CLIENTE"]
PLATAS_H = ["NOMBRE CLIENTE", "COSTO BASE", "VENTA", "GANANCIA", "IVA 19%", "COBRADO", "COMISION DIEGO"]
INFO = [INFO_H, ["Ana", "999", "1 de enero 2020", "", "", "", "", 100, 50]]
PLATAS = [PLATAS_H, ["Ana", 25, 100, 75, 19, 0, 10]]


class HistoricalViewTest(unittest.TestCase):
    def test_retains_source_rows_and_creates_no_operational_data(self):
        view = ps.historical_view(INFO, PLATAS, date(2026, 11, 9))
        self.assertEqual(view.info_rows[0]["source_row"], 2)
        self.assertEqual(view.info_rows[0]["values"], INFO[1])
        self.assertEqual(view.platas_rows[0]["values"], PLATAS[1])
        self.assertEqual(view.info_rows[0]["status"], "pendiente/no disponible")
        self.assertFalse(view.stats["datos_operativos"])

    def test_only_explicit_red_marks_abandoned_quote(self):
        view = ps.historical_view(INFO, PLATAS, date(2026, 11, 9), info_colors={(2, 0): "red"})
        self.assertEqual(view.info_rows[0]["status"], "presupuesto abandonado/no respondió")
        self.assertIn("color rojo explícito", view.info_rows[0]["status_signal"])

    def test_grid_data_normalizes_red_and_leaves_other_colors_unclassified(self):
        response = {"sheets": [{"properties": {"title": "INFO PEDIDOS POOLEDGE"}, "data": [{
            "startRow": 2, "startColumn": 0, "rowData": [
                {"values": [{"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 0, "blue": 0}}}]},
                {"values": [{"userEnteredFormat": {"backgroundColor": {"red": 1, "green": 0.1, "blue": 0}}}]},
            ]}]}]}
        platas_grid = {"sheets": [{"properties": {"title": "PLATAS POOLEDGE"}, "data": []}]}
        view = ps.historical_view_from_grid(INFO + [["Beto"], ["Carla"], ["Diego"]], PLATAS,
                                           response, platas_grid, date(2026, 11, 9))
        self.assertEqual(view.info_rows[0]["status"], "pendiente/no disponible")
        self.assertEqual(view.info_rows[1]["status"], "presupuesto abandonado/no respondió")
        self.assertEqual(ps.normalize_grid_color({"red": 1, "green": 0, "blue": 0}), "red")
        self.assertEqual(ps.normalize_grid_color({"red": 0, "green": 0, "blue": 1}), "#0000ff")
        self.assertIsNone(ps.normalize_grid_color(None))

    def test_renderer_states_historical_limits(self):
        page = ps.render_preview_html(ps.historical_view(INFO, PLATAS, date(2026, 11, 9)))
        for text in ("Sin datos operativos", "Estados no inferidos", "fecha antigua no significa entregado",
                     "Rojo solo si existe señal explícita", "pendiente/no disponible"):
            self.assertIn(text, page)

    def test_rejects_unrecognized_source(self):
        with self.assertRaises(ps.MigrationError):
            ps.historical_view([["distinto"]], PLATAS, date(2026, 11, 9))

    def test_grid_response_must_match_expected_tab(self):
        with self.assertRaises(ps.MigrationError):
            ps.historical_view_from_grid(INFO, PLATAS,
                                        {"sheets": [{"properties": {"title": "PLATAS POOLEDGE"}}]},
                                        {"sheets": [{"properties": {"title": "PLATAS POOLEDGE"}}]},
                                        date(2026, 11, 9))


class GridReadTest(unittest.TestCase):
    def test_grid_read_quotes_range_requests_narrow_fields_and_never_writes(self):
        body = {"sheets": [{"data": [{"rowData": [{"values": [
            {"userEnteredValue": {"stringValue": "Ana", "formulaValue": "=1+1"},
             "note": "nota sintética", "userEnteredFormat": {"backgroundColor": {"red": 1}}}
        ]}]}]}]}
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = __import__("json").dumps(body).encode()
        a1 = "'INFO O'Brien'!A1:I40"
        with mock.patch("zero.sheets.urllib.request.urlopen", return_value=response) as opener, \
             mock.patch.object(sheets, "batch_update", side_effect=AssertionError("write")), \
             mock.patch.object(sheets, "batch_values_update", side_effect=AssertionError("write")):
            result = sheets.read_grid_data("sheet-id", a1, "fake-token")
        request = opener.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        query = parse_qs(urlsplit(request.full_url).query)
        self.assertEqual(query["ranges"], [a1])
        self.assertEqual(query["includeGridData"], ["true"])
        fields = query["fields"][0]
        self.assertIn("effectiveValue", fields)
        self.assertIn("userEnteredValue", fields)
        self.assertIn("note", fields)
        self.assertIn("backgroundColor", fields)
        self.assertNotIn("charts", fields)
        self.assertEqual(result, body)


class PreviewCliTest(unittest.TestCase):
    def test_fake_read_only_output_does_not_print_cell_values(self):
        calls = []
        def reader(_sid, a1, _token):
            calls.append(a1)
            return INFO if "INFO" in a1 else PLATAS
        def grid(_sid, a1, _token):
            calls.append("grid:" + a1)
            title = "INFO PEDIDOS POOLEDGE" if "INFO" in a1 else "PLATAS POOLEDGE"
            return {"sheets": [{"properties": {"title": title}, "data": []}]}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(Path, "home", return_value=Path(tmp)), \
                 mock.patch.dict(os.environ, {"LOSETASCHILE_ORDERS_SHEET_ID": "fake-id"}):
                output = io.StringIO()
                with redirect_stdout(output):
                    result = cli.run(["--preview"], token_provider=lambda **kw: "synthetic-token",
                                     values_reader=reader, grid_reader=grid, env_loader=lambda: None)
                self.assertEqual(result, 0)
                self.assertNotIn("Ana", output.getvalue())
                self.assertEqual(len(calls), 4)
                saved_files = list((Path(tmp) / "pooledge-vista-previa").glob("pooledge-historico-*.html"))
                self.assertEqual(len(saved_files), 1)
                saved = saved_files[0]
                second = cli._save_private("otra vista", Path(tmp) / "pooledge-vista-previa")
                self.assertNotEqual(saved, second)
                self.assertIn("otra vista", second.read_text())
                self.assertEqual(second.stat().st_mode & 0o777, 0o600)
                self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
                self.assertIn("Ana", saved.read_text())
                self.assertEqual((Path(tmp) / "pooledge-vista-previa").stat().st_mode & 0o777, 0o700)

    def test_cannot_apply_and_errors_are_redacted(self):
        with self.assertRaises(SystemExit):
            cli.run(["--apply"])
        output = io.StringIO()
        called = []
        def boom(**_kw):
            called.append(True)
            raise RuntimeError("secret-token-value")
        with redirect_stdout(output), \
             mock.patch.dict(os.environ, {"LOSETASCHILE_ORDERS_SHEET_ID": "fake-id"}):
            self.assertEqual(cli.run(["--preview"], token_provider=boom, env_loader=lambda: None), 1)
        self.assertEqual(called, [True])  # el error viene del token, no de la falta de ID
        self.assertNotIn("secret-token-value", output.getvalue())
        self.assertIn("RuntimeError", output.getvalue())

    def test_script_source_has_no_writer_import_or_application_mode(self):
        source = Path(cli.__file__).read_text()
        self.assertNotIn("batch_values_update", source)
        self.assertNotIn("batch_values_clear", source)
        self.assertNotIn("batch_update(", source)
        self.assertIn("--apply", source)  # explicit refusal only


if __name__ == "__main__":
    unittest.main()
