"""Conversation level WhatsApp handoff without live delivery."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zero.agents import build_agents
from zero.crm import CRM
from zero.config import (WHATSAPP_FALLBACK_GREETINGS, WHATSAPP_FALLBACK_GREETINGS_NAMED,
                         WHATSAPP_REVIEW_NOTICES)
from zero.contracts import AgentResponse
from zero.memory import SessionMemory
from zero.losetas_shipping import (DELIVERY_LOCATION_PROMPT, DELIVERY_POLL_LOCATION,
                                   SHIPPING_COVERAGE_REPLY)
from zero.orchestrator import Zero, _unverified_quote_review_claim


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
        self.assertEqual(result["delivery"]["status"], "sent")
        self.assertIsNone(self.memory.get_whatsapp_handoff(
            "losetaschile", "56933333333@c.us"))
        with mock.patch.object(self.zero, "converse_result", return_value={
            "reply": "Te cuento las opciones.", "intent": "explain"}):
            other = self.inbound("¿Qué venden?", client="petlabs")
        self.assertFalse(other.get("manual_review", False))
        self.assertEqual(self.zero._deliver.call_count, 2)

    def test_repeated_answer_reviews_one_message_without_blocking_next(self):
        with mock.patch.object(self.zero, "converse_result", return_value={
            "reply": "Necesito la comuna de entrega.", "intent": "general"}):
            first = self.inbound("¿Pueden despachar?")
            second = self.inbound("Estoy en La Florida")
        self.assertEqual(first["delivery"]["status"], "sent")
        self.assertTrue(second["manual_review"])
        self.assertEqual(second["delivery"]["status"], "sent")
        self.assertIn(self.zero._deliver.call_args.args[3]["body"], WHATSAPP_REVIEW_NOTICES)
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
        with mock.patch("zero.orchestrator.whatsapp_greeting", return_value="Buenas noches"), \
             mock.patch.object(self.zero, "converse_result", return_value={
            "reply": "Necesito las medidas", "intent": "general"}) as draft:
            result = self.inbound("Hola")
        self.assertFalse(result.get("manual_review", False))
        self.assertEqual(result["delivery"]["status"], "sent")
        self.assertEqual(draft.call_count, 1)
        self.assertIn(self.zero._deliver.call_args.args[3]["body"],
                      [v.format(greeting="Buenas noches") for v in WHATSAPP_FALLBACK_GREETINGS])
        self.assertIsNone(self.memory.get_whatsapp_handoff(
            "losetaschile", "56933333333@c.us"))

    def test_introduction_is_saved_and_repeated_draft_does_not_silence_chat(self):
        self.memory.add_turn("losetaschile", "56933333333", "agent",
                             "¡Hola! Estoy aquí para ayudarte. ¿Qué necesitas hoy?")
        self.memory.save()
        detached = dict(self.crm.find_by_contact(phone="56933333333", client_id="losetaschile"))
        with mock.patch("zero.orchestrator.whatsapp_greeting", return_value="Buenas noches"), \
             mock.patch.object(self.crm, "find_by_contact", return_value=detached), \
             mock.patch.object(self.zero, "converse_result", return_value={
            "reply": "¡Hola! Estoy aquí para ayudarte. ¿Qué necesitas hoy?",
            "intent": "general"}) as draft:
            result = self.inbound("Hola me llamo diego")
        self.assertFalse(result.get("manual_review", False))
        self.assertEqual(draft.call_count, 1)
        self.assertEqual(result["delivery"]["status"], "sent")
        self.assertIn(self.zero._deliver.call_args.args[3]["body"],
                      [v.format(greeting="Buenas noches", name="Diego")
                       for v in WHATSAPP_FALLBACK_GREETINGS_NAMED])
        self.assertEqual(self.crm.get("losetaschile", "56933333333")["name"], "Diego")
        self.assertIsNone(self.memory.get_whatsapp_handoff(
            "losetaschile", "56933333333@c.us"))

    def test_unreadable_text_skips_model_and_hands_off(self):
        with mock.patch.object(self.zero, "converse_result") as draft:
            result = self.inbound("asdgfhj 123 ??")
        self.assertTrue(result["manual_review"])
        draft.assert_not_called()

    def test_unreadable_meta_placeholders_skip_model(self):
        for marker in ("[interactive]", "[contacts]", "[image]"):
            with self.subTest(marker=marker), mock.patch.object(self.zero, "converse_result") as draft:
                result = self.inbound(marker, chat=f"{marker}@c.us")
            self.assertTrue(result["manual_review"])
            draft.assert_not_called()
        with mock.patch.object(self.zero, "converse_result") as draft:
            result = self.inbound("[location] https://www.google.com/maps?q=-33.61,-70.64",
                                  client="petlabs", chat="other-location@c.us")
        self.assertTrue(result["manual_review"])
        draft.assert_not_called()

    def test_invalid_generated_reply_sends_review_notice_instead(self):
        self.zero.agents["CONCIERGE"].prompt_file = "concierge-whatsapp-local.md"
        unsafe = AgentResponse("test", "CONCIERGE", "done",
                               {"reply": "Sale $99.000 al mes.", "intent": "pricing"})
        with mock.patch.object(self.zero, "dispatch", return_value=unsafe) as dispatch:
            result = self.inbound("¿Cuánto cuesta el servicio?", client="petlabs")
        self.assertEqual(dispatch.call_count, 2)
        self.assertTrue(result["manual_review"])
        body = self.zero._deliver.call_args.args[3]["body"]
        self.assertIn(body, WHATSAPP_REVIEW_NOTICES)
        self.assertNotIn("$99.000", body)

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
        self.assertEqual(result["delivery"]["status"], "sent")
        self.assertNotIn("Hacemos despacho", self.zero._deliver.call_args.args[3]["body"])

    @mock.patch("zero.orchestrator.LOSETASCHILE_CHOICE_STYLE", "poll")
    def test_verified_shipping_coverage_is_sent_without_handoff(self):
        from zero.whatsapp_format import format_whatsapp_reply
        self.memory.set_client_knowledge(
            "losetaschile", "Cotizaciones y despacho requieren revisión humana.")
        with mock.patch("zero.whatsapp_web.send_delivery_poll", return_value={
                "status": "sent", "id": "poll-1"}) as send_poll:
            result = self.inbound("¿Despachan a Los Andes?")
        self.assertFalse(result.get("manual_review", False))
        body = self.zero._deliver.call_args.args[3]["body"]
        self.assertEqual(body, result["reply"])
        self.assertIn("\n\n¿Dónde sería la entrega?\n\n", body)
        self.assertEqual(body.replace("\n\n", " "), SHIPPING_COVERAGE_REPLY)
        self.assertEqual(body, format_whatsapp_reply(SHIPPING_COVERAGE_REPLY))
        self.assertEqual(result["poll_delivery"]["id"], "poll-1")
        send_poll.assert_called_once()

    def test_second_coverage_question_remains_answerable(self):
        self.memory.set_client_knowledge(
            "losetaschile", "Cotizaciones y despacho requieren revisión humana.")
        with mock.patch("zero.whatsapp_web.send_delivery_poll", return_value={
                "status": "sent", "id": "poll-1"}):
            first = self.inbound("¿Tienen despachos?")
            second = self.inbound("¿Despachan a Los Andes?")
        self.assertFalse(first.get("manual_review", False))
        self.assertFalse(second.get("manual_review", False))
        self.assertEqual(self.zero._deliver.call_count, 2)

    @mock.patch("zero.orchestrator.LOSETASCHILE_CHOICE_STYLE", "poll")
    def test_poll_failure_keeps_text_answer_and_direct_location_option(self):
        with mock.patch("zero.whatsapp_web.send_delivery_poll",
                        side_effect=RuntimeError("resultado incierto")):
            result = self.inbound("¿Hacen despachos?")
        self.assertFalse(result.get("manual_review", False))
        self.assertEqual(result["delivery"]["status"], "sent")
        self.assertEqual(result["poll_delivery"]["status"], "error")
        self.assertIn("compartir tu ubicación aquí", result["reply"])

    def test_poll_choice_gets_one_instruction_without_new_poll(self):
        result = self.inbound(DELIVERY_POLL_LOCATION)
        self.assertFalse(result.get("manual_review", False))
        self.assertEqual(result["reply"], DELIVERY_LOCATION_PROMPT)
        self.assertIsNone(result["poll_delivery"])

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
        self.assertEqual(result["delivery"]["status"], "sent")
        self.assertNotIn("revisé", self.zero._deliver.call_args.args[3]["body"])
        self.assertIsNone(self.memory.get_whatsapp_handoff(
            "losetaschile", "56933333333@c.us"))

    def test_real_unverified_consulta_draft_gets_notice_then_greeting(self):
        draft = "¡Hola Diego! Ya revisé tu consulta. ¿Cuál modelo y medidas necesitas?"
        self.assertTrue(_unverified_quote_review_claim(draft))
        self.assertFalse(_unverified_quote_review_claim(
            "Voy a revisar tu consulta antes de responder."))
        with mock.patch.object(self.zero, "converse_result", side_effect=[
            {"reply": draft, "intent": "info"},
            {"reply": draft, "intent": "info"},
        ]) as generated:
            first = self.inbound("¿Qué pasó con mi pedido?")
        self.assertEqual(generated.call_count, 2)
        self.assertTrue(first["manual_review"])
        self.assertEqual(first["delivery"]["status"], "sent")
        self.assertNotIn("Ya revisé", self.zero._deliver.call_args.args[3]["body"])
        self.assertIsNone(SessionMemory(self.path).get_whatsapp_handoff(
            "losetaschile", "56933333333@c.us"))
        with mock.patch.object(self.zero, "converse_result", return_value={
            "reply": "¡Hola! ¿En qué puedo ayudarte?", "intent": "general"}):
            second = self.inbound("Hola")
        self.assertFalse(second.get("manual_review", False))
        self.assertEqual(second["delivery"]["status"], "sent")
        self.assertEqual(self.zero._deliver.call_count, 2)

    def test_failed_review_notice_does_not_retry_uncertain_delivery(self):
        self.zero._deliver = mock.Mock(side_effect=[
            {"status": "error", "via": "whatsapp_web", "error": "timeout"},
            {"status": "sent", "via": "whatsapp_web"},
        ])
        with mock.patch.object(self.zero, "converse_result", side_effect=[
            {"reply": "Ya revisé tu consulta.", "intent": "info"},
            {"reply": "Ya revisé tu consulta.", "intent": "info"},
        ]):
            first = self.inbound("¿Qué pasó con mi pedido?")
        self.assertEqual(first["delivery"]["status"], "error")
        self.assertIsNone(self.memory.get_whatsapp_handoff(
            "losetaschile", "56933333333@c.us"))
        with mock.patch.object(self.zero, "converse_result", return_value={
            "reply": "¡Hola! ¿En qué puedo ayudarte?", "intent": "general"}):
            second = self.inbound("Hola")
        self.assertEqual(second["delivery"]["status"], "sent")
        self.assertEqual(self.zero._deliver.call_count, 2)

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
