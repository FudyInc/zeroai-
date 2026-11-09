"""Estructura operativa Pooledge: meta sintética, sin red."""
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from scripts import pooledge_estructura as cli
from zero import config as C
from zero import pooledge_layout as pl


def _meta(extra=(), info_rows=99):
    sheets = [
        {"properties": {"sheetId": 0, "title": C.POOLEDGE_TAB_INFO,
                        "gridProperties": {"rowCount": 1000, "columnCount": 26}}},
        {"properties": {"sheetId": 2026001, "title": C.POOLEDGE_TAB_PLATAS,
                        "gridProperties": {"rowCount": 100, "columnCount": 10}}},
    ]
    sheets += [{"properties": {"sheetId": 7 + i, "title": t}} for i, t in enumerate(extra)]
    return {"sheets": sheets}


LAST = 100


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.plan = pl.build_plan(_meta(), LAST)

    def test_creates_three_tabs_with_unique_ids(self):
        adds = [r["addSheet"]["properties"] for r in self.plan["requests"] if "addSheet" in r]
        self.assertEqual([a["title"] for a in adds],
                         [C.POOLEDGE_TAB_PLATAS_NEW, C.POOLEDGE_TAB_RESUMEN, C.POOLEDGE_TAB_COBRANZA])
        ids = [a["sheetId"] for a in adds]
        self.assertEqual(len(set(ids)), 3)
        self.assertFalse({0, 2026001} & set(ids))

    def test_errors_on_existing_destination_or_missing_source(self):
        with self.assertRaises(pl.LayoutError):
            pl.build_plan(_meta(extra=[C.POOLEDGE_TAB_RESUMEN]), LAST)
        with self.assertRaises(pl.LayoutError):
            pl.build_plan({"sheets": _meta()["sheets"][:1]}, LAST)
        with self.assertRaises(pl.LayoutError):
            pl.build_plan(_meta(), 0)

    def test_info_untouched_before_first_new_row(self):
        info_id = 0
        touched = 0
        for r in self.plan["requests"]:
            for body in r.values():
                rng = body.get("range") if isinstance(body, dict) else None
                if rng and rng.get("sheetId") == info_id:
                    touched += 1
                    if rng["startColumnIndex"] == 9 and rng["endRowIndex"] == 1:  # J1: encabezado vacío
                        self.assertEqual(rng["startRowIndex"], 0)
                    else:
                        self.assertEqual(rng["startRowIndex"], LAST)  # fila LAST+1, 0-based
        self.assertEqual(touched, 4)
        info_cells = [r["updateCells"] for r in self.plan["requests"]
                      if r.get("updateCells", {}).get("start", {}).get("sheetId") == info_id]
        self.assertEqual(len(info_cells), 1)
        self.assertEqual(info_cells[0]["start"], {"sheetId": 0, "rowIndex": 0, "columnIndex": 9})
        self.assertEqual(info_cells[0]["rows"], [{"values": [{"userEnteredValue": {"stringValue": "ID PEDIDO"}}]}])

    def test_everything_in_requests_with_updatecells_after_addsheet(self):
        self.assertNotIn("values", self.plan)
        kinds = [next(iter(r)) for r in self.plan["requests"]]
        last_add = max(i for i, k in enumerate(kinds) if k == "addSheet")
        first_cells = min(i for i, k in enumerate(kinds) if k == "updateCells")
        self.assertGreater(first_cells, last_add)
        formulas = [c["userEnteredValue"]["formulaValue"] for r in self.plan["requests"] if "updateCells" in r
                    for row in r["updateCells"]["rows"] for c in row["values"]
                    if "formulaValue" in c["userEnteredValue"]]
        self.assertGreaterEqual(len(formulas), 10)
        self.assertTrue(all(f.startswith("=") for f in formulas))

    def test_text_format_for_ids(self):
        texts = [r["repeatCell"]["range"] for r in self.plan["requests"]
                 if r.get("repeatCell", {}).get("cell", {}).get("userEnteredFormat", {})
                 .get("numberFormat", {}).get("type") == "TEXT"]
        self.assertEqual(len(texts), 2)
        self.assertIn(LAST, [t["startRowIndex"] for t in texts])

    def test_j_with_content_raises(self):
        with self.assertRaises(pl.LayoutError):
            pl.build_plan(_meta(), LAST, 1)

    def test_formulas_use_config_rates(self):
        text = json.dumps([r for r in self.plan["requests"] if "updateCells" in r], ensure_ascii=False)
        self.assertIn("F2:F*0.19", text)
        self.assertIn("FILTER(", text)
        self.assertIn("F2:F*0.1)", text)
        for state in C.POOLEDGE_COMMISSION_STATES:
            self.assertIn(state, text)
        self.assertIn("VLOOKUP(A2:A,{\'INFO PEDIDOS POOLEDGE\'!J2:J,\'INFO PEDIDOS POOLEDGE\'!G2:G},2,FALSE)".replace("\\'", "'"),
                      text.replace("\\'", "'"))

    def test_fingerprint_deterministic(self):
        again = pl.build_plan(_meta(), LAST)
        self.assertEqual(pl.plan_fingerprint(self.plan), pl.plan_fingerprint(again))
        self.assertNotEqual(pl.plan_fingerprint(self.plan),
                            pl.plan_fingerprint(pl.build_plan(_meta(), LAST + 1)))

    def test_html_escaped_and_self_contained(self):
        plan = json.loads(json.dumps(self.plan))
        plan["summary"]["tabs_to_create"].append("<script>x</script>")
        page = pl.render_plan_html(plan)
        self.assertNotIn("<script>x", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("<body>", page)
        self.assertIn("$150.000", page)
        self.assertIn("$28.500", page)
        self.assertIn("$15.000", page)


class FakeApi:
    def __init__(self, fail_backup=False, fail_batch=False):
        self.fail_batch = fail_batch
        self.calls = []
        self.fail_backup = fail_backup

    def token(self, scope=None):
        self.calls.append(("token", scope))
        return "tok"

    def meta(self, sid, token):
        return _meta()

    def read(self, sid, rng, token, render="FORMATTED_VALUE"):
        self.calls.append(("read", render))
        if render == "FORMULA" and self.fail_backup:
            raise RuntimeError("SECRETO-DE-LA-HOJA")
        if rng.endswith("!A:I"):
            return [["x"]] * (LAST - 1) + [[""] * 8 + ["abono"]]
        if rng.endswith("!J:J"):
            return []
        return [["dato privado"]]

    def grid(self, sid, rng, token):
        self.calls.append(("grid", rng))
        return {"sheets": []}

    def batch(self, sid, reqs, token):
        self.calls.append(("batch", len(reqs)))
        if self.fail_batch:
            raise RuntimeError("SECRETO-BATCH")


class ScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name) / "priv"
        self.out = []
        self.api = FakeApi()
        self.fp = pl.plan_fingerprint(pl.build_plan(_meta(), LAST))
        os.environ[C.POOLEDGE_ORDERS_SHEET_ENV] = "sheet-id"
        self.addCleanup(os.environ.pop, C.POOLEDGE_ORDERS_SHEET_ENV, None)

    def run_cli(self, argv, api=None):
        api = api or self.api
        return cli.run(argv, token_provider=api.token, meta_reader=api.meta, values_reader=api.read,
                       batch_updater=api.batch, grid_reader=api.grid, env_loader=lambda: None,
                       directory=self.dir, output=self.out.append)

    def test_parser_errors(self):
        for argv in ([], ["--apply"]):
            with self.assertRaises(SystemExit):
                self.run_cli(argv)

    def test_preview_never_writes(self):
        self.assertEqual(self.run_cli(["--preview"]), 0)
        names = [c[0] for c in self.api.calls]
        self.assertNotIn("batch", names)
        self.assertEqual(self.api.calls[0], ("token", cli.sheets._READONLY_SCOPE))
        files = list(self.dir.glob("pooledge-estructura-*.html"))
        self.assertEqual(len(files), 1)
        self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)
        self.assertIn(self.fp, self.out[0])

    def test_apply_wrong_fingerprint_does_not_write(self):
        self.assertEqual(self.run_cli(["--apply", "--fingerprint", "0000"]), 1)
        self.assertNotIn("batch", [c[0] for c in self.api.calls])
        self.assertFalse(list(self.dir.glob("pooledge-respaldo-*")))
        self.assertNotIn(self.fp, "".join(self.out))

    def test_apply_backs_up_before_writing(self):
        self.assertEqual(self.run_cli(["--apply", "--fingerprint", self.fp]), 0)
        names = [c[0] if c[0] != "read" else f"read:{c[1]}" for c in self.api.calls]
        self.assertLess(max(i for i, n in enumerate(names) if n == "read:FORMULA"), names.index("batch"))
        self.assertEqual(names.count("batch"), 1)
        self.assertEqual(len([c for c in self.api.calls if c[0] == "grid"]), 1)
        self.assertEqual(len([n for n in names if n == "read:FORMULA"]), 3)
        backup = list(self.dir.glob("pooledge-respaldo-*.json"))
        self.assertEqual(len(backup), 1)
        self.assertEqual(stat.S_IMODE(backup[0].stat().st_mode), 0o600)
        audit = (self.dir / "pooledge-auditoria.log").read_text().splitlines()
        self.assertEqual(len(audit), 2)
        self.assertNotIn("dato privado", "".join(audit) + "".join(self.out))

    def test_backup_failure_aborts_and_error_is_redacted(self):
        api = FakeApi(fail_backup=True)
        self.assertEqual(self.run_cli(["--apply", "--fingerprint", self.fp], api), 1)
        self.assertNotIn("batch", [c[0] for c in api.calls])
        self.assertNotIn("SECRETO", "".join(self.out))
        self.assertIn("RuntimeError", self.out[-1])

    def test_batch_failure_logs_failed_and_returns_1(self):
        api = FakeApi(fail_batch=True)
        self.assertEqual(self.run_cli(["--apply", "--fingerprint", self.fp], api), 1)
        self.assertEqual([c[0] for c in api.calls].count("batch"), 1)
        audit = (self.dir / "pooledge-auditoria.log").read_text().splitlines()
        self.assertEqual([json.loads(l)["estado"] for l in audit], ["aplicando", "fallido"])
        self.assertNotIn("SECRETO", "".join(self.out))

    def test_final_audit_failure_still_returns_0(self):
        real = cli._audit
        calls = []

        def flaky(directory, entry):
            calls.append(entry["estado"])
            if entry["estado"] == "aplicado":
                raise OSError("disco")
            real(directory, entry)
        cli._audit = flaky
        self.addCleanup(setattr, cli, "_audit", real)
        self.assertEqual(self.run_cli(["--apply", "--fingerprint", self.fp]), 0)
        self.assertIn("el registro de auditoría falló", self.out[-1])

    def test_layout_error_message_is_shown_without_cells(self):
        api = FakeApi()
        api.read = lambda sid, rng, token, render="FORMATTED_VALUE": (
            [["Dato Secreto"]] if rng.endswith("!J:J") else [["x"]])
        self.assertEqual(self.run_cli(["--preview"], api), 1)
        self.assertIn("columna J", self.out[-1])
        self.assertNotIn("Secreto", self.out[-1])

    def test_last_row_counts_any_column(self):
        self.assertEqual(cli._last_row([["a"], [], ["", "", "b"], [""], []]), 3)
        self.assertEqual(cli._nonempty_count([["", "x"], ["y"]]), 2)

    def test_last_row_in_script_uses_columns_b_to_i(self):
        # el fake deja dato solo en I de la fila LAST: build_plan debe partir de ahí
        self.run_cli(["--preview"])
        html_file = next(self.dir.glob("pooledge-estructura-*.html"))
        self.assertIn(f"hasta la {LAST};", html_file.read_text())


if __name__ == "__main__":
    unittest.main()
