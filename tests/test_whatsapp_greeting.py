"""WhatsApp salutation follows Chile's clock, including daylight saving time."""
import unittest
from datetime import datetime, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from zero.contracts import AgentResponse
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.whatsapp_greeting import align_opening_greeting, whatsapp_greeting


class WhatsAppGreetingTest(unittest.TestCase):
    def test_hour_boundaries_in_chile(self):
        chile = ZoneInfo("America/Santiago")
        for hour, expected in ((4, "Buenas noches"), (5, "Buenos días"),
                               (11, "Buenos días"), (12, "Buenas tardes"),
                               (19, "Buenas tardes"), (20, "Buenas noches")):
            with self.subTest(hour=hour):
                self.assertEqual(whatsapp_greeting(datetime(2026, 10, 11, hour,
                                                            tzinfo=chile)), expected)

    def test_daylight_saving_uses_named_zone(self):
        self.assertEqual(whatsapp_greeting(datetime(2026, 1, 10, 15,
                                                     tzinfo=timezone.utc)), "Buenas tardes")
        self.assertEqual(whatsapp_greeting(datetime(2026, 7, 10, 15,
                                                     tzinfo=timezone.utc)), "Buenos días")

    def test_simple_afternoon_greeting_at_night_is_answered_as_night(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        agent = mock.Mock(prompt_file="concierge-whatsapp-local.md")
        zero = Zero({"CONCIERGE": agent}, memory=memory)
        with mock.patch("zero.orchestrator.whatsapp_greeting", return_value="Buenas noches"), \
             mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result("losetaschile", "Buenas tardes")
        self.assertEqual(result["reply"], "¡Buenas noches! ¿En qué puedo ayudarte?")
        dispatch.assert_not_called()

    def test_other_business_keeps_persona_and_corrects_wrong_greeting(self):
        memory = SessionMemory(None)
        memory.register_client("zeroai", "GROWTH")
        agent = mock.Mock(prompt_file="concierge-whatsapp-local.md")
        zero = Zero({"CONCIERGE": agent}, memory=memory)
        answer = AgentResponse("test", "CONCIERGE", "done", {
            "reply": "Buenas tardes, soy Fernanda. ¿En qué te ayudo?", "intent": "general"})
        with mock.patch("zero.orchestrator.whatsapp_greeting", return_value="Buenas noches"), \
             mock.patch.object(zero, "dispatch", return_value=answer):
            result = zero.converse_result("zeroai", "Buenas tardes")
        self.assertEqual(result["reply"],
                         "Buenas noches, soy Fernanda. ¿En qué te ayudo?")

    def test_model_receives_greeting_and_wrong_opening_is_corrected(self):
        memory = SessionMemory(None)
        memory.register_client("zeroai", "GROWTH")
        agent = mock.Mock(prompt_file="concierge-whatsapp-local.md")
        zero = Zero({"CONCIERGE": agent}, memory=memory)
        answer = AgentResponse("test", "CONCIERGE", "done", {
            "reply": "Buenas tardes, te cuento cómo funciona.", "intent": "explain"})
        with mock.patch("zero.orchestrator.whatsapp_greeting", return_value="Buenas noches"), \
             mock.patch.object(zero, "dispatch", return_value=answer) as dispatch:
            result = zero.converse_result("zeroai", "Buenas tardes, ¿cómo funciona?")
        self.assertEqual(dispatch.call_args.args[1].data["greeting"], "Buenas noches")
        self.assertEqual(result["reply"], "Buenas noches, te cuento cómo funciona.")
        self.assertEqual(align_opening_greeting("El horario no está confirmado.",
                                                "Buenas noches"),
                         "El horario no está confirmado.")
        self.assertEqual(align_opening_greeting("Hola, buenas tardes. Te cuento.",
                                                "Buenas noches"),
                         "Buenas noches. Te cuento.")
        self.assertEqual(align_opening_greeting("¡Hola! Buenas tardes, te cuento.",
                                                "Buenas noches"),
                         "¡Buenas noches! Te cuento.")
        self.assertEqual(align_opening_greeting("Hola Diego, buenas tardes. Te cuento.",
                                                "Buenas noches"),
                         "Buenas noches, Diego. Te cuento.")
        self.assertEqual(align_opening_greeting("Hola, Diego, buenas tardes. Te cuento.",
                                                "Buenas noches"),
                         "Buenas noches, Diego. Te cuento.")
        self.assertEqual(align_opening_greeting("¡Hola, Diego! Buenas tardes.",
                                                "Buenas noches"),
                         "¡Buenas noches, Diego!")


if __name__ == "__main__":
    unittest.main()
