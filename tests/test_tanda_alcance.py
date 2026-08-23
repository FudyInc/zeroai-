"""La puerta de alcance lee bien los nombres de archivo.

Encontrado en la primera corrida real del sistema autónomo (2026-08-22): la puerta
rechazó un `README.md` legítimo porque lo leyó como `EADME.md`. El helper de git hacía
`.strip()` sobre toda la salida, lo que se come el espacio inicial de la primera línea
del formato porcelain (` M README.md`) y desalinea el corte de columnas.

Con ese defecto, **la primera tarea de cualquier tanda se rechazaba sola** — y el motivo
guardado ("tocó archivos fuera del alcance") habría mandado a buscar el problema al lado
equivocado: al agente, que había hecho bien su trabajo.
"""
import importlib.util
import pathlib
import unittest

_ruta = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "tanda.py"
_spec = importlib.util.spec_from_file_location("tanda", _ruta)
tanda = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tanda)


class ParseoDeGitStatus(unittest.TestCase):

    def test_modificado_sin_stage(self):
        """El caso que falló: espacio inicial + M."""
        self.assertEqual(tanda.parsear_status(" M README.md"), ["README.md"])

    def test_varias_lineas_mezcladas(self):
        salida = " M README.md\n?? scripts/nuevo.py\nA  zero/x.py\n M  frontend/src/App.jsx\n"
        self.assertEqual(tanda.parsear_status(salida),
                         ["README.md", "scripts/nuevo.py", "zero/x.py", "frontend/src/App.jsx"])

    def test_renombrado_cuenta_el_destino(self):
        self.assertEqual(tanda.parsear_status("R  viejo.py -> nuevo.py"), ["nuevo.py"])

    def test_nombre_con_espacios(self):
        self.assertEqual(tanda.parsear_status(' M "docs/mi archivo.md"'), ["docs/mi archivo.md"])

    def test_salida_vacia(self):
        self.assertEqual(tanda.parsear_status(""), [])
        self.assertEqual(tanda.parsear_status("\n\n"), [])


class PuertaDeAlcance(unittest.TestCase):

    def test_un_archivo_permitido_no_es_violacion(self):
        tarea = {"workspace": "core", "archivos": ["README.md"]}
        original = tanda.archivos_tocados
        tanda.archivos_tocados = lambda d: ["README.md"]
        try:
            self.assertEqual(tanda.fuera_de_alcance(tarea), [])
        finally:
            tanda.archivos_tocados = original

    def test_un_archivo_no_declarado_si_lo_es(self):
        tarea = {"workspace": "core", "archivos": ["README.md"]}
        original = tanda.archivos_tocados
        tanda.archivos_tocados = lambda d: ["README.md", "api.py"]
        try:
            self.assertEqual(tanda.fuera_de_alcance(tarea), ["api.py"])
        finally:
            tanda.archivos_tocados = original


if __name__ == "__main__":
    unittest.main()
