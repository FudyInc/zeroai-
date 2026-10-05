import unittest
from unittest import mock

from zero.contracts import AgentResponse
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.whatsapp_context import select_history, select_knowledge


class WhatsAppContextTest(unittest.TestCase):
    def test_retrieves_late_policy_within_local_budget(self):
        sheet = ("Empresa: Losetas Chile. Vendemos baldosas.\n\n" +
                 "Productos: " + "variedad de diseños. " * 90 + "\n\n" +
                 "Despacho: Entregamos en Maipú los martes y jueves.")
        selected = select_knowledge(sheet, "¿Cuándo despachan a Maipú?", max_chars=1600)
        self.assertLessEqual(len(selected), 1600)
        self.assertIn("Empresa: Losetas Chile", selected)
        self.assertIn("martes y jueves", selected)

    def test_local_agent_receives_policy_beyond_old_4000_character_cutoff(self):
        memory = SessionMemory(None)
        memory.set_client_knowledge("empresa-a", "Empresa: Losetas Chile.\n\n" +
                                    "Productos: " + "baldosas variadas. " * 260 + "\n\n" +
                                    "Despacho: Maipú solo los jueves.")
        agent = mock.Mock(prompt_file="concierge-whatsapp-local.md")
        zero = Zero({"CONCIERGE": agent}, memory=memory)
        answer = AgentResponse("test", "CONCIERGE", "done", {"reply": "Los jueves."})
        with mock.patch.object(zero, "dispatch", return_value=answer) as dispatch:
            zero.converse_result("empresa-a", "¿Despachan a Maipú?", history=[])
        self.assertIn("Maipú solo los jueves", dispatch.call_args.args[1].data["knowledge"])

    def test_relevant_old_turn_survives_recent_context_limit(self):
        turns = [{"role": "lead", "text": "Necesito baldosas para la terraza"},
                 {"role": "agent", "text": "¿Cuántos metros?"},
                 {"role": "lead", "text": "Son 30 m2"},
                 {"role": "agent", "text": "¿En qué comuna?"},
                 {"role": "lead", "text": "Maipú"},
                 {"role": "agent", "text": "Anotado"}]
        chosen = select_history(turns, "¿Cuánto cuesta para la terraza?", 4)
        self.assertEqual(len(chosen), 4)
        self.assertIn("terraza", " ".join(t["text"] for t in chosen))
        self.assertEqual(chosen[-1]["text"], "Anotado")

    def test_facts_require_literal_customer_evidence_and_stay_per_lead(self):
        memory = SessionMemory(None)
        memory.remember_lead_facts("empresa-a", "lead-1", "Necesito 30 m2 en Maipú", [
            {"kind": "quantity", "evidence": "30 m2"},
            {"kind": "location", "evidence": "Maipú"},
            {"kind": "budget", "evidence": "$900.000"},
        ])
        self.assertEqual({f["kind"] for f in memory.get_lead_facts("empresa-a", "lead-1")},
                         {"quantity", "location"})
        self.assertEqual(memory.get_lead_facts("empresa-b", "lead-1"), [])
        memory.remember_lead_facts("empresa-a", "lead-1", "Ahora en Ñuñoa", [
            {"kind": "location", "evidence": "Ñuñoa"},
        ])
        self.assertIn("Ñuñoa", str(memory.get_lead_facts("empresa-a", "lead-1")))
        self.assertNotIn("Maipú", str(memory.get_lead_facts("empresa-a", "lead-1")))

    def test_real_question_can_be_promoted_only_inside_its_business(self):
        memory = SessionMemory(None)
        memory.add_turn("empresa-a", "lead-1", "lead", "¿Despachan a Maipú?")
        with self.assertRaises(ValueError):
            memory.add_case_from_conversation("empresa-b", "lead-1", "¿Despachan a Maipú?", "Sí")
        case = memory.add_case_from_conversation(
            "empresa-a", "lead-1", "¿Despachan a Maipú?", "Sí, martes y jueves")
        self.assertEqual(case["respuesta_esperada"], "Sí, martes y jueves")
        with self.assertRaises(ValueError):
            memory.add_case_from_conversation("empresa-a", "lead-1", "¿Despachan a Maipú?", "Sí")


if __name__ == "__main__":
    unittest.main()
