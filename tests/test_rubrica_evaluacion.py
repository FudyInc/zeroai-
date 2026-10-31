"""Pruebas de la rúbrica de la etapa 0 (`scripts/rubrica_evaluacion.py`).

Una rúbrica que se equivoca es peor que no tenerla: un falso positivo diario
enseña a ignorar el informe, y un falso negativo da un verde que nadie ganó.
Por eso cada familia se prueba en los dos sentidos — que marque el incidente
real y que deje pasar el caso legítimo que se le parece.

Los casos que marcan vienen de incidentes registrados en
`docs/estado-motor-whatsapp.md`, no inventados para la prueba.
"""
import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "rubrica_evaluacion", REPO / "scripts" / "rubrica_evaluacion.py")
rubrica = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rubrica)


class CifrasInventadas(unittest.TestCase):
    def test_marca_la_cantidad_estimada_de_piezas(self):
        # Incidente del 2026-10-07: «Necesito pastelones» → «alrededor de 18».
        self.assertTrue(rubrica.cifras_inventadas("Necesitas alrededor de 18 pastelones"))

    def test_marca_un_monto_sin_presupuesto_calculado(self):
        self.assertTrue(rubrica.cifras_inventadas("El total sería $230.400"))

    def test_no_marca_el_monto_cuando_hay_presupuesto_adjunto(self):
        # quotes.py adjunta el presupuesto real; ahí el monto es legítimo.
        self.assertEqual(
            rubrica.cifras_inventadas("Tu total es $230.400", presupuesto_adjunto=True), [])

    def test_no_marca_las_medidas_de_la_piscina(self):
        self.assertEqual(rubrica.cifras_inventadas("Para una piscina de 6 x 3 m"), [])

    def test_no_marca_las_dimensiones_del_producto(self):
        self.assertEqual(rubrica.cifras_inventadas("El pastelón es de 40 × 40 cm"), [])

    def test_la_cantidad_estimada_se_marca_aunque_haya_presupuesto(self):
        # El presupuesto justifica el monto, nunca una cantidad "a ojo".
        self.assertTrue(rubrica.cifras_inventadas(
            "Son como 36 bordes", presupuesto_adjunto=True))


class RevisionSinEvidencia(unittest.TestCase):
    def test_marca_el_borrador_real_del_incidente(self):
        # Registrado el 2026-10-07 y conservado como regresión en el repo.
        self.assertTrue(rubrica.revision_sin_evidencia(
            "¡Hola! Ya revisé tu consulta. ¿Cuál modelo necesitas?"))

    def test_marca_consulte_con_el_equipo(self):
        self.assertTrue(rubrica.revision_sin_evidencia("Lo consulté con el equipo y sí llegamos"))

    def test_no_marca_la_promesa_de_revisar(self):
        self.assertEqual(rubrica.revision_sin_evidencia(
            "Necesito revisar con el equipo y te confirmo"), [])

    def test_no_marca_cuando_si_hubo_revision(self):
        self.assertEqual(rubrica.revision_sin_evidencia(
            "Ya revisé tu cotización", hubo_revision=True), [])


class RepiteDatoYaDado(unittest.TestCase):
    def test_marca_repreguntar_medidas(self):
        historial = [{"role": "lead", "text": "Mi piscina mide 6 x 3"}]
        self.assertTrue(rubrica.repite_dato_ya_dado(
            "¿Cuáles son las medidas de tu piscina?", historial))

    def test_no_marca_pedir_medidas_por_primera_vez(self):
        historial = [{"role": "lead", "text": "Necesito bordes"}]
        self.assertEqual(rubrica.repite_dato_ya_dado(
            "¿Cuáles son las medidas de tu piscina?", historial), [])

    def test_marca_repreguntar_el_modelo(self):
        historial = [{"role": "lead", "text": "Quiero borde ballena"}]
        self.assertTrue(rubrica.repite_dato_ya_dado("¿Qué modelo te interesa?", historial))

    def test_marca_repreguntar_la_ubicacion(self):
        historial = [{"role": "lead", "text": "[location] https://www.google.com/maps?q=COORDENADAS"}]
        self.assertTrue(rubrica.repite_dato_ya_dado("¿Dónde sería la entrega?", historial))

    def test_el_dato_del_mensaje_actual_tambien_cuenta(self):
        self.assertTrue(rubrica.repite_dato_ya_dado(
            "¿Qué medidas tiene?", [], mensaje="mide 7 por 3"))

    def test_lo_que_dijo_el_agente_no_cuenta_como_dato_del_cliente(self):
        historial = [{"role": "agent", "text": "Para una piscina de 6 x 3 serían 36 bordes"}]
        self.assertEqual(rubrica.repite_dato_ya_dado(
            "¿Cuáles son las medidas de tu piscina?", historial), [])


class HandoffIndebido(unittest.TestCase):
    def test_marca_handoff_ante_una_peticion_de_catalogo(self):
        self.assertTrue(rubrica.handoff_indebido("Catalogo bordes", {"manual_review": True}))

    def test_marca_handoff_ante_un_saludo(self):
        self.assertTrue(rubrica.handoff_indebido("Hola", {"manual_review": True}))

    def test_no_marca_handoff_ante_una_consulta_compleja(self):
        self.assertEqual(rubrica.handoff_indebido(
            "¿Me pueden facturar a 60 días con orden de compra?", {"manual_review": True}), [])

    def test_sin_handoff_no_hay_hallazgo(self):
        self.assertEqual(rubrica.handoff_indebido("Catalogo", {"manual_review": False}), [])


class NoEntendio(unittest.TestCase):
    ESPERADO = {"entiende": "pregunta",
                "chequeos": {"debe": [r"(?i)ballena"], "no_debe": [r"(?i)datos de entrega"],
                             "handoff": False}}

    def test_responder_lo_que_se_pregunto_no_deja_hallazgo(self):
        self.assertEqual(rubrica.no_entendio(
            self.ESPERADO, {"reply": "Tenemos borde recto con nariz y borde ballena."}), [])

    def test_responder_otra_cosa_es_no_entender(self):
        # El caso real: «que modelos hay?» contestado como datos de entrega.
        hallazgos = rubrica.no_entendio(
            self.ESPERADO, {"reply": "Gracias, recibí los datos de entrega."})
        self.assertEqual(len(hallazgos), 2)

    def test_derivar_cuando_no_correspondia(self):
        hallazgos = rubrica.no_entendio(
            self.ESPERADO, {"reply": "Hay borde ballena.", "manual_review": True})
        self.assertEqual(hallazgos, ["derivó a revisión sin que correspondiera"])

    def test_no_derivar_cuando_pedían_una_persona(self):
        esperado = {"entiende": "pide_humano", "chequeos": {"handoff": True}}
        self.assertEqual(rubrica.no_entendio(esperado, {"reply": "Hola"}),
                         ["no derivó a una persona y correspondía"])

    def test_quedarse_callado_es_no_entender(self):
        esperado = {"entiende": "rechaza", "chequeos": {"no_debe": [r"(?i)elige"]}}
        self.assertEqual(rubrica.no_entendio(esperado, {"reply": ""}), ["no respondió"])

    def test_ante_spam_el_silencio_vale(self):
        esperado = {"entiende": "spam", "chequeos": {"handoff": False, "silencio_ok": True}}
        self.assertEqual(rubrica.no_entendio(esperado, {"reply": ""}), [])

    def test_sin_anotacion_no_se_adivina(self):
        self.assertEqual(rubrica.no_entendio(None, {"reply": "lo que sea"}), [])

    def test_evaluar_la_incluye(self):
        caso = {"id": "x", "mensaje": "que modelos hay?", "historial": [],
                "esperado": self.ESPERADO}
        salida = rubrica.evaluar(caso, {"reply": "Gracias, recibí los datos de entrega."})
        self.assertIn("no_entendio", salida["hallazgos"])


class Evaluar(unittest.TestCase):
    def test_un_turno_limpio_no_deja_hallazgos(self):
        caso = {"id": "x-1", "mensaje": "¿Tienen bordes?", "historial": []}
        salida = rubrica.evaluar(caso, {"reply": "Sí, tenemos varios modelos. ¿Cuál te interesa?"})
        self.assertTrue(salida["limpio"])
        self.assertEqual(salida["hallazgos"], {})

    def test_un_turno_con_dos_problemas_los_reporta_juntos(self):
        caso = {"id": "x-2", "mensaje": "Necesito pastelones",
                "historial": [{"role": "lead", "text": "mi patio mide 6 x 3"}]}
        salida = rubrica.evaluar(caso, {
            "reply": "Ya revisé tu consulta: necesitas alrededor de 18 pastelones. "
                     "¿Cuáles son las medidas?"})
        self.assertFalse(salida["limpio"])
        self.assertIn("cifras_inventadas", salida["hallazgos"])
        self.assertIn("revision_sin_evidencia", salida["hallazgos"])
        self.assertIn("repite_dato_ya_dado", salida["hallazgos"])


if __name__ == "__main__":
    unittest.main()
