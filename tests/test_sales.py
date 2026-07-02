"""Tests de zero/sales.py — composición del pitch de venta en frío.

sales.compose_pitch es determinista (mock-first): fija subject/body a partir de
nombre, empresa y una muestra de leads. Estos tests aseguran personalización,
degradación limpia sin datos, y que la muestra se renderice fiel al contrato.
"""
import unittest

from zero import sales


class TestComposePitch(unittest.TestCase):
    def test_devuelve_subject_y_body(self):
        out = sales.compose_pitch()
        self.assertEqual(set(out), {"subject", "body"})
        self.assertTrue(out["subject"])
        self.assertTrue(out["body"])

    def test_sin_datos_saludo_generico(self):
        out = sales.compose_pitch()
        self.assertIn("Hola,", out["body"])

    def test_con_nombre_personaliza_saludo(self):
        out = sales.compose_pitch(name="Diego")
        self.assertIn("Hola Diego,", out["body"])

    def test_nombre_en_blanco_degrada_a_generico(self):
        out = sales.compose_pitch(name="   ")
        self.assertIn("Hola,", out["body"])

    def test_con_empresa_en_subject(self):
        out = sales.compose_pitch(company="Acme")
        self.assertIn("Acme", out["subject"])

    def test_empresa_en_blanco_subject_generico(self):
        out = sales.compose_pitch(company="  ")
        self.assertEqual(out["subject"], "Leads B2B calificados, listos para contactar")

    def test_usa_muestra_por_defecto(self):
        out = sales.compose_pitch()
        for s in sales.DEFAULT_SAMPLES:
            self.assertIn(s["company"], out["body"])

    def test_muestra_custom_reemplaza_default(self):
        muestra = [{"company": "ZetaCorp", "role": "CEO",
                    "contact": "ceo@zeta.cl", "score": 92}]
        out = sales.compose_pitch(samples=muestra)
        self.assertIn("ZetaCorp", out["body"])
        self.assertIn("score 92", out["body"])
        self.assertNotIn("AgroNorte", out["body"])

    def test_incluye_el_ask_gratuito(self):
        out = sales.compose_pitch()
        self.assertIn("10 leads", out["body"])
        self.assertIn("gratis", out["body"])

    def test_es_determinista(self):
        a = sales.compose_pitch(name="Ana", company="Beta")
        b = sales.compose_pitch(name="Ana", company="Beta")
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
