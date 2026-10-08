import os
import unittest
from types import SimpleNamespace
from unittest import mock

from zero.agents import build_agents
from zero.crm import CRM
from zero.losetas_color import color_question
from zero.losetas_shipping import (DELIVERY_ADDRESS_PROMPT, DELIVERY_LOCATION_PROMPT,
                                   DELIVERY_POLL_ADDRESS, DELIVERY_POLL_LOCATION,
                                   SHIPPING_COVERAGE_REPLY, delivery_detail,
                                   shipping_delivery_followup, shipping_coverage_request)
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.pool_border import (border_plan, delegates_piece_calculation,
                              measurement_followup, normalize_pool_border_terms,
                              pool_border_models_reply,
                              unquoted_piece_count,
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

    def test_single_typo_in_bordes_still_asks_pool_measurements(self):
        for question in ("necesito pordes para mi piscina",
                         "quiero bordez para piscina", "busco bodes para mi piscina"):
            with self.subTest(question=question):
                self.assertTrue(wants_border_budget(question))
                plan, reply = border_plan(question, [])
                self.assertIsNone(plan)
                self.assertIn("largo y ancho en metros", reply)
        self.assertEqual(normalize_pool_border_terms("necesito pordes para mi piscina"),
                         "necesito bordes para mi piscina")

    def test_typo_request_routes_without_model_or_long_question_list(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result("losetaschile",
                                          "necesito pordes para mi piscina",
                                          lead={"key": "new-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("largo y ancho en metros", result["reply"])
        self.assertNotIn("comuna", result["reply"])

    def test_model_question_uses_active_pricing_and_pool_context(self):
        memory = self.priced_memory(include_tone=False)
        memory.set_client_pricing("losetaschile", {"currency": "CLP", "iva_rate": 0,
            "items": [
                {"id": "borde-recto-nariz-50x50", "name": "Borde recto con nariz 50x50", "unit_price": 6000},
                {"id": "borde-ballena-50x40", "name": "Borde ballena 50x40", "unit_price": 6800},
                {"id": "esquina-piscina-50x50", "name": "Esquina piscina 50x50", "unit_price": 3600},
            ]})
        memory.clients["losetaschile"]["conversations"]["test-lead"] = [
            {"role": "lead", "text": "necesito pordes para mi piscina"},
            {"role": "agent", "text": "¿Cuáles son las medidas de tu piscina?"},
        ]
        zero = Zero(build_agents(mock=True), memory=memory)
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result("losetaschile", "¿Qué modelos hay?",
                                          lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("Borde recto con nariz 50x50", result["reply"])
        self.assertIn("Borde ballena 50x40", result["reply"])
        self.assertIn("¿Cuál modelo te interesa?", result["reply"])
        self.assertNotIn("medidas de tu piscina", result["reply"])
        self.assertNotIn("$", result["reply"])
        self.assertIsNone(pool_border_models_reply("¿Qué modelos hay?", [],
                                                  {"items": []}))
        self.assertIsNone(pool_border_models_reply(
            "¿Qué modelos de pastelones hay?",
            [{"role": "lead", "text": "Necesito bordes para piscina"}],
            {"items": [{"id": "borde-ballena-50x40", "name": "Borde ballena 50x40"}]}))

    def test_simple_greeting_does_not_dispatch_model(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result("losetaschile", "hola buenas",
                                          lead={"key": "new-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertEqual(result["reply"], "¡Hola! ¿En qué puedo ayudarte?")

    def test_stefano_repeated_model_question_reaches_customer(self):
        memory = self.priced_memory(include_tone=False)
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        crm = CRM(None)
        rec = crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
        for role, text in (("lead", "necesito pordes para mi piscina"),
                           ("agent", "¿Cuáles son las medidas de tu piscina?"),
                           ("lead", "mi piscina mide 10 x 200 metros")):
            memory.add_turn("losetaschile", rec["key"], role, text)
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web",
                                                "id": "reply-1"})
        with mock.patch.object(zero, "dispatch") as dispatch:
            first = zero.handle_inbound("56933333333", "que modelos hay?",
                                        to_phone_id="56911111111",
                                        whatsapp_chat_id="56933333333@c.us")
            second = zero.handle_inbound("56933333333", "que modelos tienen?",
                                         to_phone_id="56911111111",
                                         whatsapp_chat_id="56933333333@c.us")
        dispatch.assert_not_called()
        self.assertEqual(first["delivery"]["status"], "sent")
        self.assertEqual(second["delivery"]["status"], "sent")
        self.assertIn("Borde recto con nariz", first["reply"])
        self.assertIn("Borde recto con nariz", second["reply"])
        self.assertNotIn("Necesito revisar", second["reply"])

    def test_outlier_pool_measurements_are_confirmed_before_other_questions(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory(include_tone=False))
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result("losetaschile", "mi piscina mide 10 x 200 metros",
                                          lead={"key": "new-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("confirmar el largo y ancho", result["reply"])
        self.assertNotIn("modelo", result["reply"])

    def test_unverified_payment_and_discount_are_not_invented(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory(include_tone=False))
        for question, expected in (("como se paga?", "formas de pago"),
                                   ("tienen algun descuento?", "descuento confirmado")):
            with self.subTest(question=question), mock.patch.object(zero, "dispatch") as dispatch:
                result = zero.converse_result("losetaschile", question,
                                              lead={"key": "new-lead"}, channel="whatsapp")
                dispatch.assert_not_called()
                self.assertIn(expected, result["reply"])

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

    def test_typo_quantity_question_never_asks_customer_to_calculate(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        zero = Zero(build_agents(mock=True), memory=memory)
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", "¿Cuántos bords para mi piscina?", channel="whatsapp")
        dispatch.assert_not_called()
        self.assertNotIn("divide", result["reply"])
        self.assertIn("largo y ancho", result["reply"])

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
        self.assertIn("compartir tu ubicación", result["reply"])
        self.assertTrue(result["delivery_poll"])

    def test_shipping_coverage_questions_use_one_verified_reply(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        for question in ("¿Tienen despachos?", "¿Despachan a Los Andes?",
                         "¿Hacen envíos a regiones?", "¿Hay flete a mi comuna?",
                         "le llegan a arika?"):
            with self.subTest(question=question), mock.patch.object(zero, "dispatch") as dispatch:
                result = zero.converse_result(
                    "losetaschile", question, lead={"key": "test-lead"},
                    channel="whatsapp")
                dispatch.assert_not_called()
                self.assertEqual(result["reply"], SHIPPING_COVERAGE_REPLY)
                self.assertTrue(result["delivery_poll"])
                self.assertNotIn("quote", result)
        self.assertFalse(shipping_coverage_request("¿Llegan los bordes dañados?"))

    def test_poll_choice_gets_one_short_instruction(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        for choice, expected in ((DELIVERY_POLL_LOCATION, DELIVERY_LOCATION_PROMPT),
                                 (DELIVERY_POLL_ADDRESS, DELIVERY_ADDRESS_PROMPT)):
            with self.subTest(choice=choice), mock.patch.object(zero, "dispatch") as dispatch:
                result = zero.converse_result(
                    "losetaschile", choice, lead={"key": "test-lead"},
                    channel="whatsapp")
                dispatch.assert_not_called()
                self.assertEqual(result["reply"], expected)
                self.assertNotIn("delivery_poll", result)

    def test_shared_location_is_in_internal_quote(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        location = "[location] https://www.google.com/maps?q=-33.610397,-70.643376"
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result(
                "losetaschile", location, lead={"key": "test-lead"},
                channel="whatsapp")
        dispatch.assert_not_called()
        self.assertEqual(result["quote"]["delivery_detail"],
                         "Ubicación compartida: https://www.google.com/maps?q=-33.610397,-70.643376")

    def test_delivery_prompt_accepts_city_and_written_address(self):
        history = [{"role": "agent", "text": SHIPPING_COVERAGE_REPLY}]
        self.assertTrue(shipping_delivery_followup("Los Andes", history))
        self.assertTrue(shipping_delivery_followup("¿Los Andes?", history))
        self.assertEqual(delivery_detail("Los Andes", history), "Destino indicado: Los Andes")
        self.assertEqual(delivery_detail("Mi comuna es La Florida", []),
                         "Dirección indicada: La Florida")
        self.assertEqual(delivery_detail("Av. Central 123", history),
                         "Destino indicado: Av. Central 123")
        self.assertFalse(shipping_delivery_followup("gris", history))
        self.assertTrue(shipping_delivery_followup(
            "Los Andes", [{"role": "agent", "text": DELIVERY_LOCATION_PROMPT}]))
        for question in ("¿Qué modelos hay?", "¿Tienen otros bordes?",
                         "necesito pordes para mi piscina", "gracias",
                         "Estoy en duda sobre los modelos"):
            with self.subTest(question=question):
                self.assertFalse(shipping_delivery_followup(question, history))
                self.assertIsNone(delivery_detail(question, history))

    def test_mixed_product_question_does_not_define_shipping_destination(self):
        history = [{"role": "agent", "text": (
            "Indícame el modelo, las medidas de tu piscina, las esquinas y "
            "la comuna de entrega para revisar despacho.")}]
        self.assertFalse(shipping_delivery_followup("¿Qué modelos hay?", history))
        self.assertFalse(shipping_delivery_followup("Los Andes", history))

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
                self.assertIn("compartir tu ubicación", result["reply"])

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
        self.assertIn("datos de entrega", acknowledgment)
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
