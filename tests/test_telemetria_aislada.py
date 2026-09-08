"""La suite no puede tocar el anillo de telemetría de la máquina.

Esto no es un test de una función: es el candado de `tests/__init__.py`, que no tenía
ninguno. Si alguien quita ese aislamiento, el panel de Arquitectura vuelve a llenarse de
corridas de test presentadas como producción, y `revisar-salud.py` vuelve a gritar por
trabajo que nadie hizo — que fue exactamente el bug del 2026-09-08.

Se comprueba el EFECTO (el archivo no cambia), no la forma de la escotilla: si mañana el
aislamiento se hace con otro mecanismo, este test tiene que seguir valiendo.
"""
import json
import os
import unittest
from pathlib import Path

from zero import telemetry


class TelemetriaAisladaTest(unittest.TestCase):
    def test_la_ruta_no_apunta_al_anillo_del_repo(self):
        self.assertNotEqual(telemetry._ruta().name, "agent_activity.json",
                            "la telemetría de la suite apunta al anillo de producción")

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
