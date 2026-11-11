"""Estructura operativa Pooledge: meta sintética, sin red."""
import json
import os
import re
import stat
import tempfile
import unittest
from unittest import mock
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


def _formulas(plan):
    """(hoja, letra+fila) -> fórmula de cada updateCells con fórmula."""
    titles = plan["summary"]["sheet_titles"]
    out = {}
    for r in plan["requests"]:
        uc = r.get("updateCells")
        if not uc:
            continue
        st = uc["start"]
        for i, row in enumerate(uc["rows"]):
            for j, cell in enumerate(row["values"]):
                f = cell["userEnteredValue"].get("formulaValue")
                if f:
                    out[(titles[str(st["sheetId"])], pl.col_letter(st["columnIndex"] + j), st["rowIndex"] + i + 1)] = f
    return out


def _assert_coherent(tc, plan):
    """Toda fórmula, rango, formato y validación de PLATAS/RESUMEN/COBRANZA sigue a las letras
    derivadas de pl.platas_columns(); expectativas escritas aquí desde L, no copiadas del módulo."""
    L = pl.platas_letters()
    cols = pl.platas_columns()
    ncol = len(cols)
    ids = plan["summary"]["sheet_ids"]
    pid, rid, cid = (ids[t] for t in (C.POOLEDGE_TAB_PLATAS_NEW, C.POOLEDGE_TAB_RESUMEN, C.POOLEDGE_TAB_COBRANZA))
    tc.assertEqual(plan["summary"]["platas_columns"], {L[k]: h for k, h, _ in cols})
    idx = {k: pl._col_index(v) for k, v in L.items()}
    reqs = plan["requests"]

    # Encabezados escritos en A1.. en el mismo orden que las letras.
    heads = next(r["updateCells"] for r in reqs if r.get("updateCells", {}).get("start", {}) ==
                 {"sheetId": pid, "rowIndex": 0, "columnIndex": 0})
    tc.assertEqual([c["userEnteredValue"]["stringValue"] for c in heads["rows"][0]["values"]],
                   [h for _, h, _ in cols])

    # Nada de PLATAS fuera de las columnas definidas; cuadrícula del tamaño exacto.
    grid = next(r["addSheet"]["properties"]["gridProperties"] for r in reqs
                if r.get("addSheet", {}).get("properties", {}).get("sheetId") == pid)
    tc.assertEqual(grid["columnCount"], ncol)
    for r in reqs:
        for body in r.values():
            rng = body.get("range") if isinstance(body, dict) else None
            if isinstance(rng, dict) and rng.get("sheetId") == pid and "endColumnIndex" in rng:
                tc.assertLessEqual(rng["endColumnIndex"], ncol, r)

    def cols_of(pred):
        return sorted({(x["range"]["startColumnIndex"], x["range"]["endColumnIndex"]) for x in
                       (r["repeatCell"] for r in reqs if "repeatCell" in r)
                       if x["range"]["sheetId"] == pid and pred(x["cell"]["userEnteredFormat"])})

    def one(k):
        return (idx[k], idx[k] + 1)
    nf = lambda t: (lambda f: f.get("numberFormat", {}).get("type") == t)  # noqa: E731
    tc.assertEqual(cols_of(nf("DATE")), sorted([one("fecha"), one("fcobro")]))
    money = ["venta", "comision"] + (["costo", "ganancia"] if C.POOLEDGE_TRACK_COST else [])
    tc.assertEqual(cols_of(nf("CURRENCY")), sorted(one(k) for k in money))
    tc.assertEqual(cols_of(nf("TEXT")), [one("id")])

    vals = {(v["range"]["startColumnIndex"], v["rule"]["condition"]["type"]): v for v in
            (r["setDataValidation"] for r in reqs if "setDataValidation" in r) if v["range"]["sheetId"] == pid}
    tc.assertEqual(sorted(vals), sorted([(idx["id"], "ONE_OF_RANGE"), (idx["fecha"], "DATE_IS_VALID"),
                                         (idx["fcobro"], "DATE_IS_VALID"), (idx["cobrado"], "BOOLEAN")]))
    tc.assertEqual(vals[(idx["id"], "ONE_OF_RANGE")]["rule"]["condition"]["values"][0]["userEnteredValue"],
                   "='INFO PEDIDOS POOLEDGE'!J2:J")
    tc.assertTrue(all(v["rule"]["strict"] for v in vals.values()))

    protected = {(r["addProtectedRange"]["protectedRange"]["range"]["startColumnIndex"],
                  r["addProtectedRange"]["protectedRange"]["range"]["endColumnIndex"])
                 for r in reqs if "addProtectedRange" in r}
    calc = ["cliente", "comision", "entregado", "estado"] + (["ganancia"] if C.POOLEDGE_TRACK_COST else [])
    covered = {i for a, b in protected for i in range(a, b)}
    tc.assertEqual(covered, {idx[k] for k in calc})

    cf = [r["addConditionalFormatRule"]["rule"] for r in reqs if "addConditionalFormatRule" in r]
    est = [x for x in cf if x["ranges"][0]["sheetId"] == pid and x["ranges"][0]["startColumnIndex"] == idx["estado"]]
    tc.assertEqual(len(est), 3)
    miss = [x for x in cf if x["ranges"][0]["sheetId"] == pid and x["ranges"][0]["startColumnIndex"] == idx["fcobro"]]
    tc.assertEqual(miss[0]["booleanRule"]["condition"]["values"][0]["userEnteredValue"],
                   f'=AND(${L["cobrado"]}2=TRUE,${L["fcobro"]}2="")')

    # Fórmulas de PLATAS: exactamente las columnas calculadas, con las letras de sus insumos.
    F = _formulas(plan)
    p = C.POOLEDGE_TAB_PLATAS_NEW
    a, e, i, g, c = (f"{L[k]}2:{L[k]}" for k in ("id", "venta", "cobrado", "entregado", "cliente"))
    own = {k[1]: v for k, v in F.items() if k[0] == p}
    tc.assertEqual(set(own), {L[k] for k in calc})
    tc.assertIn(f'=MAP({a}, LAMBDA(id,', own[L["cliente"]])
    tc.assertIn(f'=ARRAYFORMULA(IF({a}="",,ROUND({e}*', own[L["comision"]])
    tc.assertIn("'INFO PEDIDOS POOLEDGE'!G:G", own[L["entregado"]])
    tc.assertEqual(own[L["estado"]], f'=ARRAYFORMULA(IF({a}="",,IF({i}=TRUE,"Cobrada",IF({g}="Sí","Por cobrar","Futura"))))')
    refs = lambda f: set(re.findall(r"(?<![A-Z'!])([A-Z]{1,2})2:\1\b", re.sub(r"'[^']*'!", "!", f)))  # noqa: E731
    for letter, f in own.items():
        for ref in refs(f):
            tc.assertIn(ref, L.values(), f)

    # RESUMEN y COBRANZA: las únicas letras de PLATAS que citan son las de sus insumos.
    def platas_letters_in(tab):
        found = set()
        for (t, _, _), f in F.items():
            if t == tab:
                for m in re.finditer(r"'PLATAS 2026'!([A-Z]+)\d*(?::([A-Z]+)\d*)?", f):
                    found |= {m.group(1), m.group(2) or m.group(1)}
        return found
    tc.assertEqual(platas_letters_in(C.POOLEDGE_TAB_RESUMEN),
                   {L[k] for k in ("estado", "comision", "venta", "id", "fecha")}
                   | ({L["ganancia"]} if C.POOLEDGE_TRACK_COST else set()))
    tc.assertEqual(platas_letters_in(C.POOLEDGE_TAB_COBRANZA), {"A", L["fcobro"], L["estado"], L["comision"], L["id"]})
    pos = lambda k: [h for _, h, _ in cols].index(dict((kk, hh) for kk, hh, _ in cols)[k]) + 1  # noqa: E731
    cob = {f"{k[1]}{k[2]}": v for k, v in F.items() if k[0] == C.POOLEDGE_TAB_COBRANZA}
    src = f"'PLATAS 2026'!A2:{L['fcobro']}"
    tc.assertIn(f"CHOOSECOLS(FILTER({src}, 'PLATAS 2026'!{L['estado']}2:{L['estado']}=\"Por cobrar\"), "
                f"{pos('id')}, {pos('cliente')}, {pos('fecha')})", cob["B6"])
    tc.assertIn(f"{pos('id')}, {pos('cliente')}, {pos('fecha')}, {pos('comision')})", cob["H6"])
    tc.assertIn(f"{pos('id')}, {pos('cliente')}, {pos('comision')}, {pos('fcobro')}), 4, FALSE)", cob["M6"])
    tc.assertIn(f"XLOOKUP(id, 'PLATAS 2026'!{L['id']}:{L['id']}, 'PLATAS 2026'!{L['comision']}:{L['comision']})", cob["F6"])
    for letter, state in (("F", "Por cobrar"), ("K", "Futura"), ("P", "Cobrada")):
        tc.assertEqual(cob[letter + "3"], f"=SUMIF('PLATAS 2026'!{L['estado']}2:{L['estado']},\"{state}\","
                                    f"'PLATAS 2026'!{L['comision']}2:{L['comision']})")
    res = {f"{k[1]}{k[2]}": v for k, v in F.items() if k[0] == C.POOLEDGE_TAB_RESUMEN}
    tc.assertEqual(res["B5"], f"=SUMIF('PLATAS 2026'!{L['estado']}2:{L['estado']},\"Cobrada\","
                              f"'PLATAS 2026'!{L['comision']}2:{L['comision']})")
    tc.assertEqual(res["E5"], f"=SUM('PLATAS 2026'!{L['venta']}2:{L['venta']})")
    tc.assertEqual(res["F5"], f"=COUNTA('PLATAS 2026'!{L['id']}2:{L['id']})")
    last = pl.resumen_letters()["comision"]
    tc.assertEqual(res[last + "21"], f"=SUM({last}9:{last}20)")
    tc.assertIn(f"SUMIFS('PLATAS 2026'!{L['comision']}2:{L['comision']},'PLATAS 2026'!{L['fecha']}2:{L['fecha']}", res[last + "9"])


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

    def test_info_only_gets_j1_header_value(self):
        info_cells = [r["updateCells"] for r in self.plan["requests"]
                      if r.get("updateCells", {}).get("start", {}).get("sheetId") == 0]
        self.assertEqual(len(info_cells), 1)
        self.assertEqual(info_cells[0]["start"], {"sheetId": 0, "rowIndex": 0, "columnIndex": 9})
        self.assertEqual(info_cells[0]["rows"], [{"values": [{"userEnteredValue": {"stringValue": "ID PEDIDO"}}]}])
        # Ninguna otra escritura de valores en INFO: sin pegado, sin append, sin fórmulas.
        for r in self.plan["requests"]:
            for kind in ("appendCells", "pasteData", "updateCells"):
                if kind in r and kind != "updateCells":
                    self.fail(kind)

    def test_info_validations_and_styles(self):
        reqs = [r for r in self.plan["requests"] if "setDataValidation" in r
                and r["setDataValidation"]["range"]["sheetId"] == 0]
        by_col = {r["setDataValidation"]["range"]["startColumnIndex"]: r["setDataValidation"] for r in reqs}
        self.assertEqual(by_col[6]["rule"]["condition"], {"type": "BOOLEAN"})
        self.assertEqual(by_col[6]["range"]["startRowIndex"], 1)
        j = by_col[9]
        self.assertEqual(j["rule"]["condition"]["type"], "CUSTOM_FORMULA")
        self.assertEqual(j["rule"]["condition"]["values"][0]["userEnteredValue"], "=COUNTIF(J:J,J2)=1")
        self.assertTrue(j["rule"]["strict"])
        self.assertEqual(j["range"]["startRowIndex"], 1)

    def test_g_invalid_count_is_only_a_count_and_warns(self):
        plan = pl.build_plan(_meta(), LAST, info_g_invalid=3)
        self.assertEqual(plan["summary"]["info_g_invalid"], 3)
        self.assertTrue(plan["summary"]["warnings"])
        self.assertIn("3 celda", plan["summary"]["warnings"][0])
        self.assertFalse(pl.build_plan(_meta(), LAST)["summary"]["warnings"])
        self.assertNotEqual(pl.plan_fingerprint(plan), pl.plan_fingerprint(self.plan))
        self.assertIn("Avisos", pl.render_plan_html(plan))

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
        self.assertEqual(len(texts), 1)
        self.assertEqual((texts[0]["startColumnIndex"], texts[0]["endColumnIndex"]), (0, 1))

    def test_no_iva_total_nor_hidden_columns(self):
        self.assertFalse(hasattr(C, "POOLEDGE_SHOW_IVA"))
        self.assertFalse([r for r in self.plan["requests"] if "updateDimensionProperties" in r
                          and r["updateDimensionProperties"]["properties"].get("hiddenByUser")])
        self.assertEqual({"IVA", "TOTAL"} & set(self.plan["summary"]["platas_columns"].values()), set())
        self.assertNotIn("0.19", json.dumps(self.plan))
        self.assertNotRegex(json.dumps(self.plan), r"\bIVA\b")

    def test_j1_must_be_empty_or_already_the_header(self):
        with self.assertRaises(pl.LayoutError) as ctx:
            pl.build_plan(_meta(), LAST, "Dato Secreto")
        self.assertNotIn("Secreto", str(ctx.exception))
        same = pl.build_plan(_meta(), LAST, "ID PEDIDO")
        self.assertFalse([r for r in same["requests"] if r.get("updateCells", {}).get("start", {})
                          .get("sheetId") == 0])
        self.assertTrue(same["summary"]["info_j1_has_header"])
        self.assertNotEqual(pl.plan_fingerprint(same), pl.plan_fingerprint(self.plan))
        # datos en J2:J no estorban: el script solo pasa J1
        self.assertTrue(pl.build_plan(_meta(), LAST, ""))

    def test_precios_banding_skipped_when_overlapping(self):
        def meta_with(bands):
            m = _meta()
            m["sheets"].append({"properties": {"sheetId": 55, "title": C.POOLEDGE_TAB_PRECIOS,
                                               "gridProperties": {"rowCount": 200, "columnCount": 11}},
                                "bandedRanges": bands})
            return m
        for bands in ([], [{"range": {"sheetId": 55, "startRowIndex": 20, "endRowIndex": 30,
                                      "startColumnIndex": 12, "endColumnIndex": 14}}]):
            plan = pl.build_plan(meta_with(bands), LAST)
            self.assertEqual(len([r for r in plan["requests"] if "addBanding" in r]), 1)
            self.assertFalse(plan["summary"]["warnings"])
        for band in ({"range": {"sheetId": 55, "startRowIndex": 0, "endRowIndex": 200}},   # sin columnas: toda la hoja
                     {"range": {"sheetId": 55, "startRowIndex": 5, "endRowIndex": 9,
                                "startColumnIndex": 2, "endColumnIndex": 3}}):
            plan = pl.build_plan(meta_with([band]), LAST)
            self.assertFalse([r for r in plan["requests"] if "addBanding" in r])
            self.assertIn("ya tiene colores alternos; se dejan los existentes",
                          " ".join(plan["summary"]["warnings"]))
        # el resto del estilo sigue aplicándose
        self.assertTrue([r for r in plan["requests"] if r.get("updateSheetProperties", {})
                         .get("properties", {}).get("sheetId") == 55])
        # solo PLATAS/RESUMEN/COBRANZA reciben addProtectedRange (hojas nuevas): nada choca en INFO/PRECIOS
        for r in plan["requests"]:
            if "addProtectedRange" in r:
                self.assertIn(r["addProtectedRange"]["protectedRange"]["range"]["sheetId"],
                              plan["summary"]["sheet_ids"].values())

    def test_text_map_formulas_return_empty_string_numeric_stay_empty(self):
        f = {k[1]: v for k, v in _formulas(self.plan).items() if k[0] == C.POOLEDGE_TAB_PLATAS_NEW}
        self.assertIn('IF(id="","", XLOOKUP', f["C"])
        self.assertIn('IF(id="","", IF(XLOOKUP', f["G"])
        self.assertNotIn('IF(id="",,', f["C"] + f["G"])
        self.assertIn('IF(A2:A="",,ROUND(', f["F"])

    def test_formulas_use_config_rate_and_english_syntax(self):
        formulas = _formulas(self.plan)
        self.assertTrue(any("ROUND(E2:E*0.1)" in f for f in formulas.values()))
        with mock.patch.object(C, "POOLEDGE_COMMISSION_RATE", 0.15):
            other = _formulas(pl.build_plan(_meta(), LAST))
        self.assertTrue(any("ROUND(E2:E*0.15)" in f for f in other.values()))
        for state in C.POOLEDGE_COMMISSION_STATES:
            self.assertIn(state, " ".join(formulas.values()))
        for f in formulas.values():
            outside = re.sub(r'"[^"]*"', "", f)
            self.assertNotIn(";", outside, f)          # el ; de la ficha es sintaxis Chile, no API
            self.assertNotRegex(outside, r"\*\s*\d+,\d")  # coma decimal tampoco

    def test_cost_off_has_no_cost_or_profit_anywhere(self):
        self.assertFalse(C.POOLEDGE_TRACK_COST)
        self.assertEqual(list(pl.platas_letters()), ["id", "fecha", "cliente", "detalle", "venta", "comision",
                                                      "entregado", "estado", "cobrado", "fcobro"])
        text = json.dumps(self.plan, ensure_ascii=False)
        for word in ("COSTO", "GANANCIA", "Ganancia"):
            self.assertNotIn(word, text)
        self.assertEqual(self.plan["summary"]["platas_columns"]["J"], "FECHA COBRO")
        self.assertNotIn("K", self.plan["summary"]["platas_columns"])

    def test_cost_on_appends_k_l_without_moving_letters(self):
        base = pl.platas_letters()
        with mock.patch.object(C, "POOLEDGE_TRACK_COST", True):
            on = pl.build_plan(_meta(), LAST)
            L = pl.platas_letters()
            self.assertEqual({k: v for k, v in L.items() if k in base}, base)
            self.assertEqual((L["costo"], L["ganancia"]), ("K", "L"))
            self.assertEqual(on["summary"]["platas_columns"]["K"], "COSTO BASE NETO")
            self.assertEqual(on["summary"]["platas_columns"]["L"], "GANANCIA")
            f = _formulas(on)
            self.assertTrue(any(v == "=ARRAYFORMULA(IF(A2:A=\"\",,E2:E-K2:K))" for v in f.values()))
            # RESUMEN: columna de ganancia mensual (E) y comisión pasa a F
            self.assertEqual(pl.resumen_letters(), {"mes": "B", "pedidos": "C", "venta": "D",
                                                    "ganancia": "E", "comision": "F"})
            self.assertIn("'PLATAS 2026'!L2:L", " ".join(f.values()))
            # alerta de ganancia negativa solo con el flag
            lt = [r for r in on["requests"] if r.get("addConditionalFormatRule", {}).get("rule", {})
                  .get("booleanRule", {}).get("condition", {}).get("type") == "NUMBER_LESS"]
            self.assertEqual(len(lt), 1)
            _assert_coherent(self, on)
        self.assertFalse([r for r in self.plan["requests"] if r.get("addConditionalFormatRule", {})
                          .get("rule", {}).get("booleanRule", {}).get("condition", {}).get("type") == "NUMBER_LESS"])

    def test_coherent_letters_default(self):
        _assert_coherent(self, self.plan)

    def test_coherent_letters_follow_a_single_definition(self):
        # Si alguien mueve una columna, TODO lo derivado la sigue; un literal viejo haría fallar esto.
        base = list(pl._PLATAS_BASE)
        swapped = base[:3] + [base[4], base[3]] + base[5:]      # VENTA NETA antes de DETALLE
        with mock.patch.object(pl, "_PLATAS_BASE", tuple(swapped)):
            self.assertEqual(pl.platas_letters()["venta"], "D")
            _assert_coherent(self, pl.build_plan(_meta(), LAST))

    def test_resumen_and_chart(self):
        reqs = self.plan["requests"]
        rid = self.plan["summary"]["sheet_ids"][C.POOLEDGE_TAB_RESUMEN]
        charts = [r["addChart"]["chart"] for r in reqs if "addChart" in r]
        self.assertEqual(len(charts), 1)
        spec = charts[0]["spec"]
        self.assertEqual(spec["basicChart"]["chartType"], "COLUMN")
        self.assertEqual(spec["title"], "Comisión por mes")
        pos = charts[0]["position"]["overlayPosition"]
        self.assertEqual((pos["anchorCell"], pos["widthPixels"], pos["heightPixels"]),
                         ({"sheetId": rid, "rowIndex": 6, "columnIndex": 7}, 520, 408))
        ser = spec["basicChart"]["series"][0]["series"]["sourceRange"]["sources"][0]
        self.assertEqual((ser["startColumnIndex"], ser["startRowIndex"], ser["endRowIndex"]), (4, 7, 20))  # E8:E20
        dom = spec["basicChart"]["domains"][0]["domain"]["sourceRange"]["sources"][0]
        self.assertEqual(dom["startColumnIndex"], 1)

    def test_gridlines_hidden_and_frozen(self):
        adds = {r["addSheet"]["properties"]["title"]: r["addSheet"]["properties"]["gridProperties"]
                for r in self.plan["requests"] if "addSheet" in r}
        for gp in adds.values():
            self.assertTrue(gp["hideGridlines"])
        self.assertEqual(adds[C.POOLEDGE_TAB_PLATAS_NEW]["frozenRowCount"], 1)
        self.assertEqual(adds[C.POOLEDGE_TAB_PLATAS_NEW]["columnCount"], 10)
        self.assertEqual(adds[C.POOLEDGE_TAB_COBRANZA]["frozenRowCount"], 5)

    def test_precios_only_style_and_no_hide(self):
        meta = _meta()
        meta["sheets"].append({"properties": {"sheetId": 55, "title": C.POOLEDGE_TAB_PRECIOS,
                                              "gridProperties": {"rowCount": 200, "columnCount": 11}}})
        plan = pl.build_plan(meta, LAST)
        mine = [r for r in plan["requests"] if any(isinstance(v, dict) and (
            v.get("range", {}).get("sheetId") == 55 or v.get("sheetId") == 55
            or v.get("properties", {}).get("sheetId") == 55) for v in r.values())]
        self.assertTrue(mine)
        self.assertFalse([r for r in mine if "updateCells" in r])
        self.assertFalse([r for r in mine if r.get("updateDimensionProperties", {})
                          .get("properties", {}).get("hiddenByUser")])
        self.assertEqual([r["addBanding"]["bandedRange"]["range"]["sheetId"]
                          for r in plan["requests"] if "addBanding" in r], [55])
        self.assertIn("NO se ocultan", " ".join(plan["summary"]["formats"]))
        self.assertFalse([r for r in self.plan["requests"] if "addBanding" in r])  # sin pestaña: se omite

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
        self.assertIn("$15.000", page)
        self.assertNotIn("$28.500", page)


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
        if rng.endswith("!J1"):
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
            [["Dato Secreto"]] if rng.endswith("!J1") else [["x"]])
        self.assertEqual(self.run_cli(["--preview"], api), 1)
        self.assertIn("INFO!J1", self.out[-1])
        self.assertNotIn("Secreto", self.out[-1])

    def test_g_invalid_count_reaches_preview_without_content(self):
        api = FakeApi()
        base = api.read
        api.read = lambda sid, rng, token, render="FORMATTED_VALUE": (
            [["ENTREGADO"], ["TRUE"], ["false"], [""], ["Sí-SECRETO"], ["x"]] if rng.endswith("!G:G")
            else base(sid, rng, token, render))
        self.assertEqual(self.run_cli(["--preview"], api), 0)
        page = next(self.dir.glob("pooledge-estructura-*.html")).read_text()
        self.assertIn("2 celda(s)", page)
        self.assertNotIn("SECRETO", page + "".join(self.out))
        self.assertEqual(cli._invalid_checkbox_count([["h"], ["TRUE"], ["No"], []]), 1)

    def test_last_row_counts_any_column(self):
        self.assertEqual(cli._last_row([["a"], [], ["", "", "b"], [""], []]), 3)

    def test_last_row_in_script_uses_columns_b_to_i(self):
        # el fake deja dato solo en I de la fila LAST: build_plan debe partir de ahí
        self.run_cli(["--preview"])
        html_file = next(self.dir.glob("pooledge-estructura-*.html"))
        self.assertIn(f"hasta la {LAST}.", html_file.read_text())


if __name__ == "__main__":
    unittest.main()
