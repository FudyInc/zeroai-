"""Tests de zero/store.py — el switch entre backend local (JSON) y Supabase.

store decide, según env, si el CRM/memoria van a Postgres o a archivo local.
Estos tests fijan el camino local (sin Supabase) y el detector _supabase_on.
Se usan paths temporales: nunca tocan crm.json / state.json reales.
"""
import contextlib
import io
import os
import tempfile
import unittest
import urllib.error
from unittest import mock

from zero import store
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
    def test_402_degrada_a_crm_local_con_aviso(self):
        with mock.patch.dict(os.environ, _SB_ENV, clear=False), \
             mock.patch("urllib.request.urlopen", side_effect=_http_402), \
             tempfile.TemporaryDirectory() as d, \
             contextlib.redirect_stderr(io.StringIO()) as err:
            crm = store.make_crm(os.path.join(d, "crm.json"))
            self.assertIsInstance(crm, CRM)
            self.assertNotIsInstance(crm, SupabaseCRM)
            self.assertIn("CRM en la nube no disponible", err.getvalue())

    def test_supabase_sano_sigue_usando_la_nube(self):
        with mock.patch.dict(os.environ, _SB_ENV, clear=False), \
             mock.patch("zero.crm_supabase.sb_request", return_value=[]), \
             tempfile.TemporaryDirectory() as d:
            self.assertIsInstance(store.make_crm(os.path.join(d, "crm.json")), SupabaseCRM)

    def test_fallback_no_pisa_un_crm_json_corrupto(self):
        with mock.patch.dict(os.environ, _SB_ENV, clear=False), \
             mock.patch("urllib.request.urlopen", side_effect=_http_402), \
             tempfile.TemporaryDirectory() as d, \
             contextlib.redirect_stderr(io.StringIO()):
            path = os.path.join(d, "crm.json")
            with open(path, "w") as f:
                f.write("{corrupto")
            with self.assertRaises(RuntimeError):
                store.make_crm(path)
            with open(path) as f:
                self.assertEqual(f.read(), "{corrupto")

    def test_endpoint_no_da_503_con_supabase_caido(self):
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
