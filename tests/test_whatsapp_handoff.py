"""Conversation level WhatsApp handoff without live delivery."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zero.agents import build_agents
from zero.crm import CRM
from zero.memory import SessionMemory
from zero.orchestrator import Zero


class WhatsAppHandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "state.json")
        self.memory = SessionMemory(self.path)
        self.memory.register_client("losetaschile", "STARTER")
        self.memory.register_client("petlabs", "STARTER")
        self.memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        self.memory.set_client_agent_profile("petlabs", {
            "whatsapp_number": "56922222222", "response_mode": "automatic"})
        self.crm = CRM(None)
        self.crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
        self.crm.upsert("petlabs", {"phone": "56933333333", "source": "test"})
        self.zero = Zero(build_agents(mock=True), memory=self.memory, crm=self.crm)
        self.zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web"})

    def inbound(self, text, client="losetaschile", chat="56933333333@c.us"):
        number = "56911111111" if client == "losetaschile" else "56922222222"
        return self.zero.handle_inbound("56933333333", text, to_phone_id=number,
                                        whatsapp_chat_id=chat)

    def test_request_for_human_stops_bot_and_survives_reload(self):
        first = self.inbound("Necesito hablar con una persona")
        self.assertTrue(first["manual_review"])
        self.assertEqual(self.zero._deliver.call_count, 0)
        self.assertIsNotNone(SessionMemory(self.path).get_whatsapp_handoff(
            "losetaschile", "56933333333@c.us"))
        second = self.inbound("Hola, sigo esperando")
        self.assertTrue(second["manual_review"])
        self.assertEqual(self.zero._deliver.call_count, 0)
        self.assertIsNone(self.memory.get_whatsapp_handoff("petlabs", "56933333333@c.us"))

    def test_model_uncertainty_hands_off_and_another_business_still_responds(self):
        with mock.patch.object(self.zero, "converse_result", return_value={
            "reply": "Voy a pedir apoyo al equipo.", "intent": "handoff"}):
            result = self.inbound("No sé explicar bien lo que necesito")
        self.assertTrue(result["manual_review"])
        self.zero._deliver.assert_not_called()
        with mock.patch.object(self.zero, "converse_result", return_value={
            "reply": "Te cuento las opciones.", "intent": "explain"}):
            other = self.inbound("¿Qué venden?", client="petlabs")
        self.assertFalse(other.get("manual_review", False))
        self.assertEqual(self.zero._deliver.call_count, 1)

    def test_repeated_answer_reviews_one_message_without_blocking_next(self):
        with mock.patch.object(self.zero, "converse_result", return_value={
            "reply": "Necesito la comuna de entrega.", "intent": "general"}):
            first = self.inbound("¿Pueden despachar?")
            second = self.inbound("Estoy en La Florida")
        self.assertEqual(first["delivery"]["status"], "sent")
        self.assertTrue(second["manual_review"])
        self.assertEqual(second["delivery"]["status"], "sent")
        self.assertIn("Necesito revisar", self.zero._deliver.call_args.args[3]["body"])
        self.assertEqual(self.zero._deliver.call_count, 2)
        self.assertIsNone(self.zero.memory.get_whatsapp_handoff(
            "losetaschile", "56933333333@c.us"))
        with mock.patch.object(self.zero, "converse_result", return_value={
            "reply": "Gracias, revisaré el despacho a La Florida.", "intent": "general"}):
            resumed = self.inbound("¿Y el despacho?")
        self.assertEqual(resumed["delivery"]["status"], "sent")
        self.assertEqual(self.zero._deliver.call_count, 3)

    def test_empty_agent_reply_hands_off(self):
        with mock.patch.object(self.zero, "converse_result", return_value={}):
            result = self.inbound("[audio]")
        self.assertTrue(result["manual_review"])
        self.zero._deliver.assert_not_called()

    def test_repeated_greeting_still_gets_a_reply(self):
        self.memory.add_turn("losetaschile", "56933333333", "agent", "Necesito las medidas")
        self.memory.save()
        with mock.patch.object(self.zero, "converse_result", return_value={
            "reply": "Necesito las medidas", "intent": "general"}) as draft:
            result = self.inbound("Hola")
        self.assertFalse(result.get("manual_review", False))
        self.assertEqual(result["delivery"]["status"], "sent")
        self.assertEqual(draft.call_count, 1)
        self.assertEqual(self.zero._deliver.call_args.args[3]["body"],
                         "¡Hola! Estoy aquí para ayudarte. ¿Qué necesitas hoy?")
        self.assertIsNone(self.memory.get_whatsapp_handoff(
            "losetaschile", "56933333333@c.us"))

    def test_introduction_is_saved_and_repeated_draft_does_not_silence_chat(self):
        self.memory.add_turn("losetaschile", "56933333333", "agent",
                             "¡Hola! Estoy aquí para ayudarte. ¿Qué necesitas hoy?")
        self.memory.save()
        detached = dict(self.crm.find_by_contact(phone="56933333333", client_id="losetaschile"))
        with mock.patch.object(self.crm, "find_by_contact", return_value=detached), \
             mock.patch.object(self.zero, "converse_result", return_value={
            "reply": "¡Hola! Estoy aquí para ayudarte. ¿Qué necesitas hoy?",
            "intent": "general"}) as draft:
            result = self.inbound("Hola me llamo diego")
        self.assertFalse(result.get("manual_review", False))
        self.assertEqual(draft.call_count, 1)
        self.assertEqual(result["delivery"]["status"], "sent")
        self.assertEqual(self.zero._deliver.call_args.args[3]["body"],
                         "¡Hola, Diego! ¿En qué puedo ayudarte?")
        self.assertEqual(self.crm.get("losetaschile", "56933333333")["name"], "Diego")
        self.assertIsNone(self.memory.get_whatsapp_handoff(
            "losetaschile", "56933333333@c.us"))

    def test_unreadable_text_skips_model_and_hands_off(self):
        with mock.patch.object(self.zero, "converse_result") as draft:
            result = self.inbound("asdgfhj 123 ??")
        self.assertTrue(result["manual_review"])
        draft.assert_not_called()

    def test_supplied_measurements_are_not_requested_again(self):
        self.memory.add_turn("losetaschile", "56933333333", "lead", "Mi piscina mide 7 por 3 metros")
        self.memory.set_client_knowledge("losetaschile", "Cotizaciones y despacho requieren revisión humana.")
        with mock.patch.object(self.zero, "converse_result", side_effect=[
            {"reply": "¿Me das las medidas de la piscina?", "intent": "info"},
            {"reply": "Hacemos despacho a La Florida.", "intent": "info"},
        ]) as draft:
            result = self.inbound("¿Hacen despacho a La Florida?")
        self.assertEqual(draft.call_count, 2)
        self.assertTrue(result["manual_review"])
        self.zero._deliver.assert_not_called()

    def test_human_takeover_during_draft_prevents_send(self):
        def draft(*args, **kwargs):
            concurrent = SessionMemory(self.path)
            concurrent.set_whatsapp_handoff("losetaschile", "56933333333@c.us",
                                            "El equipo tomó la conversación")
            concurrent.save()
            return {"reply": "Podemos ayudarte con eso.", "intent": "general"}

        with mock.patch.object(self.zero, "converse_result", side_effect=draft):
            result = self.inbound("¿Me pueden ayudar?")
        self.assertTrue(result["manual_review"])
        self.zero._deliver.assert_not_called()
        self.assertIsNotNone(SessionMemory(self.path).get_whatsapp_handoff(
            "losetaschile", "56933333333@c.us"))

    def test_unverified_quote_review_is_not_sent(self):
        with mock.patch.object(self.zero, "converse_result", side_effect=[
            {"reply": "Ya revisé tu cotización; está aprobada.", "intent": "pricing"},
            {"reply": "Confirmé tu presupuesto y podemos seguir.", "intent": "pricing"},
        ]):
            result = self.inbound("¿Qué pasó con mi cotización?")
        self.assertTrue(result["manual_review"])
        self.zero._deliver.assert_not_called()

    def test_inbox_handoff_control_is_scoped_to_selected_business(self):
        import api
        from fastapi import HTTPException

        def bridge(path, body=None, client=None):
            if path == "/chats":
                return {"chats": [{"id": "56933333333@c.us"}] if client == "losetaschile" else []}
            raise AssertionError("No debe enviar mensajes")

        with mock.patch.object(api, "make_memory", return_value=self.memory), \
             mock.patch.object(api, "_whatsapp_web_inbox_request", side_effect=bridge):
            result = api.whatsapp_web_handoff("56933333333@c.us",
                                              api.WhatsAppHandoffBody(active=True),
                                              client="losetaschile")
            self.assertIsNotNone(result["handoff"])
            self.assertIsNone(self.memory.get_whatsapp_handoff("petlabs", "56933333333@c.us"))
            with self.assertRaises(HTTPException) as rejected:
                api.whatsapp_web_handoff("56933333333@c.us",
                                         api.WhatsAppHandoffBody(active=True), client="petlabs")
            self.assertEqual(rejected.exception.status_code, 404)
            api.whatsapp_web_handoff("56933333333@c.us",
                                     api.WhatsAppHandoffBody(active=False), client="losetaschile")
            self.assertIsNone(self.memory.get_whatsapp_handoff("losetaschile", "56933333333@c.us"))


if __name__ == "__main__":
    unittest.main()
