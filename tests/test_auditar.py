"""Pruebas del auditor diario (`scripts/auditar.py`).

Se prueban las partes puras: las que deciden si algo es un hallazgo o no. Un auditor
que se equivoca en esa decisión es peor que no tenerlo — un falso positivo diario
enseña a ignorar la salida completa, y un falso negativo da un verde que nadie ganó.
"""
import base64
import importlib.util
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("auditar", REPO / "scripts" / "auditar.py")
auditar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auditar)


def _jwt(payload: dict) -> str:
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{b64({'alg': 'HS256'})}.{b64(payload)}.{'s' * 43}"


class TestJwtPublico(unittest.TestCase):
    """La anon key de Supabase y la service_role tienen la MISMA forma."""

    def test_anon_es_publica(self):
        self.assertTrue(auditar._jwt_es_publico(_jwt({"role": "anon", "ref": "abc"})))

    def test_service_role_no_es_publica(self):
        # La que se salta RLS. Si esto devuelve True, el auditor calla la fuga peor.
        self.assertFalse(auditar._jwt_es_publico(_jwt({"role": "service_role"})))

    def test_jwt_ilegible_no_se_declara_inofensivo(self):
        for basura in ("eyJ.no-es-json.xxx", "", "eyJhbGciOiJIUzI1NiJ9", "a.b.c"):
            self.assertFalse(auditar._jwt_es_publico(basura), basura)

    def test_sin_claim_role_no_es_publico(self):
        self.assertFalse(auditar._jwt_es_publico(_jwt({"ref": "abc"})))


class TestRutasDuplicadas(unittest.TestCase):
    def test_api_real_no_tiene_duplicados(self):
        # Ya pasó de verdad: dos `/api/vendors` por ramas de larga vida. FastAPI no
        # avisa —registra ambas y gana la primera—, así que esto es la única alarma.
        self.assertEqual(auditar.rutas_duplicadas(), [])

    def test_detecta_un_duplicado_plantado(self):
        texto = ('@app.get("/api/leads")\ndef a(): ...\n'
                 '@app.post("/api/leads")\ndef b(): ...\n'
                 '@app.get("/api/leads")\ndef c(): ...\n')
        encontrados = [(m.group(1), m.group(2)) for m in auditar._RUTA_RE.finditer(texto)]
        self.assertEqual(len(encontrados), 3)
        # get/leads dos veces, post/leads una: solo la primera es duplicado.
        self.assertEqual(encontrados.count(("get", "/api/leads")), 2)


class TestFicha(unittest.TestCase):
    def test_la_ficha_cabe_en_el_limite(self):
        # `reply_to_inbound` la corta en 4000 sin avisar: lo que sobra no llega nunca.
        self.assertEqual(auditar.ficha_se_trunca(), [])


class TestHallazgos(unittest.TestCase):
    def test_todo_hallazgo_trae_como_reproducirlo(self):
        """La regla que separa este auditor de uno que opina."""
        for _, fn in auditar.CHECKS:
            for h in ([] if fn.__name__ in ("suite_de_tests", "pipeline_en_mock",
                                            "build_del_dashboard") else fn()):
                self.assertTrue(h.get("evidencia"), f"{h['check']} sin evidencia")
                self.assertIn(h["gravedad"], (auditar.ALTA, auditar.MEDIA))


if __name__ == "__main__":
    unittest.main()
