"""Compact local context must retain relevant facts from long conversations."""
import unittest
from unittest import mock

from zero.contracts import AgentResponse
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.whatsapp_context import select_history, select_knowledge
from scripts.cargar_empresa import leer_ficha


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

    def test_restaurant_question_includes_relevant_offer(self):
        sheet = leer_ficha("docs/ficha-zeroai.md")
        selected = select_knowledge(sheet, "Tengo un restaurante, ¿qué me ofrecen?", 1600)
        self.assertIn("toma pedidos y agenda reservas", " ".join(selected.split()))

    def test_uppercase_final_policy_is_not_lost(self):
        selected = select_knowledge("Empresa: Ejemplo.\n\nNO HACEMOS DESPACHO",
                                    "¿Hacen despacho?", 1600)
        self.assertIn("NO HACEMOS DESPACHO", selected)

    def test_explicit_new_topic_does_not_retrieve_previous_service(self):
        sheet = leer_ficha("docs/ficha-zeroai.md")
        memory = SessionMemory(None)
        memory.register_client("zeroai", "GROWTH")
        memory.set_client_knowledge("zeroai", sheet)
        agent = mock.Mock(prompt_file="concierge-whatsapp-local.md")
        zero = Zero({"CONCIERGE": agent}, memory=memory)
        answer = AgentResponse("test", "CONCIERGE", "done", {"reply": "Te cuento."})
        turns = [{"role": "lead", "text": "Me interesan los leads B2B"},
                 {"role": "agent", "text": "Podemos conseguir leads B2B calificados."}]
        with mock.patch.object(zero, "dispatch", return_value=answer) as dispatch:
            zero.converse_result("zeroai", "Tengo un restaurante, ¿qué me ofrecen?",
                                 history=turns)
        selected = dispatch.call_args.args[1].data["knowledge"]
        self.assertIn("toma pedidos y agenda reservas", " ".join(selected.split()))

    def test_freight_question_finds_shipping_policy(self):
        sheet = "Empresa: Ejemplo.\n\n" + "\n\n".join(
            f"Producto {i}: " + "baldosas decorativas. " * 20 for i in range(8))
        sheet += "\n\nDespacho: requiere revisión humana antes de confirmar entrega."
        selected = select_knowledge(sheet, "¿Cuánto cuesta el flete?", 1600)
        self.assertIn("requiere revisión humana", selected)

    def test_followup_uses_recent_topic_to_retrieve_policy(self):
        sheet = "Empresa: Ejemplo.\n\n" + "\n\n".join(
            f"Producto {i}: " + "baldosas decorativas. " * 20 for i in range(8))
        sheet += "\n\nDespacho: requiere revisión humana antes de confirmar entrega."
        memory = SessionMemory(None)
        memory.register_client("ejemplo", "STARTER")
        memory.set_client_knowledge("ejemplo", sheet)
        agent = mock.Mock(prompt_file="concierge-whatsapp-local.md")
        zero = Zero({"CONCIERGE": agent}, memory=memory)
        answer = AgentResponse("test", "CONCIERGE", "done", {"reply": "Lo revisamos."})
        turns = [{"role": "lead", "text": "¿Hacen despacho?"},
                 {"role": "agent", "text": "El despacho requiere revisión."}]
        with mock.patch.object(zero, "dispatch", return_value=answer) as dispatch:
            zero.converse_result("ejemplo", "¿Y eso cuánto cuesta?", history=turns)
        selected = dispatch.call_args.args[1].data["knowledge"]
        self.assertIn("requiere revisión humana", selected)

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

    def test_realistic_long_chat_keeps_latest_model_size_and_location(self):
        turns = [
            {"role": "lead", "text": "Mi piscina mide 7x3 rectangular"},
            {"role": "agent", "text": "¿Qué modelo te interesa?"},
            {"role": "lead", "text": "Es de 6x3 rectangular"},
            {"role": "lead", "text": "Borde recto con nariz"},
            {"role": "agent", "text": "¿En qué comuna estás?"},
            {"role": "lead", "text": "Ñuñoa"},
        ]
        turns += [{"role": "agent", "text": f"Conversación intermedia {i}"}
                  for i in range(20)]
        turns += [{"role": "agent", "text": "Te escucho"},
                  {"role": "lead", "text": "¿Podemos continuar?"}]
        chosen = select_history(turns, "¿Podemos continuar?", 6)
        visible = " ".join(turn["text"] for turn in chosen)
        self.assertIn("6x3 rectangular", visible)
        self.assertNotIn("7x3", visible)
        self.assertIn("Borde recto con nariz", visible)
        self.assertIn("Ñuñoa", visible)
        self.assertLessEqual(len(chosen), 6)

    def test_orchestrator_fetches_old_turn_before_compacting_for_local_model(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        memory.set_client_knowledge("losetaschile", "Empresa: LosetasChile.")
        memory.add_turn("losetaschile", "lead-1", "lead", "La piscina mide 7 por 3 metros")
        for number in range(16):
            memory.add_turn("losetaschile", "lead-1", "agent", f"Turno {number}")
        agent = mock.Mock(prompt_file="concierge-whatsapp-local.md")
        zero = Zero({"CONCIERGE": agent}, memory=memory)
        answer = AgentResponse("test", "CONCIERGE", "done", {"reply": "Revisamos las opciones."})
        with mock.patch.object(zero, "dispatch", return_value=answer) as dispatch:
            zero.converse_result("losetaschile", "Mi piscina de 7 por 3, ¿qué materiales tienen?",
                                 lead={"key": "lead-1"})
        history = dispatch.call_args.args[1].data["history"]
        self.assertTrue(any("7 por 3" in turn["text"] for turn in history))

    def test_local_model_receives_three_order_facts_after_long_chat(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        for role, text in [
            ("lead", "Es de 6x3 rectangular"),
            ("lead", "Borde recto con nariz"),
            ("agent", "¿En qué comuna estás?"),
            ("lead", "Ñuñoa"),
        ]:
            memory.add_turn("losetaschile", "lead-1", role, text)
        for number in range(20):
            memory.add_turn("losetaschile", "lead-1", "agent", f"Turno {number}")
        agent = mock.Mock(prompt_file="concierge-whatsapp-local.md")
        zero = Zero({"CONCIERGE": agent}, memory=memory)
        answer = AgentResponse("test", "CONCIERGE", "done", {"reply": "Cuéntame tu duda."})
        with mock.patch.object(zero, "dispatch", return_value=answer) as dispatch:
            zero.converse_result("losetaschile", "Hola, ¿seguimos?", lead={"key": "lead-1"})
        visible = " ".join(turn["text"] for turn in dispatch.call_args.args[1].data["history"])
        self.assertIn("6x3 rectangular", visible)
        self.assertIn("Borde recto con nariz", visible)
        self.assertIn("Ñuñoa", visible)


if __name__ == "__main__":
    unittest.main()
