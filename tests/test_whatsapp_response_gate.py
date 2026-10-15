"""Generated WhatsApp replies are checked before any calculated quote is appended."""
import unittest
from unittest import mock

from zero.contracts import AgentResponse
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.quotes import normalize_pricing


class WhatsAppResponseGateTest(unittest.TestCase):
    def setUp(self):
        self.memory = SessionMemory(None)
        self.memory.register_client("acme", "STARTER")
        agent = mock.Mock(prompt_file="concierge-whatsapp-local.md")
        self.zero = Zero({"CONCIERGE": agent}, memory=self.memory)

    @staticmethod
    def response(reply, intent="pricing"):
        return AgentResponse("test", "CONCIERGE", "done",
                             {"reply": reply, "intent": intent})

    def test_unsupported_model_amount_is_retried(self):
        with mock.patch.object(self.zero, "dispatch", side_effect=[
            self.response("Sale $99.000 al mes."),
            self.response("Te preparo una propuesta según lo que necesites."),
        ]) as dispatch:
            result = self.zero.converse_result("acme", "¿Cuánto cuesta?")
        self.assertEqual(dispatch.call_count, 2)
        self.assertNotIn("$", result["reply"])
        self.assertIn("propuesta", result["reply"])

    def test_two_unsafe_drafts_go_to_review(self):
        with mock.patch.object(self.zero, "dispatch", side_effect=[
            self.response("Sale $99.000 al mes."),
            self.response("Sale $89.000 al mes."),
        ]):
            result = self.zero.converse_result("acme", "¿Cuánto cuesta?")
        self.assertEqual(result, {"reply": "", "intent": "handoff"})

    def test_calculated_quote_remains_available_after_model_check(self):
        self.memory.set_client_pricing("acme", normalize_pricing({
            "currency": "CLP", "iva_rate": 0.19,
            "items": [{"id": "sitio-web", "name": "sitio web", "unit_price": 12000}],
        }))
        with mock.patch.object(self.zero, "dispatch", return_value=self.response(
                "Te comparto el presupuesto calculado.")) as dispatch:
            result = self.zero.converse_result("acme", "precio de dos sitio web")
        dispatch.assert_called_once()
        self.assertIn("$", result["reply"])
        self.assertEqual(result["quote"]["lines"][0]["qty"], 2)


if __name__ == "__main__":
    unittest.main()
