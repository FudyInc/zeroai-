"""Compact local context must retain relevant facts from long conversations."""
import unittest
from unittest import mock

from zero.contracts import AgentResponse
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.whatsapp_context import select_history, select_knowledge


class WhatsAppContextTest(unittest.TestCase):
    def test_relevant_older_customer_turn_survives_context_limit(self):
        turns = [
            {"role": "lead", "text": "Necesito baldosas para mi piscina"},
            {"role": "agent", "text": "¿Cuánto mide?"},
            {"role": "lead", "text": "La piscina mide 7 por 3 metros"},
            {"role": "agent", "text": "Gracias"},
            {"role": "lead", "text": "Estoy en Maipú"},
            {"role": "agent", "text": "Anotado"},
        ]
        chosen = select_history(turns, "¿Cuánto cuesta para la piscina?", 4)
        self.assertEqual(len(chosen), 4)
        self.assertIn("piscina", " ".join(turn["text"] for turn in chosen))
        self.assertEqual(chosen[-1]["text"], "Anotado")

    def test_local_agent_receives_relevant_late_business_policy(self):
        sheet = ("Empresa: LosetasChile.\n\n" +
                 "Productos: " + "baldosas decorativas. " * 90 + "\n\n" +
                 "Despacho: requiere revisión humana antes de confirmar entrega.")
        selected = select_knowledge(sheet, "¿Hacen despacho?", 1600)
        self.assertIn("revisión humana", selected)
        self.assertLessEqual(len(selected), 1600)

    def test_measurement_and_location_survive_unrelated_recent_turns(self):
        turns = [{"role": "lead", "text": "La piscina mide 7 por 3 metros"},
                 {"role": "lead", "text": "Estoy en Maipú"}]
        turns += [{"role": "lead", "text": f"Gracias por responder {i}"}
                  for i in range(14)]
        turns += [{"role": "agent", "text": "Cuéntame"},
                  {"role": "lead", "text": "Quiero saber el despacho"}]
        chosen = select_history(turns, "¿Cuánto cuesta y hacen despacho?", 4)
        visible = " ".join(turn["text"] for turn in chosen)
        self.assertIn("7 por 3", visible)
        self.assertIn("Maipú", visible)

    def test_orchestrator_fetches_old_turn_before_compacting_for_local_model(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        memory.set_client_knowledge("losetaschile", "Empresa: LosetasChile.")
        memory.add_turn("losetaschile", "lead-1", "lead", "La piscina mide 7 por 3 metros")
        for number in range(16):
            memory.add_turn("losetaschile", "lead-1", "agent", f"Turno {number}")
        agent = mock.Mock(prompt_file="concierge-whatsapp-local.md")
        zero = Zero({"CONCIERGE": agent}, memory=memory)
        answer = AgentResponse("test", "CONCIERGE", "done", {"reply": "Revisamos el despacho."})
        with mock.patch.object(zero, "dispatch", return_value=answer) as dispatch:
            zero.converse_result("losetaschile", "Mi piscina de 7 por 3, ¿despachan?",
                                 lead={"key": "lead-1"})
        history = dispatch.call_args.args[1].data["history"]
        self.assertTrue(any("7 por 3" in turn["text"] for turn in history))


if __name__ == "__main__":
    unittest.main()
