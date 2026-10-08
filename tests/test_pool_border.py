import os
import unittest
from types import SimpleNamespace
from unittest import mock

from zero.agents import build_agents
from zero.crm import CRM
from zero.losetas_color import color_question
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.pool_border import (border_plan, delegates_piece_calculation,
                              measurement_followup, unquoted_piece_count,
                              wants_border_budget,
                              wants_product_quote)


class PoolBorderCountTest(unittest.TestCase):
    def priced_memory(self, include_corner=True, include_tone=True):
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
        if include_tone:
            memory.add_turn("losetaschile", "test-lead", "agent", color_question())
            memory.add_turn("losetaschile", "test-lead", "lead", "beige")
        return memory

    def test_asks_for_tone_before_budget(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory(include_tone=False))
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "Necesito pastelones",
                lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("¿Cuál prefieres?", result["reply"])
        self.assertIn("media_asset", result)
        self.assertNotIn("quote", result)

    def test_confirmed_six_by_three_rule(self):
        history = [
            {"role": "lead", "text": "Es rectangular de 6x3"},
            {"role": "lead", "text": "Borde recto con nariz"},
        ]
        plan, _ = border_plan(
            "¿Cuántos pastelones caben en una piscina de 6x3 rectangular?", history)
        self.assertEqual((plan["straight"], plan["corners"]), (36, 4))

    def test_newer_measurement_replaces_old_one(self):
        history = [
            {"role": "lead", "text": "Mi piscina mide 7x3"},
            {"role": "lead", "text": "Es rectangular de 6x3"},
            {"role": "lead", "text": "Borde recto con nariz"},
        ]
        plan, _ = border_plan("¿Cuántos bordes necesito?", history)
        self.assertEqual(plan["straight"], 36)

    def test_product_size_does_not_replace_pool_size(self):
        history = [
            {"role": "lead", "text": "Mi piscina es rectangular de 6x3"},
            {"role": "lead", "text": "Borde recto con nariz"},
        ]
        plan, _ = border_plan("¿Cuánto cuestan los bordes rectos 50x50?", history)
        self.assertEqual((plan["straight"], plan["corners"]), (36, 4))

    def test_rejected_pastelones_do_not_trigger_order_budget(self):
        self.assertFalse(wants_border_budget("No quiero pastelones"))
        self.assertFalse(wants_border_budget("No quiero pastelones, ¿cuánto cuestan?"))

    def test_pool_border_request_triggers_color_flow(self):
        self.assertTrue(wants_border_budget("Necesito bordes de piscina"))
        self.assertTrue(wants_border_budget("Busco bordes para mi piscina"))

    def test_pool_order_asks_measurements_before_model(self):
        plan, question = border_plan("Necesito bordes de piscina", [])
        self.assertIsNone(plan)
        self.assertIn("medidas de tu piscina", question)
        self.assertIn("largo y ancho en metros", question)
        self.assertNotIn("modelo", question)

    def test_measurement_answer_continues_without_model(self):
        memory = self.priced_memory(include_tone=False)
        memory.clients["losetaschile"]["conversations"]["test-lead"] = [
            {"role": "lead", "text": "Necesito bordes de piscina rectangular"},
            {"role": "lead", "text": "Borde recto con nariz"},
            {"role": "agent", "text": "¿Cuáles son las medidas de tu piscina? Necesito largo y ancho en metros."},
        ]
        zero = Zero(build_agents(mock=True), memory=memory)
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result("losetaschile", "6x3 m",
                                          lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("¿Cuál prefieres?", result["reply"])
        self.assertIn("media_asset", result)

    def test_measurements_already_supplied_are_not_requested_again(self):
        plan, question = border_plan("Necesito bordes de piscina rectangular de 6x3 m", [])
        self.assertIsNone(plan)
        self.assertIn("modelo", question)
        self.assertNotIn("medidas", question)

    def test_unknown_product_asks_instead_of_guessing(self):
        plan, clarification = border_plan("¿Cuántos pastelones para piscina 6x3?", [])
        self.assertIsNone(plan)
        self.assertIn("Qué modelo", clarification)

    def test_non_half_metre_sides_need_review(self):
        plan, clarification = border_plan("¿Cuántos bordes para piscina rectangular 6,2x3?",
                                          [{"role": "lead", "text": "Borde recto con nariz"}])
        self.assertIsNone(plan)
        self.assertIn("confirmar", clarification)

    def test_conversation_uses_verified_count_without_model(self):
        memory = self.priced_memory()
        memory.add_turn("losetaschile", "test-lead", "lead", "Borde recto con nariz")
        zero = Zero(build_agents(mock=True), memory=memory)
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "¿Cuántos pastelones para una piscina rectangular de 6x3?",
                lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("*Presupuesto de productos*", result["reply"])
        self.assertIn("*Total productos: $230.400*", result["reply"])
        self.assertNotIn("necesitarás", result["reply"].lower())

    def test_generic_pastelon_request_uses_confirmed_order_budget(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        for request in ("Necesito pastelones", "Hola, necesito pastelones",
                        "Necesito pastelones para mi piscina de 6x3",
                        "Necesito pastelones de 50x50", "Quiero precio de pastelones"):
            with self.subTest(request=request), mock.patch.object(zero, "dispatch") as dispatch:
                result = zero.converse_result(
                    "losetaschile", request,
                    lead={"key": "test-lead"}, channel="whatsapp")
                dispatch.assert_not_called()
                self.assertIn("*Presupuesto de productos*", result["reply"])
                self.assertIn("*Total productos: $230.400*", result["reply"])
                self.assertNotIn("necesitarás", result["reply"].lower())

    def test_negated_product_does_not_get_straight_border_count(self):
        plan, _ = border_plan(
            "No quiero borde recto con nariz; ¿cuántos pastelones para piscina rectangular 6x3?", [])
        self.assertIsNone(plan)

    def test_oval_pool_does_not_get_rectangle_count(self):
        plan, _ = border_plan(
            "¿Cuántos bordes rectos con nariz para piscina ovalada de 6x3?", [])
        self.assertIsNone(plan)

    def test_rectangle_shape_must_be_confirmed(self):
        plan, clarification = border_plan(
            "¿Cuántos bordes rectos con nariz para piscina 6x3?", [])
        self.assertIsNone(plan)
        self.assertIn("rectangular", clarification)

    def test_latest_shape_overrides_old_rectangle(self):
        history = [
            {"role": "lead", "text": "Mi piscina es rectangular 6x3"},
            {"role": "lead", "text": "Perdón, es ovalada 6x3"},
            {"role": "lead", "text": "Borde recto con nariz"},
        ]
        plan, _ = border_plan("¿Cuántos bordes necesito?", history)
        self.assertIsNone(plan)

    def test_latest_product_overrides_old_straight_border(self):
        history = [
            {"role": "lead", "text": "Borde recto con nariz"},
            {"role": "lead", "text": "Mejor quiero borde ballena"},
            {"role": "lead", "text": "Mi piscina es rectangular 6x3"},
        ]
        plan, _ = border_plan("¿Cuántos bordes necesito?", history)
        self.assertIsNone(plan)

    def test_plural_other_product_overrides_old_straight_border(self):
        history = [
            {"role": "lead", "text": "Borde recto con nariz"},
            {"role": "lead", "text": "Ahora quiero bordes ballena"},
            {"role": "lead", "text": "Mi piscina es rectangular 6x3"},
        ]
        plan, _ = border_plan("¿Cuántos bordes necesito?", history)
        self.assertIsNone(plan)

    def test_dimensions_in_feet_are_not_treated_as_metres(self):
        plan, clarification = border_plan(
            "¿Cuántos bordes rectos con nariz para piscina rectangular 6x3 pies?", [])
        self.assertIsNone(plan)
        self.assertIn("metros", clarification)

    def test_real_followup_with_typo_uses_previous_pool_details(self):
        history = [
            {"role": "lead", "text": "Es de 6x3"},
            {"role": "lead", "text": "Borde recto con nariz"},
            {"role": "lead", "text": "Si cuantos pastelones caben en una piscina de 6x3 rectangular?"},
        ]
        plan, _ = border_plan(
            "Cuantos bordea necesito entonces para es piscina?", history)
        self.assertEqual((plan["straight"], plan["corners"]), (36, 4))

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

    def test_unquoted_model_piece_count_is_not_delivered(self):
        memory = self.priced_memory()
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        crm = CRM(None)
        crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web"})
        draft = SimpleNamespace(result={"reply": "Necesitas alrededor de 18 pastelones.",
                                        "intent": "info"}, status="ok")
        with mock.patch.object(zero, "dispatch", return_value=draft):
            result = zero.handle_inbound(
                "56933333333", "Pastelones?", to_phone_id="56911111111",
                whatsapp_chat_id="56933333333@c.us")
        self.assertTrue(result["manual_review"])
        self.assertNotIn("18 pastelones", zero._deliver.call_args.args[3]["body"])
        self.assertTrue(unquoted_piece_count("alrededor de 18 pastelones", None))
        self.assertTrue(unquoted_piece_count("alrededor de 18 unidades", None))
        self.assertTrue(unquoted_piece_count("unos dieciocho pastelones", None))
        self.assertFalse(unquoted_piece_count("36 bordes", {"total": 230400}))

    def test_location_completes_product_subtotal_without_shipping(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "[location]", lead={"key": "test-lead"},
                channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("Borde recto con nariz 50x50: 36 × $6.000 = $216.000", result["reply"])
        self.assertIn("Esquina piscina 50x50: 4 × $3.600 = $14.400", result["reply"])
        self.assertIn("*Total productos: $230.400*", result["reply"])
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
        self.assertIn("*Total productos: $230.400*", result["reply"])

    def test_plural_price_question_uses_confirmed_order(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "¿Cuánto cuestan los bordes?",
                lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("*Total productos: $230.400*", result["reply"])

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
                self.assertIn("*Total productos: $230.400*", result["reply"])
                self.assertIn("Despacho: por cotizar", result["reply"])

    def test_without_installation_keeps_requested_border_subtotal(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "¿Qué precio tienen los bordes rectos, sin instalación?",
                lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("*Total productos: $230.400*", result["reply"])

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
        self.assertIn("*Total productos: $230.400*", result["reply"])

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

    def test_location_inbound_sends_budget_to_group_for_manual_review(self):
        memory = self.priced_memory()
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic",
            "quote_mode": "manual"})
        crm = CRM(None)
        rec = crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
        for text in ("Mi piscina es rectangular de 6x3", "Borde recto con nariz"):
            memory.add_turn("losetaschile", rec["key"], "lead", text)
        memory.add_turn("losetaschile", rec["key"], "agent", color_question())
        memory.add_turn("losetaschile", rec["key"], "lead", "beige")
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web",
                                                "id": "ack-1"})
        with mock.patch.object(zero, "dispatch") as dispatch, \
                mock.patch("zero.whatsapp_web.send_group_text",
                           return_value={"id": "internal-1", "ack": 0}) as send_group, \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": "123456789@g.us"}):
            result = zero.handle_inbound(
                "56933333333", "[location]", to_phone_id="56911111111",
                profile_name="Diego", whatsapp_chat_id="56933333333@c.us")
        dispatch.assert_not_called()
        self.assertEqual(result["delivery"]["status"], "accepted")
        self.assertTrue(result["manual_review"])
        self.assertEqual(result["customer_ack"]["id"], "ack-1")
        acknowledgment = zero._deliver.call_args.args[3]["body"]
        self.assertIn("color beige", acknowledgment)
        self.assertNotIn("$", acknowledgment)
        self.assertEqual(send_group.call_args.args[:3],
                         ("losetaschile", "56911111111", "123456789@g.us"))
        internal = send_group.call_args.args[3]
        self.assertIn("Cliente: Diego\nNúmero: +56933333333", internal)
        self.assertIn("Color indicado por cliente: beige", internal)
        self.assertIn("*Total productos: $230.400*", internal)

    def test_budget_with_no_group_is_held_and_not_sent_to_customer(self):
        memory = self.priced_memory()
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        crm = CRM(None)
        rec = crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
        for turn in memory.get_conversation("losetaschile", "test-lead"):
            memory.add_turn("losetaschile", rec["key"], turn["role"], turn["text"])
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web",
                                                "id": "ack-1"})
        with mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": ""}):
            result = zero.handle_inbound(
                "56933333333", "Necesito pastelones", to_phone_id="56911111111",
                whatsapp_chat_id="56933333333@c.us")
        self.assertEqual(result["delivery"]["status"], "error")
        self.assertFalse(result["manual_review"])
        zero._deliver.assert_not_called()

    def test_ack_failure_flags_review_after_group_accepts_budget(self):
        memory = self.priced_memory()
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        crm = CRM(None)
        rec = crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
        for turn in memory.get_conversation("losetaschile", "test-lead"):
            memory.add_turn("losetaschile", rec["key"], turn["role"], turn["text"])
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={"status": "error", "error": "outcome uncertain"})
        with mock.patch("zero.whatsapp_web.send_group_text",
                        return_value={"id": "group-1", "ack": 0}) as send_group, \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": "123456789@g.us"}):
            result = zero.handle_inbound(
                "56933333333", "Necesito pastelones", to_phone_id="56911111111",
                whatsapp_chat_id="56933333333@c.us")
        self.assertEqual(send_group.call_count, 1)
        self.assertEqual(result["delivery"]["status"], "error")
        self.assertFalse(result["manual_review"])
        self.assertNotIn("$", zero._deliver.call_args.args[3]["body"])
        self.assertTrue(memory.clients["losetaschile"]["internal_budget_signatures"])

    def test_color_image_then_choice_routes_budget_only_to_group(self):
        memory = self.priced_memory(include_tone=False)
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        crm = CRM(None)
        rec = crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
        for turn in memory.get_conversation("losetaschile", "test-lead"):
            memory.add_turn("losetaschile", rec["key"], turn["role"], turn["text"])
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web",
                                                "id": "ack-1"})
        with mock.patch("zero.whatsapp_web.send_catalog_image",
                        return_value={"id": "image-1", "ack": 0}) as send_image, \
                mock.patch("zero.whatsapp_web.send_group_text",
                           return_value={"id": "group-1", "ack": 0}) as send_group, \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": "123456789@g.us"}):
            first = zero.handle_inbound(
                "56933333333", "Necesito pastelones", to_phone_id="56911111111",
                profile_name="Diego", whatsapp_chat_id="56933333333@c.us")
            second = zero.handle_inbound(
                "56933333333", "beige", to_phone_id="56911111111",
                whatsapp_chat_id="56933333333@c.us")
        self.assertEqual(first["delivery"]["id"], "image-1")
        self.assertIn("gama-bordes-piscina.jpeg", send_image.call_args.args)
        self.assertEqual(second["delivery"]["id"], "group-1")
        self.assertTrue(second["manual_review"])
        self.assertEqual(second["customer_ack"]["id"], "ack-1")
        self.assertIn("color beige", zero._deliver.call_args.args[3]["body"])
        self.assertNotIn("$", zero._deliver.call_args.args[3]["body"])
        self.assertIn("Color indicado por cliente: beige", send_group.call_args.args[3])
        self.assertIn("Cliente: Diego\nNúmero: +56933333333", send_group.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
