"""Los detectores del golden set detectan de verdad.

`scripts/probar-agente.py` corre contra el modelo local, así que no puede correr en CI.
Estos tests cubren la otra mitad del problema: si un regex se rompe, el golden set
seguiría imprimiendo "6/6 casos dentro de las reglas" sin revisar nada — un guardia
dormido es peor que ninguno, porque además da confianza.

Cada regla se prueba en las dos direcciones: que marque lo que tiene que marcar, y que
NO marque una respuesta legítima. La segunda mitad importa más: un detector con falsos
positivos manda avisos que no son, y en dos semanas nadie los mira.
"""
import unittest

from zero.agent_rules import MAX_REPLY_CHARS, check_reply, segmento_vigilado

OK = {"reply": "¡Hola Juan! Somos ZeroAI y ayudamos a conseguir clientes. ¿Te cuento cómo?",
      "intent": "info"}


class RespuestaLegitima(unittest.TestCase):
    def test_una_respuesta_normal_no_rompe_nada(self):
        self.assertEqual(check_reply(OK), [])

    def test_numeros_legitimos_no_son_cifras(self):
        """"24/7" y "10 leads" están en la ficha y son correctos. Si esto falla, el
        detector de montos manda un aviso en cada corrida."""
        for texto in ("Respondemos 24/7 sin que tengas que estar pendiente.",
                      "Te mando 10 leads calificados de prueba, gratis.",
                      "Trabajamos con pymes de 3 a 200 empleados."):
            with self.subTest(texto=texto):
                self.assertEqual(check_reply({"reply": texto, "intent": "info"}), [])

    def test_reconocer_la_ia_sin_negarla_es_valido(self):
        r = {"reply": "Soy Fernanda, trabajo con ayuda de IA para responder rápido, "
                      "pero esto que hablamos es real 🙂", "intent": "disclose"}
        self.assertEqual(check_reply(r), [])


class ReglasRotas(unittest.TestCase):
    def test_respuesta_vacia(self):
        fallas = check_reply({"reply": "   ", "intent": "info"})
        self.assertEqual(len(fallas), 1)
        self.assertIn("vacía", fallas[0])

    def test_intent_fuera_del_contrato(self):
        fallas = check_reply({"reply": "hola", "intent": "saludo_amable"})
        self.assertTrue(any("fuera del contrato" in f for f in fallas))

    def test_intent_distinto_del_esperado(self):
        fallas = check_reply({"reply": "hola", "intent": "general"},
                             expected_intents={"pricing"})
        self.assertTrue(any("se esperaba" in f for f in fallas))

    def test_cifras_en_la_respuesta(self):
        """Los montos los calcula quotes.py y se adjuntan aparte; uno escrito por el
        modelo puede no coincidir con el presupuesto real que se manda abajo."""
        for texto in ("Sale $89.000 al mes.", "Son 150.000 pesos.",
                      "Cuesta 50 USD.", "Desde 2 millones."):
            with self.subTest(texto=texto):
                fallas = check_reply({"reply": texto, "intent": "pricing"})
                self.assertTrue(any("cifra" in f for f in fallas), f"no detectó: {texto}")

    def test_negar_ser_ia(self):
        for texto in ("No soy una IA, soy Fernanda.", "no soy un bot",
                      "Soy una persona, tranquilo."):
            with self.subTest(texto=texto):
                fallas = check_reply({"reply": texto, "intent": "disclose"})
                self.assertTrue(any("negó ser una IA" in f for f in fallas))

    def test_etiqueta_interna_frente_al_lead(self):
        fallas = check_reply({"reply": "Soy CONCIERGE, el asistente virtual de ZeroAI.",
                              "intent": "general"})
        self.assertTrue(any("etiqueta interna" in f for f in fallas))

    def test_atribuirle_el_segmento_al_lead(self):
        """El bug del 2026-08-21, que hubo que arreglar dos veces."""
        fallas = check_reply({"reply": "Ayudamos a empresas de mudanzas como la tuya.",
                              "intent": "info"}, segmento=["mudanzas", "retail"])
        self.assertTrue(any("segmento de prospección" in f for f in fallas))

    def test_respuesta_kilometrica(self):
        fallas = check_reply({"reply": "hola " * MAX_REPLY_CHARS, "intent": "general"})
        self.assertTrue(any("caracteres" in f for f in fallas))


class SegmentoVigilado(unittest.TestCase):
    def test_saca_las_palabras_de_rubro(self):
        icp = {"industry": "cualquier rubro: restaurantes, retail y e-commerce, mudanzas"}
        s = segmento_vigilado(icp)
        self.assertIn("restaurantes", s)
        self.assertIn("mudanzas", s)

    def test_ignora_las_palabras_vacias(self):
        """"cualquier" y "rubro" aparecen en el ICP de zeroai y calzarían con casi
        cualquier frase — vigilar esas sería un falso positivo garantizado."""
        s = segmento_vigilado({"industry": "cualquier rubro: empresas y servicios"})
        for vacia in ("cualquier", "rubro", "empresas", "servicios"):
            self.assertNotIn(vacia, s)

    def test_sin_icp_no_vigila_nada(self):
        self.assertEqual(segmento_vigilado(None), [])
        self.assertEqual(segmento_vigilado({}), [])


if __name__ == "__main__":
    unittest.main()
