"""Los detectores del golden set detectan de verdad.

`scripts/probar-agente.py` corre contra el modelo local, así que no puede correr en CI.
Estos tests cubren la otra mitad del problema: si un regex se rompe, el golden set
seguiría imprimiendo "6/6 casos dentro de las reglas" sin revisar nada — un guardia
dormido es peor que ninguno, porque además da confianza.

Cada regla se prueba en las dos direcciones: que marque lo que tiene que marcar, y que
NO marque una respuesta legítima. La segunda mitad importa más: un detector con falsos
positivos manda avisos que no son, y en dos semanas nadie los mira.
"""
import pathlib
import re
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


CONCIERGE = pathlib.Path(__file__).resolve().parent.parent / "prompts" / "concierge.md"

# Rioplatense: no es chileno, y el prompt lo tenía escrito en sus propias instrucciones
# (línea 18 decía «"dale"», línea 70 decía «vos NO lo redactás»). Importa más de lo que
# parece porque el motor de producción es Ollama local con qwen2.5:14b: un modelo de ese
# tamaño copia el registro de sus instrucciones, así que un prompt en voseo produce un
# agente que vosea, por más que otra línea diga "hablas español de Chile".
RIOPLATENSE = ("dale", "vos", "che", "posta", "boludo", "tenés", "querés", "podés",
               "sabés", "decime", "mirá", "andá", "hacé", "redactás", "escribís",
               "sos", "tenes")
# Chileno de más: correcto pero demasiado informal para una empresa que evalúa pagar.
DEMASIADO_JERGOSO = ("cachai", "cachái", "bacán", "fome", "pololear", "ratito",
                     "cosita", "platita")
PROHIBIDOS = RIOPLATENSE + DEMASIADO_JERGOSO

# La sección que DEFINE la regla nombra los términos prohibidos para poder prohibirlos:
# ahí no son una infracción. El barrido la salta entera, desde su encabezado hasta el
# siguiente de nivel 2. Cualquier otra línea del archivo sí cuenta.
_EXENTA_DESDE = "### El límite entre natural y jergoso"


def _lineas_auditables(texto: str):
    """(nº de línea, contenido) de todo el archivo menos el bloque que define la regla."""
    dentro_de_la_exenta = False
    for n, linea in enumerate(texto.splitlines(), start=1):
        if linea.startswith(_EXENTA_DESDE):
            dentro_de_la_exenta = True
            continue
        if dentro_de_la_exenta:
            if linea.startswith("## "):      # nivel 2 = terminó la sección exenta
                dentro_de_la_exenta = False
            else:
                continue
        yield n, linea


def lexico_prohibido(texto: str):
    """Términos prohibidos presentes, como (línea, término, contenido)."""
    hallazgos = []
    for n, linea in _lineas_auditables(texto):
        for termino in PROHIBIDOS:
            if re.search(rf"\b{re.escape(termino)}\b", linea, re.IGNORECASE):
                hallazgos.append((n, termino, linea.strip()))
    return hallazgos


class RegistroDelPromptDelVendedor(unittest.TestCase):
    """El prompt del vendedor se escribe en chileno neutro, y eso deja de depender del
    criterio de quien lo lea."""

    def test_el_prompt_no_tiene_lexico_prohibido(self):
        hallazgos = lexico_prohibido(CONCIERGE.read_text(encoding="utf-8"))
        detalle = "\n".join(f"  prompts/concierge.md:{n}: «{t}» → {linea}"
                            for n, t, linea in hallazgos)
        self.assertEqual(hallazgos, [], f"\nléxico prohibido en el prompt:\n{detalle}")

    def test_detecta_el_defecto_que_traia_el_archivo(self):
        """Las dos líneas reales que había el 2026-09-08. Si esto deja de marcarlas, el
        barrido se rompió y el test siguiente pasaría sin revisar nada."""
        viejo = ('- Suena natural — pausas, "ya", "dale", "perfecto" — sin caer en jerga.\n'
                 "  DESPUÉS de tu respuesta** — vos NO lo redactás ni mencionas cifras.\n")
        encontrados = {t for _, t, _ in lexico_prohibido(viejo)}
        self.assertEqual(encontrados, {"dale", "vos", "redactás"})

    def test_el_chileno_legitimo_no_se_marca(self):
        """La mitad que más importa: un detector con falsos positivos se ignora en dos
        semanas. "acá" y "al tiro" son chilenos normales y están en el prompt."""
        legitimo = ("Te lo mando por acá o por correo, como prefieras.\n"
                    "Lo vemos al tiro y cualquier cosa me dices.\n"
                    "Perfecto, quedamos así entonces.\n"
                    "Ya, te cuento cómo funciona en dos líneas.\n")
        self.assertEqual(lexico_prohibido(legitimo), [])

    def test_la_seccion_que_define_la_regla_esta_exenta(self):
        """El bloque de la regla nombra los términos para prohibirlos; si no estuviera
        exento, el prompt no podría documentar su propia regla."""
        texto = CONCIERGE.read_text(encoding="utf-8")
        self.assertIn(_EXENTA_DESDE, texto,
                      "desapareció la sección de la regla: el barrido quedó sin ancla")
        self.assertTrue(any('"dale"' in l for l in texto.splitlines()),
                        "la regla ya no nombra los términos que prohíbe")


if __name__ == "__main__":
    unittest.main()
