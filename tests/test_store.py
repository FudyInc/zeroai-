"""Tests de zero/store.py — el switch entre backend local (JSON) y Supabase.

store decide, según env, si el CRM/memoria van a Postgres o a archivo local.
Estos tests fijan el camino local (sin Supabase) y el detector _supabase_on.
Se usan paths temporales: nunca tocan crm.json / state.json reales.
"""
import os
import tempfile
import unittest
from unittest import mock

from zero import store
from zero.crm import CRM
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
             tempfile.TemporaryDirectory() as d:
            mem = store.make_memory(os.path.join(d, "state.json"))
            self.assertIsInstance(mem, SessionMemory)


if __name__ == "__main__":
    unittest.main()
