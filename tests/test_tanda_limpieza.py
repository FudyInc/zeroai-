"""La tanda no puede dejar puesto lo que su propia puerta rechaza.

Fallo medido, dos veces, con ocho días de parálisis en medio:

    2026-08-29  el agente de "rubro en discovery" corrió el pipeline en zero-core
                → crm.json quedó puesto → la tanda abortó los 6 workspaces del 30 al 04
    2026-09-05  el agente de CONCIERGE hizo lo mismo en zero-motor-whatsapp
                → la tanda del 07 abortó otra vez, por el mismo motivo

La causa no es el agente: `main.py` deja `--crm` con default relativo al directorio
actual, así que **cualquiera** que corra el pipeline o la suite dentro de un workspace
deja el archivo. Y `descartar()` no lo sacaba: `git clean -fd` no toca lo ignorado, y
además solo corría en los caminos de rechazo — la tarea del 05 fue APROBADA.

Lo que se fija acá es la invariante, no el síntoma: **después de procesar una tarea,
`revisar_aislamiento()` no encuentra nada en ese workspace.** Mientras eso se cumpla da
igual qué comando haya corrido el agente.

Run: python3 -m unittest tests.test_tanda_limpieza -v
"""
from __future__ import annotations

import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock

_ruta = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "tanda.py"
_spec = importlib.util.spec_from_file_location("tanda_limpieza", _ruta)
tanda = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tanda)


class LimpiezaDeDatosLocales(unittest.TestCase):

    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp())
        self._parche = mock.patch.object(tanda, "ruta_workspace", return_value=self.ws)
        self._parche.start()
        self.addCleanup(self._parche.stop)

    def test_borra_lo_que_la_puerta_rechaza(self):
        for nombre in tanda.DATOS_QUE_BLOQUEAN:
            (self.ws / nombre).write_text("{}", encoding="utf-8")

        borrados = tanda.limpiar_datos_locales("core")

        self.assertEqual(sorted(borrados), sorted(tanda.DATOS_QUE_BLOQUEAN))
        for nombre in tanda.DATOS_QUE_BLOQUEAN:
            self.assertFalse((self.ws / nombre).exists(), nombre)

    def test_no_borra_nada_mas(self):
        """`git clean -fdx` habría sido la solución obvia y borra `frontend/node_modules`,
        que además deja mudo el check del build en auditar.py. La lista es explícita para
        que no pueda pasar."""
        (self.ws / "frontend").mkdir()
        (self.ws / "frontend" / "node_modules").mkdir()
        (self.ws / "api.py").write_text("# código real", encoding="utf-8")
        (self.ws / "state.json").write_text("{}", encoding="utf-8")

        tanda.limpiar_datos_locales("dashboard")

        self.assertTrue((self.ws / "frontend" / "node_modules").is_dir())
        self.assertTrue((self.ws / "api.py").exists())
        self.assertTrue((self.ws / "state.json").exists(),
                        "state.json no bloquea la puerta: borrarlo sería pasarse de alcance")

    def test_sin_nada_que_borrar_no_falla_ni_inventa(self):
        self.assertEqual(tanda.limpiar_datos_locales("core"), [])

    def test_un_directorio_con_ese_nombre_no_se_toca(self):
        """`unlink()` sobre un directorio lanza. Que alguien tenga `crm.json/` es absurdo,
        pero un limpiador que revienta deja la tanda sin su `finally`."""
        (self.ws / "crm.json").mkdir()
        self.assertEqual(tanda.limpiar_datos_locales("core"), [])
        self.assertTrue((self.ws / "crm.json").is_dir())


class LaInvarianteDespuesDeProcesar(unittest.TestCase):
    """Lo que de verdad importa: la limpieza corre pase lo que pase con la tarea.

    `_procesar` tiene siete salidas distintas. Si la limpieza dependiera de acordarse en
    cada una, la que se olvide es exactamente la que produce el bloqueo — y el caso que
    ocurrió en producción fue el camino APROBADO, el único que no llamaba a `descartar()`.
    """

    def setUp(self):
        self.ws = pathlib.Path(tempfile.mkdtemp())
        mock.patch.object(tanda, "ruta_workspace", return_value=self.ws).start()
        self.addCleanup(mock.patch.stopall)
        self.tarea = {"id": "t1", "workspace": "core", "titulo": "una tarea",
                      "intentos": 1, "origen": "diego", "archivos": ["zero/crm.py"]}

    def _con_basura(self):
        (self.ws / "crm.json").write_text('{"leads": {}}', encoding="utf-8")

    def _procesar(self):
        return tanda.procesar(self.tarea, ejecutar=True, modelo="haiku",
                              modelo_juez="haiku")

    def test_se_limpia_cuando_la_tarea_se_aprueba(self):
        """El caso que ocurrió de verdad el 2026-09-05: tarea aprobada, commiteada, y el
        crm.json del agente quedó puesto porque el camino feliz no llamaba a descartar()."""
        self._con_basura()
        with mock.patch.object(tanda, "workspace_limpio", return_value=(True, "")), \
             mock.patch.object(tanda, "correr_agente", return_value=(True, "ok")), \
             mock.patch.object(tanda, "fuera_de_alcance", return_value=[]), \
             mock.patch.object(tanda, "_git", return_value="un diff"), \
             mock.patch.object(tanda, "archivos_tocados", return_value=["zero/crm.py"]), \
             mock.patch.object(tanda, "correr_tests", return_value=(True, "verde")), \
             mock.patch.object(tanda, "juzgar", return_value={"aprobado": True}), \
             mock.patch.object(tanda, "commitear", return_value="abc1234"), \
             mock.patch.object(tanda.tasks, "a_revision"), \
             mock.patch.object(tanda.tasks, "juzgar"), \
             mock.patch.object(tanda.tasks, "_actualizar"):
            r = self._procesar()

        self.assertEqual(r["resultado"], "aprobada")
        self.assertFalse((self.ws / "crm.json").exists())

    def test_se_limpia_cuando_los_tests_quedan_rojos(self):
        self._con_basura()
        with mock.patch.object(tanda, "workspace_limpio", return_value=(True, "")), \
             mock.patch.object(tanda, "correr_agente", return_value=(True, "ok")), \
             mock.patch.object(tanda, "fuera_de_alcance", return_value=[]), \
             mock.patch.object(tanda, "_git", return_value="un diff"), \
             mock.patch.object(tanda, "archivos_tocados", return_value=["zero/crm.py"]), \
             mock.patch.object(tanda, "correr_tests", return_value=(False, "rojo")), \
             mock.patch.object(tanda, "descartar"), \
             mock.patch.object(tanda.tasks, "juzgar"):
            r = self._procesar()

        self.assertEqual(r["resultado"], "tests_rojos")
        self.assertFalse((self.ws / "crm.json").exists())

    def test_se_limpia_aunque_procesar_lance(self):
        """Un fallo inesperado no puede dejar el workspace bloqueado para mañana."""
        self._con_basura()
        with mock.patch.object(tanda, "workspace_limpio",
                               side_effect=RuntimeError("git se cayó")):
            with self.assertRaises(RuntimeError):
                self._procesar()

        self.assertFalse((self.ws / "crm.json").exists())

    def test_la_puerta_y_la_limpieza_no_pueden_desincronizarse(self):
        """Las dos mitades salen de la misma tupla. Si alguien agrega un archivo a la
        puerta y olvida la limpieza, vuelve el bloqueo de agosto; este test lo ata."""
        import inspect
        fuente_puerta = inspect.getsource(tanda.revisar_aislamiento)
        fuente_limpieza = inspect.getsource(tanda.limpiar_datos_locales)
        self.assertIn("DATOS_QUE_BLOQUEAN", fuente_puerta)
        self.assertIn("DATOS_QUE_BLOQUEAN", fuente_limpieza)


if __name__ == "__main__":
    unittest.main()
