"""Tests de zero/icp.py — normalización y descripción del Ideal Customer Profile.

icp.py es política pura y determinista: normaliza lo que venga y nunca lanza.
Estos tests fijan ese contrato (forma fija, degradación a genérico, sin excepciones).
"""
import unittest

from zero import icp


class TestAsList(unittest.TestCase):
    def test_none_da_lista_vacia(self):
        self.assertEqual(icp._as_list(None), [])

    def test_lista_se_limpia_y_stringifica(self):
        self.assertEqual(icp._as_list([" ceo ", "cto", 42]), ["ceo", "cto", "42"])

    def test_tupla_soportada(self):
        self.assertEqual(icp._as_list(("a", "b")), ["a", "b"])

    def test_string_csv_se_divide(self):
        self.assertEqual(icp._as_list("ceo, gerente comercial"), ["ceo", "gerente comercial"])

    def test_string_simple(self):
        self.assertEqual(icp._as_list("ceo"), ["ceo"])

    def test_vacios_se_descartan(self):
        self.assertEqual(icp._as_list(["", "  ", "x"]), ["x"])
        self.assertEqual(icp._as_list("a, , ,b"), ["a", "b"])


class TestNormalizeIcp(unittest.TestCase):
    def test_none_da_forma_fija_completa(self):
        out = icp.normalize_icp(None)
        self.assertEqual(set(out), set(icp.FIELDS))

    def test_no_dict_degrada_sin_lanzar(self):
        for bad in ["texto", 123, ["lista"], object()]:
            out = icp.normalize_icp(bad)
            self.assertEqual(set(out), set(icp.FIELDS))
            self.assertTrue(icp.is_empty(out))

    def test_list_fields_son_listas(self):
        out = icp.normalize_icp({})
        for f in icp._LIST_FIELDS:
            self.assertIsInstance(out[f], list)

    def test_scalar_fields_son_strings(self):
        out = icp.normalize_icp({})
        scalars = set(icp.FIELDS) - set(icp._LIST_FIELDS)
        for f in scalars:
            self.assertEqual(out[f], "")

    def test_valores_se_normalizan(self):
        out = icp.normalize_icp({
            "industry": "  Fintech ",
            "buyer_roles": "ceo, cfo",
            "company_size": None,
        })
        self.assertEqual(out["industry"], "Fintech")
        self.assertEqual(out["buyer_roles"], ["ceo", "cfo"])
        self.assertEqual(out["company_size"], "")

    def test_campos_desconocidos_se_ignoran(self):
        out = icp.normalize_icp({"industry": "x", "basura": "y"})
        self.assertNotIn("basura", out)

    def test_idempotente(self):
        raw = {"sells": "cajas", "regions": ["RM", "V"]}
        once = icp.normalize_icp(raw)
        twice = icp.normalize_icp(once)
        self.assertEqual(once, twice)


class TestIsEmpty(unittest.TestCase):
    def test_none_es_vacio(self):
        self.assertTrue(icp.is_empty(None))

    def test_dict_vacio_es_vacio(self):
        self.assertTrue(icp.is_empty({}))

    def test_con_un_campo_no_es_vacio(self):
        self.assertFalse(icp.is_empty({"sells": "cajas"}))

    def test_solo_lista_cuenta(self):
        self.assertFalse(icp.is_empty({"regions": ["RM"]}))


class TestDescribeIcp(unittest.TestCase):
    def test_vacio_da_generico(self):
        self.assertEqual(icp.describe_icp(None), "ICP genérico (sin definir)")
        self.assertEqual(icp.describe_icp({}), "ICP genérico (sin definir)")

    def test_incluye_lo_que_vende(self):
        self.assertIn("vende cajas", icp.describe_icp({"sells": "cajas"}))

    def test_junta_partes_con_separador(self):
        out = icp.describe_icp({"sells": "cajas", "industry": "retail"})
        self.assertIn(" · ", out)
        self.assertIn("vende cajas", out)
        self.assertIn("rubro retail", out)

    def test_roles_y_zonas_se_unen_con_slash(self):
        out = icp.describe_icp({"buyer_roles": ["ceo", "cfo"], "regions": ["RM", "V"]})
        self.assertIn("decisor ceo/cfo", out)
        self.assertIn("zona RM/V", out)

    def test_must_have_se_une_con_coma(self):
        out = icp.describe_icp({"must_have": ["a", "b"]})
        self.assertIn("requiere a, b", out)

    def test_nunca_lanza_con_basura(self):
        for bad in [None, 123, "texto", ["x"]]:
            self.assertIsInstance(icp.describe_icp(bad), str)


if __name__ == "__main__":
    unittest.main()
