"""Tests de zero/board.py — render Kanban del CRM (presentación pura).

test_core ya cubre render_lead. Aquí se prueban los helpers (_fit, _paint,
_column) y render() completo, siempre con color=False para salida determinista
(sin ANSI). Un CRM falso alimenta counts/list, sin tocar crm.json.
"""
import unittest

from zero import board
from zero.config import CRM_STAGES


class _FakeCRM:
    """CRM mínimo para el render: leads agrupados por etapa."""
    def __init__(self, by_stage=None):
        self.by_stage = by_stage or {}

    def counts(self, client):
        return {s: len(self.by_stage.get(s, [])) for s in CRM_STAGES}

    def list(self, client, stage=None):
        return self.by_stage.get(stage, [])


class TestFit(unittest.TestCase):
    def test_pad_a_ancho_exacto(self):
        out = board._fit("hola", width=10)
        self.assertEqual(len(out), 10)
        self.assertTrue(out.startswith("hola"))

    def test_trunca_con_elipsis(self):
        out = board._fit("abcdefghij", width=5)
        self.assertEqual(len(out), 5)
        self.assertTrue(out.endswith("…"))

    def test_none_da_ancho_en_blanco(self):
        self.assertEqual(board._fit(None, width=6), " " * 6)


class TestPaint(unittest.TestCase):
    def test_off_no_agrega_ansi(self):
        self.assertEqual(board._paint("x", "91", on=False), "x")

    def test_on_envuelve_ansi(self):
        out = board._paint("x", "91", on=True)
        self.assertIn("\033[91m", out)
        self.assertTrue(out.endswith(board._RESET))


class TestColumn(unittest.TestCase):
    def test_vacia_muestra_vacio(self):
        lines = board._column("new", [], "90", on=False, max_cards=5)
        self.assertTrue(any("(vacío)" in ln for ln in lines))

    def test_muestra_score_y_empresa(self):
        leads = [{"company": "Acme", "score": 88, "email": "a@acme.cl"}]
        blob = "\n".join(board._column("new", leads, "90", on=False, max_cards=5))
        self.assertIn("[88]", blob)
        self.assertIn("Acme", blob)

    def test_score_none_usa_guion(self):
        leads = [{"company": "Acme", "score": None}]
        blob = "\n".join(board._column("new", leads, "90", on=False, max_cards=5))
        self.assertIn("[—]", blob)

    def test_excedente_muestra_mas(self):
        leads = [{"company": f"C{i}", "score": 70} for i in range(8)]
        blob = "\n".join(board._column("new", leads, "90", on=False, max_cards=5))
        self.assertIn("+3 más", blob)


class TestRender(unittest.TestCase):
    def test_vacio_avisa(self):
        out = board.render(_FakeCRM(), "acme", color=False)
        self.assertIn("vacío", out)

    def test_incluye_cliente_y_total(self):
        crm = _FakeCRM({"new": [{"company": "Acme", "score": 80}],
                        "qualified": [{"company": "Beta", "score": 90}]})
        out = board.render(crm, "acme", color=False, width=200)
        self.assertIn("acme", out)
        self.assertIn("(2 leads)", out)
        self.assertIn("Acme", out)
        self.assertIn("Beta", out)

    def test_color_false_sin_ansi(self):
        crm = _FakeCRM({"new": [{"company": "Acme", "score": 80}]})
        out = board.render(crm, "acme", color=False, width=200)
        self.assertNotIn("\033", out)


if __name__ == "__main__":
    unittest.main()
