"""Tests de zero/store.py — el switch entre backend local (JSON) y Supabase.

store decide, según env, si el CRM/memoria van a Postgres o a archivo local.
Estos tests fijan el camino local (sin Supabase) y el detector _supabase_on.
Se usan paths temporales: nunca tocan crm.json / state.json reales.
"""
import contextlib
import io
import os
import pathlib
import tempfile
import unittest
import urllib.error
from unittest import mock

from zero import store
from zero.config import CRM_BREAKER_DOWN_S, CRM_BREAKER_OK_S
from zero.crm import CRM
from zero.crm_supabase import SupabaseCRM
from zero.memory import SessionMemory


def _no_supabase_env():
    """Entorno sin las claves de Supabase."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("SUPABASE_URL", "SUPABASE_KEY")}
    return mock.patch.dict(os.environ, env, clear=True)


class TestSupabaseOn(unittest.TestCase):
    def test_off_sin_claves(self):
        with _no_supabase_env():
            self.assertFalse(store._supabase_on())

    def test_off_con_solo_una_clave(self):
        with mock.patch.dict(os.environ, {"SUPABASE_URL": "x"}, clear=False):
            os.environ.pop("SUPABASE_KEY", None)
            self.assertFalse(store._supabase_on())

    def test_on_con_ambas_claves(self):
        with mock.patch.dict(os.environ,
                             {"SUPABASE_URL": "http://x", "SUPABASE_KEY": "k"},
                             clear=False):
            self.assertTrue(store._supabase_on())

    def test_off_con_claves_vacias(self):
        with mock.patch.dict(os.environ,
                             {"SUPABASE_URL": "", "SUPABASE_KEY": ""},
                             clear=False):
            self.assertFalse(store._supabase_on())


class TestMakeCrm(unittest.TestCase):
    def test_local_devuelve_crm(self):
        with _no_supabase_env(), tempfile.TemporaryDirectory() as d:
            crm = store.make_crm(os.path.join(d, "crm.json"))
            self.assertIsInstance(crm, CRM)


def _http_402(*args, **kwargs):
    """Frontera HTTP: Supabase sin cuota de egress."""
    raise urllib.error.HTTPError(
        "http://x/rest/v1/crm_leads", 402, "Payment Required", {},
        io.BytesIO(b'{"message":"exceed_egress_quota"}'))


_SB_ENV = {"SUPABASE_URL": "http://x", "SUPABASE_KEY": "k"}


class TestMakeCrmSupabaseCaido(unittest.TestCase):
    def setUp(self):
        store._breaker.update(up=True, until=0.0)
        self.addCleanup(store._breaker.update, up=True, until=0.0)

    def _crm_en_respaldo(self, d, sonda=_http_402):
        path = os.path.join(d, "crm.json")
        with mock.patch.dict(os.environ, _SB_ENV, clear=False), \
             mock.patch("urllib.request.urlopen", side_effect=sonda), \
             contextlib.redirect_stderr(io.StringIO()):
            return path, store.make_crm(path)

    def test_402_degrada_a_crm_local_con_aviso(self):
        with mock.patch.dict(os.environ, _SB_ENV, clear=False), \
             mock.patch("urllib.request.urlopen", side_effect=_http_402), \
             tempfile.TemporaryDirectory() as d, \
             contextlib.redirect_stderr(io.StringIO()) as err:
            crm = store.make_crm(os.path.join(d, "crm.json"))
            self.assertIsInstance(crm, store.CRMRespaldoSoloLectura)
            self.assertNotIsInstance(crm, SupabaseCRM)
            self.assertIn("CRM en la nube no disponible", err.getvalue())

    def test_excepciones_no_supabase_tambien_degradan(self):
        for exc in (TimeoutError("t"), ConnectionResetError("r"), ValueError("json")):
            store._breaker.update(up=True, until=0.0)
            with tempfile.TemporaryDirectory() as d:
                _, crm = self._crm_en_respaldo(d, sonda=exc)
                self.assertIsInstance(crm, store.CRMRespaldoSoloLectura, exc)

    def test_supabase_sano_sigue_usando_la_nube(self):
        with mock.patch.dict(os.environ, _SB_ENV, clear=False), \
             mock.patch("zero.store.sb_request", return_value=[]), \
             tempfile.TemporaryDirectory() as d:
            self.assertIsInstance(store.make_crm(os.path.join(d, "crm.json")), SupabaseCRM)

    def test_breaker_caido_no_resondea_y_resondea_al_vencer(self):
        with mock.patch.dict(os.environ, _SB_ENV, clear=False), \
             mock.patch("urllib.request.urlopen", side_effect=_http_402) as uo, \
             mock.patch("zero.store.time.monotonic") as clock, \
             tempfile.TemporaryDirectory() as d, \
             contextlib.redirect_stderr(io.StringIO()):
            path = os.path.join(d, "crm.json")
            clock.return_value = 1000.0
            store.make_crm(path)
            clock.return_value = 1000.0 + CRM_BREAKER_DOWN_S - 1
            store.make_crm(path)
            self.assertEqual(uo.call_count, 1)
            clock.return_value = 1000.0 + CRM_BREAKER_DOWN_S + 1
            store.make_crm(path)
            self.assertEqual(uo.call_count, 2)

    def test_breaker_sano_no_resondea_dentro_de_la_ventana(self):
        with mock.patch.dict(os.environ, _SB_ENV, clear=False), \
             mock.patch("zero.store.sb_request", return_value=[]) as sb, \
             mock.patch("zero.store.time.monotonic") as clock, \
             tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "crm.json")
            clock.return_value = 1000.0
            store.make_crm(path)
            clock.return_value = 1000.0 + CRM_BREAKER_OK_S - 1
            store.make_crm(path)
            self.assertEqual(sb.call_count, 1)
            clock.return_value = 1000.0 + CRM_BREAKER_OK_S + 1
            store.make_crm(path)
            self.assertEqual(sb.call_count, 2)

    def test_escritura_en_respaldo_da_503_y_no_toca_crm_json(self):
        import api
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "crm.json")
            semilla = CRM(path)
            semilla.upsert("acme", {"company": "Vieja SA", "email": "a@b.cl"})
            semilla.save()
            antes = (pathlib.Path(path).read_text(), os.stat(path).st_mtime_ns, os.path.exists(path + ".bak"))
            _, crm = self._crm_en_respaldo(d)
            self.assertEqual(len(crm.list("acme")), 1)   # lectura sí
            for escribir in (lambda: crm.upsert("acme", {"company": "N"}), crm.save,
                             lambda: crm.clear("acme"), lambda: crm.log("acme", "k", "e")):
                with self.assertRaises(api.SupabaseError) as cm:
                    escribir()
                self.assertEqual(cm.exception.code, 503)
            despues = (pathlib.Path(path).read_text(), os.stat(path).st_mtime_ns, os.path.exists(path + ".bak"))
            self.assertEqual(antes, despues)

    def test_health_refleja_el_modo(self):
        import api
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "crm.json")
            with mock.patch.dict(os.environ, _SB_ENV, clear=False), \
                 mock.patch.object(api, "CRM_PATH", path):
                with open(path, "w") as f:
                    f.write("{}")
                with mock.patch("urllib.request.urlopen", side_effect=_http_402), \
                     contextlib.redirect_stderr(io.StringIO()):
                    h = api.health()
                self.assertEqual(h["crm"], "respaldo_local_solo_lectura")
                self.assertTrue(h["crm_json_modificado"])
                store._breaker.update(up=True, until=0.0)
                with mock.patch("zero.store.sb_request", return_value=[]):
                    self.assertEqual(api.health()["crm"], "nube")
            store._breaker.update(up=True, until=0.0)
            with _no_supabase_env(), mock.patch.object(api, "CRM_PATH", path):
                self.assertEqual(api.health()["crm"], "local")

    def test_respaldo_no_pisa_un_crm_json_corrupto(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "crm.json")
            with open(path, "w") as f:
                f.write("{corrupto")
            with self.assertRaises(RuntimeError):
                self._crm_en_respaldo(d)
            with open(path) as f:
                self.assertEqual(f.read(), "{corrupto")

    def test_endpoint_no_da_503_al_leer_con_supabase_caido(self):
        import api
        with mock.patch.dict(os.environ, _SB_ENV, clear=False), \
             mock.patch("urllib.request.urlopen", side_effect=_http_402), \
             tempfile.TemporaryDirectory() as d, \
             contextlib.redirect_stderr(io.StringIO()):
            with mock.patch.object(api, "CRM_PATH", os.path.join(d, "crm.json")), \
                 mock.patch.object(api, "make_memory",
                                   return_value=SessionMemory(os.path.join(d, "state.json"))):
                self.assertEqual(api._all_client_ids(), [])


class TestMakeMemory(unittest.TestCase):
    def test_local_devuelve_session_memory(self):
        with _no_supabase_env(), tempfile.TemporaryDirectory() as d:
            mem = store.make_memory(os.path.join(d, "state.json"))
            self.assertIsInstance(mem, SessionMemory)

    def test_supabase_falla_degrada_a_local(self):
        # Con Supabase "encendido" pero el import/instancia falla → cae a local sin romper.
        with mock.patch.dict(os.environ,
                             {"SUPABASE_URL": "http://x", "SUPABASE_KEY": "k"},
                             clear=False), \
             mock.patch("zero.memory_supabase.SupabaseMemory",
                        side_effect=RuntimeError("tabla ausente")), \
             tempfile.TemporaryDirectory() as d, \
             contextlib.redirect_stderr(io.StringIO()):
            mem = store.make_memory(os.path.join(d, "state.json"))
            self.assertIsInstance(mem, SessionMemory)


if __name__ == "__main__":
    unittest.main()
