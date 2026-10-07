import unittest
from types import SimpleNamespace
from unittest import mock

from zero.agents import build_agents
from zero.crm import CRM
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.pool_border import (border_count_reply, delegates_piece_calculation,
                              wants_product_quote)


class PoolBorderCountTest(unittest.TestCase):
    def priced_memory(self, include_corner=True):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        items = [{"id": "borde-recto-nariz-50x50", "name": "Borde recto con nariz 50x50",
                  "unit_price": 6000, "unit": "unidad"}]
        if include_corner:
            items.append({"id": "esquina-piscina-50x50", "name": "Esquina piscina 50x50",
                          "unit_price": 3600, "unit": "unidad"})
        memory.set_client_pricing("losetaschile", {"currency": "CLP", "iva_rate": 0,
                                                   "items": items})
        for text in ("Mi piscina es rectangular de 6x3", "Borde recto con nariz",
                     "Ñuñoa"):
            memory.add_turn("losetaschile", "test-lead", "lead", text)
        return memory

    def test_confirmed_six_by_three_rule(self):
        history = [
            {"role": "lead", "text": "Es rectangular de 6x3"},
            {"role": "lead", "text": "Borde recto con nariz"},
        ]
        reply = border_count_reply(
            "¿Cuántos pastelones caben en una piscina de 6x3 rectangular?", history)
        self.assertIn("36 bordes rectos de 50 cm más 4 esquinas", reply)
        self.assertNotIn("24 piezas", reply)

    def test_newer_measurement_replaces_old_one(self):
        history = [
            {"role": "lead", "text": "Mi piscina mide 7x3"},
            {"role": "lead", "text": "Es rectangular de 6x3"},
            {"role": "lead", "text": "Borde recto con nariz"},
        ]
        reply = border_count_reply("¿Cuántos bordes necesito?", history)
        self.assertIn("36 bordes rectos", reply)

    def test_unknown_product_asks_instead_of_guessing(self):
        reply = border_count_reply("¿Cuántos pastelones para piscina 6x3?", [])
        self.assertIn("Qué modelo", reply)
        self.assertNotIn("36", reply)

    def test_non_half_metre_sides_need_review(self):
        reply = border_count_reply("¿Cuántos bordes para piscina rectangular 6,2x3?",
                                   [{"role": "lead", "text": "Borde recto con nariz"}])
        self.assertIn("confirmar", reply)
        self.assertNotIn("bordes rectos más", reply)

    def test_conversation_uses_verified_count_without_model(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        memory.add_turn("losetaschile", "test-lead", "lead", "Borde recto con nariz")
        zero = Zero(build_agents(mock=True), memory=memory)
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "¿Cuántos pastelones para una piscina rectangular de 6x3?",
                lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("36 bordes rectos de 50 cm más 4 esquinas", result["reply"])
        self.assertLess(len(result["reply"]), 100)

    def test_price_question_does_not_enter_piece_counter(self):
        self.assertIsNone(border_count_reply(
            "¿Cuánto cuestan los bordes rectos con nariz para piscina rectangular 6x3?", []))

    def test_negated_product_does_not_get_straight_border_count(self):
        reply = border_count_reply(
            "No quiero borde recto con nariz; ¿cuántos pastelones para piscina rectangular 6x3?", [])
        self.assertNotIn("36 bordes", reply)

    def test_oval_pool_does_not_get_rectangle_count(self):
        reply = border_count_reply(
            "¿Cuántos bordes rectos con nariz para piscina ovalada de 6x3?", [])
        self.assertNotIn("36 bordes", reply)

    def test_rectangle_shape_must_be_confirmed(self):
        reply = border_count_reply(
            "¿Cuántos bordes rectos con nariz para piscina 6x3?", [])
        self.assertIn("rectangular", reply)
        self.assertNotIn("36 bordes", reply)

    def test_latest_shape_overrides_old_rectangle(self):
        history = [
            {"role": "lead", "text": "Mi piscina es rectangular 6x3"},
            {"role": "lead", "text": "Perdón, es ovalada 6x3"},
            {"role": "lead", "text": "Borde recto con nariz"},
        ]
        reply = border_count_reply("¿Cuántos bordes necesito?", history)
        self.assertNotIn("36 bordes", reply)

    def test_latest_product_overrides_old_straight_border(self):
        history = [
            {"role": "lead", "text": "Borde recto con nariz"},
            {"role": "lead", "text": "Mejor quiero borde ballena"},
            {"role": "lead", "text": "Mi piscina es rectangular 6x3"},
        ]
        reply = border_count_reply("¿Cuántos bordes necesito?", history)
        self.assertNotIn("36 bordes", reply)

    def test_plural_other_product_overrides_old_straight_border(self):
        history = [
            {"role": "lead", "text": "Borde recto con nariz"},
            {"role": "lead", "text": "Ahora quiero bordes ballena"},
            {"role": "lead", "text": "Mi piscina es rectangular 6x3"},
        ]
        reply = border_count_reply("¿Cuántos bordes necesito?", history)
        self.assertNotIn("36 bordes", reply)

    def test_dimensions_in_feet_are_not_treated_as_metres(self):
        reply = border_count_reply(
            "¿Cuántos bordes rectos con nariz para piscina rectangular 6x3 pies?", [])
        self.assertIn("metros", reply)
        self.assertNotIn("36 bordes", reply)

    def test_real_followup_with_typo_uses_previous_pool_details(self):
        history = [
            {"role": "lead", "text": "Es de 6x3"},
            {"role": "lead", "text": "Borde recto con nariz"},
            {"role": "lead", "text": "Si cuantos pastelones caben en una piscina de 6x3 rectangular?"},
        ]
        reply = border_count_reply(
            "Cuantos bordea necesito entonces para es piscina?", history)
        self.assertEqual(
            reply, "Para tu piscina de 6 × 3 m: 36 bordes rectos de 50 cm más 4 esquinas.")

    def test_calculation_instructions_are_rejected_for_quantity_question(self):
        self.assertTrue(delegates_piece_calculation(
            "¿Cuántos bordes para mi piscina?",
            "Para calcular los bordes, divide el perímetro entre el largo de la pieza."))
        self.assertFalse(delegates_piece_calculation(
            "¿Cómo calculo el perímetro?",
            "Divide el perímetro entre el largo de la pieza."))

    def test_model_advice_is_replaced_before_customer_reply(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        zero = Zero(build_agents(mock=True), memory=memory)
        draft = SimpleNamespace(result={
            "reply": "Para calcular los bordes, divide el perímetro por el largo.",
            "intent": "info"}, status="ok")
        with mock.patch.object(zero, "dispatch", return_value=draft):
            result = zero.converse_result(
                "losetaschile", "¿Cuántos bords para mi piscina?", channel="whatsapp")
        self.assertNotIn("divide", result["reply"])
        self.assertIn("confirmas", result["reply"])

    def test_location_completes_product_subtotal_without_shipping(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "[location]", lead={"key": "test-lead"},
                channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("36 bordes × $6.000 = $216.000", result["reply"])
        self.assertIn("4 esquinas × $3.600 = $14.400", result["reply"])
        self.assertIn("Productos: $230.400", result["reply"])
        self.assertIn("Despacho: por cotizar", result["reply"])
        self.assertEqual(result["quote"]["total"], 230400)
        self.assertTrue(result["quote"]["shipping_pending"])
        self.assertNotIn("shipping", result["quote"])

    def test_price_and_quantity_question_gets_subtotal(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "¿Cuántos bordes y cuánto cuesta para mi piscina?",
                lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("Productos: $230.400", result["reply"])

    def test_plural_price_question_uses_confirmed_order(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "¿Cuánto cuestan los bordes?",
                lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("Productos: $230.400", result["reply"])

    def test_shipping_price_does_not_repeat_product_subtotal(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "¿Cuál es el precio del despacho?",
                lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertNotIn("quote", result)
        self.assertNotIn("$230.400", result["reply"])
        self.assertIn("revisar su valor", result["reply"])

    def test_shipping_price_of_existing_order_does_not_repeat_subtotal(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        for question in ("¿Cuánto cuesta el despacho de los bordes?",
                         "¿Cuál es el total del despacho?",
                         "¿Me cotizas el despacho de mi pedido?"):
            with self.subTest(question=question), mock.patch.object(zero, "dispatch") as dispatch:
                result = zero.converse_result(
                    "losetaschile", question,
                    lead={"key": "test-lead"}, channel="whatsapp")
                dispatch.assert_not_called()
                self.assertNotIn("quote", result)
                self.assertNotIn("$230.400", result["reply"])
                self.assertIn("revisar su valor", result["reply"])

    def test_product_and_shipping_request_keeps_product_subtotal_separate(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        for question in ("¿Precio de los bordes y del despacho?",
                         "¿Cuánto cuesta el despacho y los bordes?"):
            with self.subTest(question=question), mock.patch.object(zero, "dispatch") as dispatch:
                result = zero.converse_result(
                    "losetaschile", question,
                    lead={"key": "test-lead"}, channel="whatsapp")
                dispatch.assert_not_called()
                self.assertIn("Productos: $230.400", result["reply"])
                self.assertIn("Despacho: por cotizar", result["reply"])

    def test_without_installation_keeps_requested_border_subtotal(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "¿Qué precio tienen los bordes rectos, sin instalación?",
                lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("Productos: $230.400", result["reply"])

    def test_long_chat_uses_confirmed_order_before_model_context_is_trimmed(self):
        memory = self.priced_memory()
        for index in range(30):
            memory.add_turn("losetaschile", "test-lead", "agent", f"Turno anterior {index}")
        agents = build_agents(mock=True)
        agents["CONCIERGE"].prompt_file = "concierge-whatsapp-local.md"
        zero = Zero(agents, memory=memory)
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "¿Me das el presupuesto?", lead={"key": "test-lead"},
                channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("Productos: $230.400", result["reply"])

    def test_delivery_questions_do_not_trigger_unsolicited_subtotal(self):
        self.assertFalse(wants_product_quote("¿Cuál es su dirección?"))
        self.assertFalse(wants_product_quote("¿Despachan a mi comuna?"))
        self.assertTrue(wants_product_quote("[location]"))
        self.assertTrue(wants_product_quote("Mi dirección es Avenida Central 123"))
        self.assertFalse(wants_product_quote("¿Qué valor tiene la instalación?"))
        self.assertFalse(wants_product_quote("¿Cuánto vale el despacho?"))

    def test_missing_corner_price_does_not_send_partial_subtotal(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory(False))
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "¿Me das el presupuesto?", lead={"key": "test-lead"},
                channel="whatsapp")
        dispatch.assert_not_called()
        self.assertNotIn("quote", result)
        self.assertNotIn("$216.000", result["reply"])

    def test_location_inbound_sends_product_subtotal(self):
        memory = self.priced_memory()
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic",
            "quote_mode": "manual"})
        crm = CRM(None)
        rec = crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
        for text in ("Mi piscina es rectangular de 6x3", "Borde recto con nariz"):
            memory.add_turn("losetaschile", rec["key"], "lead", text)
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web"})
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.handle_inbound(
                "56933333333", "[location]", to_phone_id="56911111111",
                whatsapp_chat_id="56933333333@c.us")
        dispatch.assert_not_called()
        self.assertEqual(result["delivery"]["status"], "sent")
        self.assertIn("Productos: $230.400", zero._deliver.call_args.args[3]["body"])
        self.assertIn("product_subtotal_accepted",
                      [event["event"] for event in rec.get("history", [])])


if __name__ == "__main__":
    unittest.main()
