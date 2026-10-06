"""El mock de CONCIERGE habla como la persona que declara `prompts/concierge.md`.

El mock existe para demostrar la conversación sin red, y su docstring promete que
el modelo real hace *lo mismo* con comprensión genuina. Si el mock quedó hablando
distinto del prompt, lo que se demuestra offline no es lo que el lead va a recibir:
falsa confianza, justo lo que prohíbe el principio 1 del repo.

Estos tests son el barrido que hace que "dejar de ser fiel al prompt" rompa algo.
Vigilan tres compromisos verificables sin modelo:

1. **Persona** — `data.vendor` cambia el texto. Fernanda ("cercana, cálida, directa")
   y Stéfano ("formal, técnico, al grano") no pueden devolver lo mismo.
2. **Registro** — español de Chile, sin rioplatenses; 1–3 frases, ≤1 emoji, una
   sola pregunta al final.
3. **Nada inventado** — ni una cifra, ni un horario, ni una dirección.

Correr: python3 -m unittest tests.test_concierge_persona -v
"""
from __future__ import annotations

import pathlib
import re
import unittest

from zero.agent_rules import INTENTS, check_reply
from zero.agents import build_agents
from zero.agents.concierge import _VENDOR_POR_DEFECTO
from zero.contracts import Constraints, TaskPayload

FERNANDA = {"name": "Fernanda", "tone": "cercana, cálida, directa"}
STEFANO = {"name": "Stéfano", "tone": "formal, técnico, al grano"}

# Un mensaje por cada caso que el mock sabe responder. Si mañana se agrega un caso
# sin sus dos registros, agregarlo acá lo somete al barrido completo.
MENSAJES = {
    "disclose": "¿eres un bot o una persona?",
    "optout": "no me interesa, gracias",
    "trust": "¿de dónde sacaste mi número?",
    "objection_precio": "nos parece muy caro",
    "objection_proveedor": "ya tenemos proveedor para esto",
    "info": "mándame más info",
    "pricing": "¿cuánto cuesta el servicio?",
    "explain": "¿cómo funciona esto?",
    "meeting": "¿podemos agendar una llamada?",
    "accept": "ya, listo",
    "general": "hola",
}

# Léxico rioplatense: el prompt pide español de Chile y una demo offline con voseo
# no es la conversación que el cliente va a recibir.
_RIOPLATENSE = re.compile(
    r"\b(vos|sos|ten[ée]s|quer[ée]s|pod[ée]s|sab[ée]s|redact[áa]s|decime|contame|"
    r"escribime|acordate|fijate|mir[áa]|and[áa]|dale|che|boludo|posta|laburo|pibe)\b",
    re.IGNORECASE,
)

# Bloques de emoji suficientes para lo que un agente de ventas usaría.
_EMOJI = re.compile(r"[\U0001F300-\U0001FAFF☀-➿⬀-⯿️]")

# Cifras y datos de la empresa que el mock no puede afirmar: los montos los calcula
# zero/quotes.py y se adjuntan aparte, y horario/dirección solo salen de `knowledge`.
_DIGITO = re.compile(r"\d")
_DATO_INVENTADO = re.compile(
    r"\b(horario|abrimos|cerramos|atendemos de|nuestra dirección|queda en|"
    r"lunes a viernes|24/7)\b",
    re.IGNORECASE,
)


def _responder(msg: str, vendor: dict | None = None, lead: dict | None = None) -> dict:
    c = build_agents(mock=True)["CONCIERGE"]
    data = {"message": msg,
            "lead": lead if lead is not None else {"name": "Carla", "company": "Acme"},
            "icp": {"sells": "pallets"}}
    if vendor is not None:
        data["vendor"] = vendor
    task = TaskPayload(agent="CONCIERGE", client_id="acme", client_tier="GROWTH",
                       instructions="x", data=data,
                       constraints=Constraints(channels=["whatsapp"]))
    return c.run(task).result


class DosPersonasDistintasTest(unittest.TestCase):
    """B: ante el MISMO mensaje, Fernanda y Stéfano no devuelven el mismo texto."""

    def test_cada_caso_suena_distinto_segun_el_vendedor(self):
        for caso, msg in MENSAJES.items():
            with self.subTest(caso=caso):
                f = _responder(msg, FERNANDA)
                s = _responder(msg, STEFANO)
                self.assertEqual(f["intent"], s["intent"],
                                 "el registro cambia el texto, nunca la intención detectada")
                self.assertNotEqual(f["reply"], s["reply"],
                                    f"'{msg}' suena idéntico para Fernanda y para Stéfano")

    def test_cada_uno_se_presenta_con_su_nombre(self):
        # El prompt es explícito: "Nunca te presentes con un nombre distinto al que
        # te dieron" — y el modelo real ya copió "Fernanda" del ejemplo en vivo.
        self.assertIn("Stéfano", _responder(MENSAJES["general"], STEFANO)["reply"])
        self.assertNotIn("Fernanda", _responder(MENSAJES["general"], STEFANO)["reply"])
        self.assertIn("Fernanda", _responder(MENSAJES["general"], FERNANDA)["reply"])

    def test_sin_vendor_la_persona_por_defecto_es_fernanda(self):
        # prompts/concierge.md: "Si no llega `data.vendor`, eres Fernanda".
        self.assertEqual(_VENDOR_POR_DEFECTO, "Fernanda")
        self.assertIn("Fernanda", _responder(MENSAJES["general"])["reply"])

    def test_un_tono_desconocido_cae_en_el_registro_cercano(self):
        raro = {"name": "Ariel", "tone": "entusiasta"}
        self.assertEqual(_responder(MENSAJES["pricing"], raro)["reply"],
                         _responder(MENSAJES["pricing"], FERNANDA)["reply"]
                         .replace("Fernanda", "Ariel"))


class RegistroTest(unittest.TestCase):
    """A: léxico y largo del prompt — frases cortas, chileno, sin rioplatenses."""

    def _todas(self):
        for caso, msg in MENSAJES.items():
            for vendor in (FERNANDA, STEFANO, None):
                yield caso, vendor, _responder(msg, vendor)["reply"]

    def test_ninguna_respuesta_usa_lexico_rioplatense(self):
        for caso, vendor, reply in self._todas():
            with self.subTest(caso=caso, vendor=(vendor or {}).get("name")):
                hallado = _RIOPLATENSE.search(reply)
                self.assertIsNone(hallado, f"rioplatense {hallado and hallado.group(0)!r}: {reply}")

    def test_el_archivo_completo_pasa_el_barrido(self):
        """El barrido de aceptación corre sobre el archivo, no sobre una muestra:

            grep -nE '\\b(dale|vos|redactás|tenés|querés|podés)\\b' zero/agents/concierge.py

        Cubre también los patrones que leen al lead, no solo lo que el mock dice.
        """
        fuente = pathlib.Path("zero/agents/concierge.py").read_text(encoding="utf-8")
        for n, linea in enumerate(fuente.splitlines(), 1):
            hallado = _RIOPLATENSE.search(linea)
            self.assertIsNone(hallado, f"zero/agents/concierge.py:{n}: {linea.strip()}")

    def test_ninguna_respuesta_pasa_de_tres_frases(self):
        # "Frases cortas (1–3), una idea a la vez" — el prompt, sección Estilo.
        for caso, vendor, reply in self._todas():
            with self.subTest(caso=caso, vendor=(vendor or {}).get("name")):
                frases = len(re.findall(r"[.!?…]+", reply))
                self.assertGreaterEqual(frases, 1, reply)
                self.assertLessEqual(frases, 3, f"{frases} frases: {reply}")

    def test_maximo_un_emoji(self):
        for caso, vendor, reply in self._todas():
            with self.subTest(caso=caso, vendor=(vendor or {}).get("name")):
                self.assertLessEqual(len(_EMOJI.findall(reply)), 1, reply)

    def test_una_sola_pregunta_al_final(self):
        # "Una sola pregunta o llamado a la acción al final" — regla 3 del prompt.
        for caso, vendor, reply in self._todas():
            with self.subTest(caso=caso, vendor=(vendor or {}).get("name")):
                self.assertLessEqual(reply.count("?"), 1, reply)


class NoInventaDatosTest(unittest.TestCase):
    """C: el mock nunca afirma precios, horarios ni dirección."""

    def test_ninguna_respuesta_escribe_una_cifra(self):
        # Más estricto que agent_rules._CIFRA a propósito: el mock es texto fijo, así
        # que puede prometer cero dígitos. Un número escrito acá no puede venir del
        # contexto del cliente — sería inventado por definición.
        for caso, msg in MENSAJES.items():
            for vendor in (FERNANDA, STEFANO):
                with self.subTest(caso=caso, vendor=vendor["name"]):
                    reply = _responder(msg, vendor)["reply"]
                    self.assertIsNone(_DIGITO.search(reply), reply)

    def test_ninguna_respuesta_afirma_horario_ni_direccion(self):
        for caso, msg in MENSAJES.items():
            for vendor in (FERNANDA, STEFANO):
                with self.subTest(caso=caso, vendor=vendor["name"]):
                    reply = _responder(msg, vendor)["reply"]
                    hallado = _DATO_INVENTADO.search(reply)
                    self.assertIsNone(hallado, f"{hallado and hallado.group(0)!r}: {reply}")

    def test_el_precio_no_menciona_un_tier_de_entrada(self):
        # Regresión: el mock decía "hay opciones desde un tier de entrada" — un dato
        # de precio que no viene ni de `icp` ni de `knowledge`.
        for vendor in (FERNANDA, STEFANO):
            reply = _responder(MENSAJES["pricing"], vendor)["reply"].lower()
            self.assertNotIn("tier", reply)
            self.assertNotIn("desde", reply)


class ReglasDurasTest(unittest.TestCase):
    """Las respuestas del mock pasan el mismo checador que el golden set del modelo
    real (`zero/agent_rules.py`): si el mock no lo pasa, no es fiel al contrato."""

    def test_ninguna_respuesta_rompe_las_reglas_duras(self):
        for caso, msg in MENSAJES.items():
            for vendor in (FERNANDA, STEFANO):
                with self.subTest(caso=caso, vendor=vendor["name"]):
                    r = _responder(msg, vendor)
                    fallas = [f for f in check_reply(r)
                              # 'accept' no está en el catálogo del prompt: es un hueco
                              # de contrato conocido, cubierto por el test de abajo.
                              if "fuera del contrato" not in f]
                    self.assertEqual(fallas, [], f"{msg} → {r['reply']}")

    def test_disclose_se_presenta_como_la_persona_no_como_asistente(self):
        # Regla 2 del prompt: "Eres tu persona (vendor.name), no 'un asistente con IA'",
        # y negarlo está prohibido. El mock decía "soy el asistente con IA del equipo".
        for vendor in (FERNANDA, STEFANO):
            reply = _responder(MENSAJES["disclose"], vendor)["reply"]
            self.assertTrue(reply.startswith(f"Soy {vendor['name']}"), reply)
            self.assertNotIn("asistente", reply.lower())
            self.assertIn("ia", reply.lower())     # no lo niega

    def test_el_intent_accept_no_esta_en_el_contrato(self):
        """Desalineación conocida, reportada a coordinación y NO arreglada acá.

        `prompts/concierge.md` cierra con 9 intents y 'accept' no es uno de ellos;
        `zero/agent_rules.INTENTS` tampoco lo tiene. El mock lo emite igual desde
        antes de este trabajo. Cambiar el vocabulario de intents es tocar el
        contrato (prompt + agent_rules), que es de coordinación.

        Cuando coordinación lo resuelva, este test falla: ahí hay que borrarlo y
        sacar el filtro de `test_ninguna_respuesta_rompe_las_reglas_duras`.
        """
        self.assertEqual(_responder(MENSAJES["accept"], FERNANDA)["intent"], "accept")
        self.assertNotIn("accept", INTENTS)


if __name__ == "__main__":
    unittest.main()
