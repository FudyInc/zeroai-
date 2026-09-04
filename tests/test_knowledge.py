"""Historial de la ficha de la empresa y banco de casos de prueba.

Hasta hoy (2026-09-04) `set_client_knowledge` sobrescribía sin dejar rastro: se
editaba la ficha para arreglar una respuesta, se rompían otras tres, y no había a
dónde volver ni con qué comparar. Estas dos piezas son la red bajo esa tarea —
versiones para poder retroceder, y un set de preguntas repetible para notar lo que
se rompió.

Lo que estos tests NO hacen, a propósito: comparar `respuesta_esperada` contra la
salida del modelo. No hay juez que puntúe respuestas (decisión de Diego); el campo
es una referencia para que una persona compare, y un test que lo tratara como
assert convertiría en obligación lo que se descartó como diseño.

Run: python3 -m unittest tests.test_knowledge -v
"""
from __future__ import annotations

import unittest
from unittest import mock

from zero.config import MAX_KNOWLEDGE_VERSIONS, MAX_TEST_CASES_PER_CLIENT
from zero.memory import SessionMemory, normalize_cases


class HistorialDeLaFichaTest(unittest.TestCase):
    """Guardar la ficha agrega una versión; nunca pisa la anterior."""

    def setUp(self):
        self.mem = SessionMemory()          # sin path: no toca state.json real

    def test_guardar_deja_la_version_vigente(self):
        entrada = self.mem.set_client_knowledge("acme", "Vendemos piscinas")
        self.assertEqual(entrada["version"], 1)
        self.assertEqual(self.mem.get_client_knowledge("acme"), "Vendemos piscinas")
        self.assertEqual(self.mem.get_client_knowledge_version("acme"), 1)

    def test_cada_guardado_es_una_version_nueva(self):
        self.mem.set_client_knowledge("acme", "v1")
        self.mem.set_client_knowledge("acme", "v2")
        versiones = self.mem.list_client_knowledge_versions("acme")
        self.assertEqual([v["version"] for v in versiones], [2, 1])   # la más nueva primero
        self.assertEqual(self.mem.get_client_knowledge("acme"), "v2")

    def test_el_texto_anterior_sigue_recuperable(self):
        """El punto entero: la v1 no se pierde al guardar la v2."""
        self.mem.set_client_knowledge("acme", "horario: 9 a 18")
        self.mem.set_client_knowledge("acme", "horario: 10 a 19")
        vieja = self.mem.get_client_knowledge_version_entry("acme", 1)
        self.assertEqual(vieja["knowledge"], "horario: 9 a 18")

    def test_el_motivo_queda_registrado(self):
        """Sin el porqué, dentro de una semana el historial es una lista de fechas."""
        self.mem.set_client_knowledge("acme", "v1", motivo="agrego política de despacho")
        self.assertEqual(self.mem.list_client_knowledge_versions("acme")[0]["motivo"],
                         "agrego política de despacho")

    def test_una_ficha_anterior_al_historial_no_se_pierde(self):
        """La ficha que ya está en producción no tiene historial todavía. La
        primera edición debe archivarla, no borrarla — es la ficha que más importa."""
        self.mem.clients["acme"] = {"knowledge": "ficha vieja cargada a mano"}
        self.mem.set_client_knowledge("acme", "ficha nueva")
        versiones = self.mem.list_client_knowledge_versions("acme")
        self.assertEqual([v["version"] for v in versiones], [2, 1])
        self.assertEqual(versiones[1]["knowledge"], "ficha vieja cargada a mano")

    def test_un_cliente_sin_ficha_esta_en_version_cero(self):
        self.assertEqual(self.mem.get_client_knowledge_version("nadie"), 0)
        self.assertEqual(self.mem.list_client_knowledge_versions("nadie"), [])

    def test_el_historial_sobrevive_al_snapshot(self):
        """Todo vive dentro de la ficha del cliente: el snapshot no cambia de
        forma, así que restaurar uno viejo sigue funcionando."""
        self.mem.set_client_knowledge("acme", "v1")
        self.mem.set_client_knowledge("acme", "v2")
        otra = SessionMemory()
        otra._restore(self.mem.snapshot())
        self.assertEqual(otra.get_client_knowledge_version("acme"), 2)
        self.assertEqual(len(otra.list_client_knowledge_versions("acme")), 2)


class RollbackTest(unittest.TestCase):

    def setUp(self):
        self.mem = SessionMemory()
        self.mem.set_client_knowledge("acme", "v1: precios viejos")
        self.mem.set_client_knowledge("acme", "v2: precios nuevos, rompió el saludo")

    def test_rollback_restaura_el_texto(self):
        self.mem.rollback_client_knowledge("acme", 1)
        self.assertEqual(self.mem.get_client_knowledge("acme"), "v1: precios viejos")

    def test_el_rollback_queda_como_version_nueva(self):
        """Volver atrás no borra el intento que se deja: saber qué se probó y no
        funcionó es lo que evita volver a probarlo la semana que viene."""
        entrada = self.mem.rollback_client_knowledge("acme", 1)
        self.assertEqual(entrada["version"], 3)
        self.assertEqual(self.mem.get_client_knowledge_version("acme"), 3)
        versiones = self.mem.list_client_knowledge_versions("acme")
        self.assertEqual([v["version"] for v in versiones], [3, 2, 1])
        # la v2 (el intento fallido) sigue entera en el historial
        self.assertEqual(self.mem.get_client_knowledge_version_entry("acme", 2)["knowledge"],
                         "v2: precios nuevos, rompió el saludo")

    def test_el_rollback_dice_de_dónde_viene(self):
        entrada = self.mem.rollback_client_knowledge("acme", 1)
        self.assertIn("rollback a la versión 1", entrada["motivo"])

    def test_una_version_inexistente_devuelve_none(self):
        """Sin lanzar: el endpoint traduce esto a un 404 con mensaje claro."""
        self.assertIsNone(self.mem.rollback_client_knowledge("acme", 99))
        self.assertEqual(self.mem.get_client_knowledge_version("acme"), 2)   # nada cambió


class TechoDeVersionesTest(unittest.TestCase):
    """El techo es política (config.py), y descarta las más viejas — nunca la vigente."""

    def setUp(self):
        self.mem = SessionMemory()

    def test_pasado_el_techo_se_descartan_las_mas_viejas(self):
        for i in range(1, MAX_KNOWLEDGE_VERSIONS + 6):
            self.mem.set_client_knowledge("acme", f"v{i}")
        versiones = self.mem.list_client_knowledge_versions("acme")
        self.assertEqual(len(versiones), MAX_KNOWLEDGE_VERSIONS)
        ultima = MAX_KNOWLEDGE_VERSIONS + 5
        self.assertEqual(versiones[0]["version"], ultima)               # la vigente está
        self.assertEqual(versiones[-1]["version"], ultima - MAX_KNOWLEDGE_VERSIONS + 1)
        self.assertIsNone(self.mem.get_client_knowledge_version_entry("acme", 1))

    def test_la_vigente_nunca_se_descarta(self):
        """Un techo mal configurado no puede dejar al cliente sin ficha: el agente
        responde con lo que diga la vigente, y sin ella responde sin contexto."""
        with mock.patch("zero.memory.MAX_KNOWLEDGE_VERSIONS", 0):
            for i in range(4):
                self.mem.set_client_knowledge("acme", f"v{i}")
        versiones = self.mem.list_client_knowledge_versions("acme")
        self.assertEqual(len(versiones), 1)
        self.assertEqual(versiones[0]["version"], 4)
        self.assertEqual(self.mem.get_client_knowledge("acme"), "v3")

    def test_el_numero_de_version_no_se_reusa(self):
        """Descartar las viejas no reinicia la numeración: dos versiones distintas
        con el mismo número harían inútil cualquier referencia a "la 3"."""
        for i in range(MAX_KNOWLEDGE_VERSIONS + 3):
            self.mem.set_client_knowledge("acme", f"v{i}")
        numeros = [v["version"] for v in self.mem.list_client_knowledge_versions("acme")]
        self.assertEqual(len(set(numeros)), len(numeros))
        self.assertEqual(max(numeros), MAX_KNOWLEDGE_VERSIONS + 3)


class BancoDeCasosTest(unittest.TestCase):

    def setUp(self):
        self.mem = SessionMemory()

    def test_guardar_y_leer_el_banco(self):
        casos = self.mem.set_client_cases("acme", [
            {"pregunta": "¿hacen despacho a regiones?",
             "respuesta_esperada": "Sí, con costo según comuna",
             "nota": "se rompió al cambiar la v3"},
        ])
        self.assertEqual(len(casos), 1)
        self.assertEqual(self.mem.get_client_cases("acme")[0]["pregunta"],
                         "¿hacen despacho a regiones?")

    def test_un_caso_sin_pregunta_se_descarta(self):
        """Un caso sin pregunta no se puede repetir, que es para lo único que sirve."""
        casos = self.mem.set_client_cases("acme", [
            {"pregunta": "  ", "respuesta_esperada": "algo"},
            {"nota": "solo una nota"},
            {"pregunta": "¿cuánto sale?"},
        ])
        self.assertEqual([c["pregunta"] for c in casos], ["¿cuánto sale?"])

    def test_los_campos_opcionales_quedan_vacios_no_nulos(self):
        """El dashboard no debería tener que distinguir None de ""."""
        caso = self.mem.set_client_cases("acme", [{"pregunta": "¿horario?"}])[0]
        self.assertEqual(caso["respuesta_esperada"], "")
        self.assertEqual(caso["nota"], "")
        self.assertTrue(caso["id"])
        self.assertTrue(caso["creado"])

    def test_el_id_de_un_caso_existente_se_respeta(self):
        """Editar el banco no puede cambiarle el id a los casos que ya estaban:
        el dashboard los referencia por ahí."""
        primero = self.mem.set_client_cases("acme", [{"pregunta": "¿horario?"}])[0]
        vuelta = self.mem.set_client_cases("acme", [
            dict(primero, nota="lo probé hoy"),
            {"pregunta": "¿despacho?"},
        ])
        self.assertEqual(vuelta[0]["id"], primero["id"])
        self.assertEqual(vuelta[0]["nota"], "lo probé hoy")

    def test_el_banco_tiene_techo(self):
        casos = self.mem.set_client_cases(
            "acme", [{"pregunta": f"p{i}"} for i in range(MAX_TEST_CASES_PER_CLIENT + 10)])
        self.assertEqual(len(casos), MAX_TEST_CASES_PER_CLIENT)
        self.assertEqual(casos[0]["pregunta"], "p0")     # se van los últimos, no los de siempre

    def test_normalize_cases_aguanta_basura(self):
        """Es la frontera con el JSON que manda el dashboard: nada de lo que llegue
        puede hacerla lanzar."""
        self.assertEqual(normalize_cases(None), [])
        self.assertEqual(normalize_cases("no soy una lista"), [])
        self.assertEqual(normalize_cases([None, 5, "x", {"pregunta": "ok"}])[0]["pregunta"], "ok")

    def test_el_banco_sobrevive_al_snapshot(self):
        self.mem.set_client_cases("acme", [{"pregunta": "¿horario?"}])
        otra = SessionMemory()
        otra._restore(self.mem.snapshot())
        self.assertEqual(len(otra.get_client_cases("acme")), 1)

    def test_el_banco_es_por_cliente(self):
        self.mem.set_client_cases("acme", [{"pregunta": "¿horario?"}])
        self.assertEqual(self.mem.get_client_cases("otra-empresa"), [])


if __name__ == "__main__":
    unittest.main()
