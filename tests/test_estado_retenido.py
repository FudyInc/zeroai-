"""Interruptor "estado local retenido" (zero/estado_retenido.py + store + SupabaseMemory).

Nube simulada con `FakeSupabase` de test_memoria_cache: sin red, sin tocar state.json real.
El marcador vive en un temporal (ZERO_ESTADO_RETENIDO_PATH).

Correr solo:  python3 -m unittest tests.test_estado_retenido -v
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import api
from zero import estado_retenido, store
from zero._supabase import SupabaseError
from zero.memory import SessionMemory
from zero.memory_supabase import CloudStateUnavailable, SupabaseMemory

from tests.test_memoria_cache import FakeSupabase, _nube


class Base(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.dir = d.name
        self.marca = os.path.join(d.name, ".runtime", "estado-local-retenido.json")
        self.state = os.path.join(d.name, "state.json")
        p = mock.patch.dict(os.environ, {"ZERO_ESTADO_RETENIDO_PATH": self.marca})
        p.start()
        self.addCleanup(p.stop)
        estado_retenido._ultimo_aviso["at"] = None
        pn = mock.patch("zero.alerts.notify_owner")      # nunca mandar un aviso real desde la suite
        self.notificar = pn.start()
        self.addCleanup(pn.stop)
        self.nube = FakeSupabase({"clients": {"acme": {"tier": "GROWTH"}}})
        self.err = io.StringIO()

    def make(self):
        with contextlib.redirect_stderr(self.err):
            return store.make_memory(self.state)


class TestInterruptor(Base):
    def test_falla_de_la_nube_crea_marcador_y_cae_a_local(self):
        self.nube.down = True
        with _nube(self.nube):
            mem = self.make()
        self.assertNotIsInstance(mem, SupabaseMemory)
        self.assertTrue(os.path.exists(self.marca))
        with open(self.marca) as fh:
            datos = json.load(fh)
        self.assertTrue(datos["desde"])
        self.assertIn("402", datos["motivo"])

    def test_desde_original_no_se_sobrescribe(self):
        self.nube.down = True
        with _nube(self.nube):
            self.make()
            with open(self.marca) as fh:
                primero = json.load(fh)
            self.make()
        with open(self.marca) as fh:
            self.assertEqual(json.load(fh), primero)

    def test_crea_el_directorio_runtime_si_no_existe(self):
        self.assertFalse(os.path.isdir(os.path.dirname(self.marca)))
        estado_retenido.marcar("x")
        self.assertTrue(os.path.exists(self.marca))

    def test_nube_sana_con_marcador_sigue_local(self):
        estado_retenido.marcar("caida previa")
        with _nube(self.nube):
            mem = self.make()
            self.assertIsInstance(mem, SessionMemory)
            self.assertNotIsInstance(mem, SupabaseMemory)
            self.assertEqual(self.nube.reads + self.nube.writes, 0)   # ni la petición de versión
        self.assertIn("estado retenido en local desde", self.err.getvalue())
        self.assertIn("reconciliar_estado.py", self.err.getvalue())

    def test_con_cache_llena_y_vencida_el_marcador_corta_hasta_la_peticion_de_version(self):
        from zero import memory_supabase
        with _nube(self.nube):
            self.make()                                   # llena la caché
            memory_supabase._cache["at"] = 0.0            # vencida: pediría select=updated
            antes = self.nube.reads
            estado_retenido.marcar("x")
            mem = self.make()
            self.assertNotIsInstance(mem, SupabaseMemory)
            self.assertEqual(self.nube.reads, antes)

    def test_sin_marcador_y_nube_sana_usa_nube(self):
        with _nube(self.nube):
            mem = self.make()
        self.assertIsInstance(mem, SupabaseMemory)
        self.assertFalse(os.path.exists(self.marca))

    def test_aviso_una_vez_por_ventana(self):
        estado_retenido.marcar("x")
        with _nube(self.nube):
            self.make()
            self.make()
        self.assertEqual(self.err.getvalue().count("estado retenido en local desde"), 1)

    def test_constructor_directo_respeta_el_marcador(self):
        estado_retenido.marcar("x")
        with _nube(self.nube), contextlib.redirect_stderr(self.err):
            for kwargs in ({}, {"fresh": True}):
                with self.assertRaises(CloudStateUnavailable):
                    SupabaseMemory(**kwargs)
        self.assertEqual(self.nube.reads, 0)

    def test_constructor_directo_que_falla_deja_marcador(self):
        self.nube.down = True
        with _nube(self.nube), self.assertRaises(SupabaseError):
            SupabaseMemory(fresh=True)
        self.assertTrue(os.path.exists(self.marca))

    def _guard(self):
        from zero import whatsapp_web
        mem = SessionMemory(self.state)
        mem.set_client_agent_profile("acme", {"response_mode": "auto"})
        mem.save()
        estado_retenido.marcar("x")
        context = {"message": {"chat_id": "56911112222@c.us"}}
        body = {"chat_id": "56911112222@c.us", "to": "56911112222@c.us"}
        with _nube(self.nube), \
             mock.patch.dict(os.environ, {"STATE_PATH": self.state}), \
             contextlib.redirect_stderr(self.err):
            return whatsapp_web._guard_event_send(context, body, "acme")

    def test_guard_de_whatsapp_bloquea_con_marcador_por_defecto(self):
        from zero import config
        self.assertFalse(config.GUARD_USA_LOCAL_RETENIDO)
        with self.assertRaises(CloudStateUnavailable):     # fail-closed, como con la nube caída
            self._guard()
        self.assertEqual(self.nube.reads + self.nube.writes, 0)

    def test_guard_de_whatsapp_lee_local_si_la_politica_lo_permite(self):
        with mock.patch("zero.config.GUARD_USA_LOCAL_RETENIDO", True):
            try:
                self._guard()
            except RuntimeError as e:    # puede frenar por reglas posteriores; no por la nube
                self.assertNotIsInstance(e, SupabaseError)
                self.assertNotIn("verificar", str(e))
        self.assertEqual(self.nube.reads + self.nube.writes, 0)

    def test_crear_el_marcador_avisa_al_dueno_una_sola_vez(self):
        estado_retenido.marcar("402 egress")
        estado_retenido.marcar("otra vez")
        self.assertEqual(self.notificar.call_count, 1)
        texto = self.notificar.call_args.args[0]
        self.assertIn("402 egress", texto)
        self.assertIn("reconciliar_estado.py", texto)
        self.assertEqual(self.notificar.call_args.kwargs["kind"], "estado_retenido")

    def test_un_aviso_que_falla_no_levanta(self):
        self.notificar.side_effect = RuntimeError("sin red")
        with contextlib.redirect_stderr(self.err):
            self.assertTrue(estado_retenido.marcar("x"))
        self.assertTrue(os.path.exists(self.marca))

    def test_ruta_vacia_avisa_a_stderr_y_guion_es_silencioso(self):
        estado_retenido._avisado_desactivado["ya"] = False
        with mock.patch.dict(os.environ, {"ZERO_ESTADO_RETENIDO_PATH": ""}), \
             contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(estado_retenido.ruta())
        self.assertIn("DESACTIVADO", err.getvalue())
        with mock.patch.dict(os.environ, {"ZERO_ESTADO_RETENIDO_PATH": "-"}), \
             contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(estado_retenido.ruta())
        self.assertEqual(err.getvalue(), "")

    def test_interruptor_desactivado_con_ruta_vacia(self):
        with mock.patch.dict(os.environ, {"ZERO_ESTADO_RETENIDO_PATH": "-"}):
            self.assertFalse(estado_retenido.marcar("x"))
            self.assertFalse(estado_retenido.activo())


class TestRevisarSalud(Base):
    def _modulo(self):
        import importlib.util
        from pathlib import Path
        ruta = Path(__file__).resolve().parent.parent / "scripts" / "revisar-salud.py"
        spec = importlib.util.spec_from_file_location("revisar_salud_estado", ruta)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_marcador_aparece_como_falla_urgente_y_estable(self):
        mod = self._modulo()
        self.assertEqual(mod._estado_retenido(), [])
        estado_retenido.marcar("x", desde="2026-11-25T21:55:00-03:00")
        fallas = mod._estado_retenido()
        self.assertEqual(fallas, ["estado retenido en local desde 2026-11-25T21:55:00-03:00; "
                                  "correr scripts/reconciliar_estado.py"])
        self.assertFalse(fallas[0].startswith(mod.NO_URGENTE))
        self.assertEqual(mod._estado_retenido(), fallas)     # mismo texto: el antirrebote lo agrupa


class TestHealth(Base):
    def test_estados(self):
        sin_nube = {k: v for k, v in os.environ.items() if not k.startswith("SUPABASE_")}
        with mock.patch.dict(os.environ, sin_nube, clear=True):
            self.assertEqual(store.estado_status()["estado"], "local")
        with _nube(self.nube):
            self.assertEqual(store.estado_status(), {"estado": "nube", "retenido_desde": None})
            estado_retenido.marcar("x")
            h = store.estado_status()
            self.assertEqual(h["estado"], "local_retenido")
            with open(self.marca) as fh:
                self.assertEqual(h["retenido_desde"], json.load(fh)["desde"])

    def test_api_health_incluye_estado(self):
        with _nube(self.nube), mock.patch.object(api, "crm_status", return_value={"crm": "nube"}):
            estado_retenido.marcar("x")
            h = api.health()
        self.assertEqual(h["estado"], "local_retenido")
        self.assertTrue(h["retenido_desde"])


if __name__ == "__main__":
    unittest.main()
