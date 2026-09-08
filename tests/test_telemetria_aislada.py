"""La suite no puede tocar el anillo de telemetría de la máquina.

Esto no es un test de una función: es el candado de `tests/__init__.py`. Si alguien lo
quita, el panel de Arquitectura vuelve a llenarse de corridas de test presentadas como
producción — que fue exactamente el bug del 2026-09-08.
"""
import json
import os
import unittest
from pathlib import Path

from zero import telemetry


class TelemetriaAisladaTest(unittest.TestCase):
    def test_la_ruta_no_apunta_al_anillo_del_repo(self):
        self.assertEqual(os.environ.get("AGENT_TELEMETRY_PATH"), os.devnull)
        self.assertNotEqual(telemetry._ruta().name, "agent_activity.json")

    def test_registrar_no_escribe_el_anillo_del_repo(self):
        """La prueba de fuego: anotar un evento y comprobar que el archivo real
        sigue byte por byte igual (o sigue sin existir)."""
        anillo = Path("agent_activity.json")
        antes = anillo.read_bytes() if anillo.exists() else None

        telemetry.registrar("CONCIERGE", status="done", ms=1.0,
                            engine="motor-de-prueba", client_id="cliente-de-prueba")

        despues = anillo.read_bytes() if anillo.exists() else None
        self.assertEqual(antes, despues,
                         "la suite escribió en agent_activity.json de la máquina")

    def test_el_evento_igual_queda_en_memoria(self):
        """Aislar no puede significar romper: lo anotado se sigue pudiendo leer."""
        telemetry.registrar("QUALIFIER", status="done", ms=2.0, engine="x")
        self.assertTrue(any(e["agent"] == "QUALIFIER" for e in telemetry.eventos(200)))


if __name__ == "__main__":
    unittest.main()
