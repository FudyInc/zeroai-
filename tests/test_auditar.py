"""Pruebas del auditor diario (`scripts/auditar.py`).

Se prueban las partes puras: las que deciden si algo es un hallazgo o no. Un auditor
que se equivoca en esa decisión es peor que no tenerlo — un falso positivo diario
enseña a ignorar la salida completa, y un falso negativo da un verde que nadie ganó.
"""
import base64
import copy
import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("auditar", REPO / "scripts" / "auditar.py")
auditar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auditar)


def _api():
    """api.py se importa dentro de cada test, no a nivel de módulo: importarlo arriba
    levanta env, secretos de nube y la app entera para toda la suite (mismo motivo que
    en tests/test_ciclo_endpoint.py)."""
    import api
    return api


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


def _normalizar(informe: dict) -> str:
    """Réplica en Python de `normalizar()` en `scripts/commitear-auditoria.sh`: la forma
    canónica del informe, sin `cuando` ni `segundos` — lo único que decide si el día
    cambió de verdad."""
    d = copy.deepcopy(informe)
    d.pop("cuando", None)
    for c in d.get("checks") or []:
        if isinstance(c, dict):
            c.pop("segundos", None)
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


class TestEstadoDeCadaCheck(unittest.TestCase):
    """`auditar()` tiene que poder distinguir «no se pudo correr» de «corrió y salió
    verde» — la lista vacía sola no alcanza, es la misma forma en los dos casos."""

    def test_check_omitido_no_es_un_hallazgo(self):
        def omitido():
            raise auditar.NoSePudoCorrer("sin frontend/node_modules")

        with mock.patch.object(auditar, "CHECKS", (("build del dashboard", omitido),)):
            informe = auditar.auditar()
        c = informe["checks"][0]
        self.assertEqual(c["estado"], "omitido")
        self.assertEqual(c["hallazgos"], 0)
        self.assertTrue(c["motivo"])
        self.assertEqual(informe["hallazgos"], [])

    def test_check_verde_no_lleva_motivo(self):
        with mock.patch.object(auditar, "CHECKS", (("suite de tests", lambda: []),)):
            informe = auditar.auditar()
        c = informe["checks"][0]
        self.assertEqual(c["estado"], "ok")
        self.assertIsNone(c["motivo"])

    def test_check_con_hallazgos_queda_marcado(self):
        def con_hallazgos():
            return [auditar._hallazgo("x", auditar.ALTA, "algo roto", "comando")]

        with mock.patch.object(auditar, "CHECKS", (("x", con_hallazgos),)):
            informe = auditar.auditar()
        c = informe["checks"][0]
        self.assertEqual(c["estado"], "hallazgos")
        self.assertEqual(c["hallazgos"], 1)
        self.assertIsNone(c["motivo"])

    def test_excepcion_cualquiera_sigue_siendo_el_hallazgo_media_de_siempre(self):
        """Solo `NoSePudoCorrer` se lee como «no sé». Cualquier otra excepción sigue
        siendo lo que era antes de este cambio: un hallazgo de gravedad media, nunca
        un omitido silencioso."""
        def revienta():
            raise ValueError("boom")

        with mock.patch.object(auditar, "CHECKS", (("y", revienta),)):
            informe = auditar.auditar()
        c = informe["checks"][0]
        self.assertNotEqual(c["estado"], "omitido")
        self.assertEqual(c["estado"], "hallazgos")
        self.assertEqual(c["hallazgos"], 1)
        self.assertIsNone(c["motivo"])
        self.assertEqual(informe["hallazgos"][0]["gravedad"], auditar.MEDIA)
        self.assertIn("boom", informe["hallazgos"][0]["detalle"])

    def test_omitido_y_verde_no_son_iguales_para_commitear_auditoria(self):
        """La garantía que pide el pedido: un día con checks omitidos NO puede
        normalizar igual que un día limpio de verdad, o `commitear-auditoria.sh`
        pensaría que no cambió nada."""
        def omitido():
            raise auditar.NoSePudoCorrer("sin frontend/node_modules")

        with mock.patch.object(auditar, "CHECKS", (("build del dashboard", omitido),)):
            informe_omitido = auditar.auditar()
        with mock.patch.object(auditar, "CHECKS", (("build del dashboard", lambda: []),)):
            informe_verde = auditar.auditar()
        self.assertNotEqual(_normalizar(informe_omitido), _normalizar(informe_verde))


class TestCompatibilidadInformesViejos(unittest.TestCase):
    """Un informe archivado antes de este cambio no tiene `estado` ni `motivo` en sus
    checks. `_informes_de_salud` (api.py) tiene que servirlo igual, con `None` en vez
    de reventar o de inventar un "omitido" que el informe nunca dijo."""

    def setUp(self):
        self.api = _api()
        self.api._informes_cache.clear()

    def tearDown(self):
        self.api._informes_cache.clear()

    def test_check_sin_estado_da_none_no_crashea(self):
        informe_viejo = json.dumps({
            "cuando": 1788637000.0,
            "checks": [{"check": "suite de tests", "hallazgos": 0, "segundos": 20.0}],
            "hallazgos": [],
        })

        def falso(*args):
            if args[0] == "ls-tree":
                return "100644 blob sha-viejo\tdocs/auditoria/2026-09-05.json\n", ""
            return informe_viejo, ""

        with mock.patch.object(self.api, "_git_lectura", side_effect=falso):
            informes, motivo = self.api._informes_de_salud(14)
        self.assertEqual(motivo, "")
        self.assertEqual(informes[0]["checks"][0]["estado"], None)
        self.assertEqual(informes[0]["checks"][0]["motivo"], None)


if __name__ == "__main__":
    unittest.main()
