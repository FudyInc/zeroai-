"""Conversation state for the local WhatsApp agent, and the prompt budget it must respect."""
import json
import unittest
from unittest import mock

from zero import config
from zero.agents import build_agents
from zero.contracts import AgentResponse
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.whatsapp_state import build_conversation_state

LEAD, AGENT = "lead", "agent"


def turns(*pairs):
    return [{"role": role, "text": text} for role, text in pairs]


class ConversationStateTest(unittest.TestCase):
    def test_pool_border_flow_knows_what_is_missing(self):
        history = turns((LEAD, "Necesito bordes para mi piscina"),
                        (AGENT, "¿Cuáles son las medidas de tu piscina?"),
                        (LEAD, "Mide 6 x 3"))
        state = build_conversation_state("losetaschile", "Borde recto con nariz", history)
        self.assertEqual(state["pidio"], "borde de piscina")
        self.assertEqual(state["conocido"]["modelo"], "recto con nariz")
        self.assertEqual(state["conocido"]["medidas"], "6x3 m")
        self.assertEqual(state["falta"], "color")

    def test_pool_border_without_measurements_asks_for_them(self):
        state = build_conversation_state(
            "losetaschile", "Necesito bordes para mi piscina", [])
        self.assertEqual(state["pidio"], "borde de piscina")
        self.assertEqual(state["falta"], "medidas")

    def test_whale_border_needs_shape_before_color(self):
        history = turns((LEAD, "Necesito bordes para mi piscina"),
                        (AGENT, "¿Cuáles son las medidas de tu piscina?"),
                        (LEAD, "6 x 3"))
        state = build_conversation_state("losetaschile", "borde ballena", history)
        self.assertEqual(state["falta"], "forma")

    def test_delivery_closes_the_border_flow(self):
        history = turns((LEAD, "Necesito bordes para mi piscina de 6 x 3"),
                        (LEAD, "Borde recto con nariz"),
                        (AGENT, "¿Qué color prefieres?"), (LEAD, "Beige"),
                        (AGENT, "Escríbeme calle, número y comuna de entrega."))
        state = build_conversation_state("losetaschile", "Mi dirección es Calle 12, Maipú",
                                         history)
        self.assertEqual(state["conocido"]["color"], "beige")
        self.assertIn("Maipú", state["conocido"]["entrega"])
        self.assertIsNone(state["falta"])

    def test_pavers_flow(self):
        history = turns((LEAD, "Quiero pastelones"),
                        (AGENT, "¿Cuántos m² necesitas cubrir con pastelones? "
                                "¿Qué modelo?"))
        state = build_conversation_state("losetaschile", "20 m2 modelo sol", history)
        self.assertEqual(state["pidio"], "pastelones")
        self.assertEqual(state["conocido"], {"modelo": "Sol", "m2": "20 m2"})
        self.assertEqual(state["falta"], "color")

    def test_customer_correction_wins(self):
        history = turns((LEAD, "Necesito bordes para mi piscina de 6 x 3"),
                        (LEAD, "Borde recto con nariz"),
                        (AGENT, "¿Qué color prefieres?"), (LEAD, "Beige"),
                        (AGENT, "Anoté beige."))
        state = build_conversation_state("losetaschile", "mejor gris", history)
        self.assertEqual(state["conocido"]["color"], "gris")
        history = turns((LEAD, "Necesito bordes para mi piscina de 6 x 3"),
                        (LEAD, "Borde recto con nariz"))
        state = build_conversation_state("losetaschile", "Perdón, mi piscina mide 8 x 4",
                                         history)
        self.assertEqual(state["conocido"]["medidas"], "8x4 m")

    def test_other_clients_get_conservative_evidence_only(self):
        state = build_conversation_state(
            "acme", "Mi piscina mide 7 por 3, estoy en Maipú", [])
        self.assertIsNone(state["falta"])
        self.assertIn("7 por 3", state["conocido"]["medidas"])
        self.assertIn("Maipú", state["conocido"]["ubicacion"])

    def test_nothing_known_returns_none(self):
        self.assertIsNone(build_conversation_state("losetaschile", "Hola", []))
        self.assertIsNone(build_conversation_state("acme", "Hola, buenas tardes", []))

    def test_failing_extractor_does_not_break_the_rest(self):
        history = turns((LEAD, "Necesito bordes para mi piscina de 6 x 3"),
                        (LEAD, "Borde recto con nariz"),
                        (AGENT, "¿Qué color prefieres?"), (LEAD, "Beige"))
        with mock.patch("zero.whatsapp_state.delivery_detail", side_effect=RuntimeError("x")), \
                self.assertLogs(level="WARNING"):
            state = build_conversation_state("losetaschile", "Gracias", history)
        self.assertEqual(state["conocido"]["color"], "beige")
        self.assertEqual(state["falta"], "entrega")

    def test_total_failure_returns_none(self):
        with mock.patch("zero.whatsapp_state._losetas_state", side_effect=RuntimeError("x")), \
                self.assertLogs(level="WARNING"):
            self.assertIsNone(build_conversation_state("losetaschile", "Hola", []))


class StateReachesTheModelTest(unittest.TestCase):
    HISTORY = turns((LEAD, "Necesito bordes para mi piscina de 6 x 3"),
                    (AGENT, "¿Qué modelo de borde te interesó más?"))

    def converse(self, prompt_file):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        agent = mock.Mock(prompt_file=prompt_file)
        zero = Zero({"CONCIERGE": agent}, memory=memory)
        answer = AgentResponse("test", "CONCIERGE", "done", {"reply": "Ya.", "intent": "info"})
        with mock.patch.object(zero, "dispatch", return_value=answer) as dispatch:
            zero.converse_result("losetaschile", "¿Cómo se limpian?", history=self.HISTORY,
                                 channel="whatsapp")
        return dispatch.call_args.args[1].data

    def test_local_engine_receives_state(self):
        data = self.converse("concierge-whatsapp-local.md")
        self.assertEqual(data["conversation_state"]["pidio"], "borde de piscina")

    def test_other_engines_do_not(self):
        self.assertNotIn("conversation_state", self.converse("concierge.md"))


LONG_CONVERSATION = turns(
    (LEAD, "Hola, buenas tardes"), (AGENT, "¡Buenas tardes! ¿En qué te puedo ayudar?"),
    (LEAD, "Necesito bordes para mi piscina"),
    (AGENT, "Claro. ¿Cuáles son las medidas de tu piscina? Necesito largo y ancho en "
            "metros (por ejemplo, 6 × 3 m)."),
    (LEAD, "Mi piscina mide 8 por 4 metros, es rectangular"),
    (AGENT, "Gracias. ¿Qué modelo de borde te interesó más?"),
    (LEAD, "Borde recto con nariz"),
    (AGENT, "Te comparto la gama de colores disponible para bordes y pastelones: "
            "anaranjado, blanco, rojo, crema, beige, gris y amarillo. ¿Qué color prefieres?"),
    (LEAD, "Beige"), (AGENT, "Anoté el color beige. ¿Cómo prefieres recibir tu pedido?"),
    (LEAD, "Despacho a domicilio"), (AGENT, "Escríbeme calle, número y comuna de entrega."),
    (LEAD, "Mi comuna es Maipú, Av. Pajaritos 1234"),
    (AGENT, "Gracias, recibí los datos de entrega. El equipo revisará cobertura y flete."),
    (LEAD, "Ya, ¿y los bordes resisten el sol y el cloro? Mi piscina tiene mucho sol"),
    (AGENT, "Sí, son de hormigón y resisten bien el sol y el cloro."),
    (LEAD, "Perfecto, ¿y son antideslizantes? Tengo niños pequeños en la casa"),
    (AGENT, "La superficie tiene textura antideslizante, pensada para zonas húmedas."),
    (LEAD, "Bacán. También quería ver pastelones para la terraza, unos 20 m2"),
    (AGENT, "¿Qué pastelón del catálogo te interesó más?"), (LEAD, "El modelo Sol"),
    (AGENT, "Anoté el modelo Sol. ¿Cuántos m² necesitas cubrir con pastelones?"),
    (LEAD, "20 m2"),
    (AGENT, "Anoté 20 m². Debo confirmar el tamaño del modelo antes de calcular."),
    (LEAD, "Ya, ¿cuánto demoran en entregar normalmente después de confirmar?"),
    (AGENT, "El plazo lo confirma el equipo al revisar tu pedido y la ruta."),
    (LEAD, "Entiendo, déjame consultarlo con mi esposo"),
    (AGENT, "Claro, aquí quedo atento."),
    (LEAD, "Hola de nuevo, mi esposo dice que sí, ¿pueden despachar antes del viernes?"),
)


class FakeBackend:
    def __init__(self):
        self.calls = []

    def complete(self, system, user, model, max_tokens=4096):
        self.calls.append((system, user))
        return json.dumps({"reply": "Listo.", "intent": "info"})


class PromptBudgetTest(unittest.TestCase):
    """Ollama's 4096-token window silently drops the start of the prompt (the rules)."""

    def request_chars(self, state=True):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        with open("docs/ficha-losetaschile.md", encoding="utf-8") as sheet:
            memory.set_client_knowledge("losetaschile", sheet.read())
        for turn in LONG_CONVERSATION:
            memory.add_turn("losetaschile", "lead-1", turn["role"], turn["text"])
        backend = FakeBackend()
        agents = build_agents(backend=backend)
        agents["CONCIERGE"].prompt_file = "concierge-whatsapp-local.md"
        zero = Zero(agents, memory=memory)
        builder = build_conversation_state if state else (lambda *args: None)
        with mock.patch("zero.orchestrator.build_conversation_state", builder):
            zero.converse_result("losetaschile", "Gracias, ¿cómo se limpian los pastelones?",
                                 lead={"key": "lead-1"}, channel="whatsapp")
        self.assertEqual(len(backend.calls), 1)
        system, user = backend.calls[0]
        return len(system) + len(user), user

    def test_long_conversation_request_fits_the_budget(self):
        total, user = self.request_chars()
        self.assertIn("conversation_state", user)
        self.assertLessEqual(total, config.WHATSAPP_PROMPT_BUDGET_CHARS)

    def test_state_costs_little(self):
        with_state, _ = self.request_chars(True)
        without_state, _ = self.request_chars(False)
        self.assertLess(with_state - without_state, 600)


if __name__ == "__main__":
    unittest.main()
