"""Preguntas sin respuesta: captura, agrupación y paso a la ficha.

La regla que estas pruebas protegen es una sola: **el agente aprende de
respuestas aprobadas por una persona, nunca de las suyas**. El historial real
tiene registradas respuestas equivocadas —una cantidad de piezas inventada,
una revisión afirmada que nunca ocurrió—; guardarlas como aprendizaje las
convertiría en doctrina y el agente repetiría sus errores con más confianza.
"""
import importlib.util
import unittest
from pathlib import Path

from zero.memory import SessionMemory, _gap_key

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "preguntas_pendientes", REPO / "scripts" / "preguntas_pendientes.py")
pendientes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pendientes)


class AgrupacionDePreguntas(unittest.TestCase):
    def test_las_variantes_de_la_misma_duda_comparten_clave(self):
        claves = {_gap_key(q) for q in
                  ("¿Realizan despachos?", "realizan despacho", "REALIZAN DESPACHOS")}
        self.assertEqual(len(claves), 1)

    def test_preguntas_distintas_no_se_mezclan(self):
        self.assertNotEqual(_gap_key("¿Realizan despachos?"), _gap_key("¿Cuánto sale el borde?"))

    def test_un_adjunto_no_es_pregunta(self):
        for adjunto in ("[image]", "[location]", "[audio]", "   "):
            self.assertEqual(_gap_key(adjunto), "", adjunto)


class RegistroDeHuecos(unittest.TestCase):
    def setUp(self):
        self.memoria = SessionMemory(None)

    def test_se_guarda_la_pregunta(self):
        self.memoria.add_knowledge_gap("acme", "¿Realizan despachos?", "no entendió")
        huecos = self.memoria.list_knowledge_gaps("acme")
        self.assertEqual(len(huecos), 1)
        self.assertEqual(huecos[0]["pregunta"], "¿Realizan despachos?")
        self.assertEqual(huecos[0]["veces"], 1)

    def test_repetir_la_pregunta_suma_en_vez_de_duplicar(self):
        for q in ("¿Realizan despachos?", "realizan despacho", "REALIZAN DESPACHOS"):
            self.memoria.add_knowledge_gap("acme", q, "no entendió")
        huecos = self.memoria.list_knowledge_gaps("acme")
        self.assertEqual(len(huecos), 1)
        self.assertEqual(huecos[0]["veces"], 3)

    def test_lo_mas_preguntado_aparece_primero(self):
        self.memoria.add_knowledge_gap("acme", "¿Tienen factura?", "x")
        for _ in range(3):
            self.memoria.add_knowledge_gap("acme", "¿Realizan despachos?", "x")
        self.assertEqual(self.memoria.list_knowledge_gaps("acme")[0]["veces"], 3)

    def test_un_adjunto_no_entra_a_la_lista(self):
        self.assertIsNone(self.memoria.add_knowledge_gap("acme", "[image]", "x"))
        self.assertEqual(self.memoria.list_knowledge_gaps("acme"), [])

    def test_resolver_la_saca_de_las_pendientes(self):
        self.memoria.add_knowledge_gap("acme", "¿Realizan despachos?", "x")
        clave = self.memoria.list_knowledge_gaps("acme")[0]["clave"]
        self.assertTrue(self.memoria.resolve_knowledge_gap("acme", clave, "Sí, a todo Santiago."))
        self.assertEqual(self.memoria.list_knowledge_gaps("acme"), [])
        todas = self.memoria.list_knowledge_gaps("acme", incluir_resueltas=True)
        self.assertEqual(todas[0]["respuesta"], "Sí, a todo Santiago.")

    def test_resolver_una_clave_inexistente_avisa(self):
        self.assertFalse(self.memoria.resolve_knowledge_gap("acme", "no-existe", "x"))

    def test_los_huecos_sobreviven_a_una_recarga(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "state.json")
            uno = SessionMemory(ruta)
            uno.add_knowledge_gap("acme", "¿Realizan despachos?", "x")
            uno.save()
            self.assertEqual(len(SessionMemory(ruta).list_knowledge_gaps("acme")), 1)


class PasoALaFicha(unittest.TestCase):
    def test_agrega_la_seccion_cuando_no_existe(self):
        nueva = pendientes.agregar_respuesta("Ficha base.", "¿Realizan despachos?",
                                             "Sí, a todo Santiago.")
        self.assertIn("## Respuestas aprobadas", nueva)
        self.assertIn("Sí, a todo Santiago.", nueva)
        self.assertIn("Ficha base.", nueva)

    def test_una_segunda_respuesta_se_suma(self):
        una = pendientes.agregar_respuesta("Base.", "¿Despachos?", "Sí.")
        dos = pendientes.agregar_respuesta(una, "¿Factura?", "Sí, con RUT.")
        self.assertEqual(dos.count("## Respuestas aprobadas"), 1)
        self.assertIn("Sí.", dos)
        self.assertIn("Sí, con RUT.", dos)

    def test_responder_dos_veces_lo_mismo_reemplaza_y_no_contradice(self):
        # Dos respuestas distintas a la misma pregunta le dan al modelo una
        # contradicción, que es peor que no tener ninguna.
        una = pendientes.agregar_respuesta("Base.", "¿Despachos?", "Solo Santiago.")
        dos = pendientes.agregar_respuesta(una, "¿Despachos?", "A todo Chile.")
        self.assertNotIn("Solo Santiago.", dos)
        self.assertIn("A todo Chile.", dos)
        self.assertEqual(dos.count("¿Despachos?"), 1)

    def test_la_seccion_se_puede_leer_de_vuelta(self):
        nueva = pendientes.agregar_respuesta("Base.", "¿Despachos?", "Sí.")
        self.assertIn("¿Despachos?", pendientes.seccion_respuestas(nueva))

    def test_sin_seccion_no_hay_respuestas(self):
        self.assertEqual(pendientes.seccion_respuestas("Ficha sin nada."), "")


if __name__ == "__main__":
    unittest.main()
