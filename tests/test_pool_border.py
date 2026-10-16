import os
import unittest
from types import SimpleNamespace
from unittest import mock

from zero.agents import build_agents
from zero.config import (LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE,
                         LOSETASCHILE_WHATSAPP_CATALOG_URL)
from zero.crm import CRM
from zero.losetas_color import color_question
from zero.losetas_polls import (DELIVERY_POLL_FACTORY_PICKUP,
                                DELIVERY_POLL_QUESTION, PRODUCT_POLL_QUESTION)
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
from zero.whatsapp_inbound import parse_inbound as parse_meta


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
        memory.add_turn("losetaschile", "test-lead", "agent", DELIVERY_ADDRESS_PROMPT)
        memory.add_turn("losetaschile", "test-lead", "lead", "Mi comuna es Ñuñoa")
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
        self.assertIn("¿Qué color prefieres?", result["reply"])
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
            catalog_result = zero.converse_result(
                "losetaschile", "¿Me mandas el catálogo?",
                lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertEqual(catalog_result["intent"], "catalog")
        self.assertEqual(catalog_result["reply"], LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE)
        mixed_result = zero.converse_result(
            "losetaschile", "¿Tienen catálogo y hacen despacho?",
            lead={"key": "test-lead"}, channel="whatsapp")
        self.assertEqual(mixed_result["reply"], LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE)
        self.assertNotIn("delivery_poll", mixed_result)
        quote_result = zero.converse_result(
            "losetaschile", "Quisiera cotizar bordes de piscina, ¿tienes catálogo?",
            lead={"key": "test-lead"}, channel="whatsapp")
        self.assertEqual(quote_result["intent"], "catalog")
        self.assertEqual(quote_result["reply"], "Catálogo Bordes de Piscina")
        self.assertEqual(quote_result["catalog_document"]["category"], "bordes")
        self.assertNotIn("quote", quote_result)
        self.assertIn("Borde recto con nariz 50x50", result["reply"])
        self.assertIn("Borde ballena 50x40", result["reply"])
        self.assertIn("¿Cuál modelo te interesa?", result["reply"])
        self.assertIn(LOSETASCHILE_WHATSAPP_CATALOG_URL, result["reply"])
        self.assertNotIn("medidas de tu piscina", result["reply"])
        self.assertNotIn("$", result["reply"])
        first_contact = pool_border_models_reply("¿Qué modelos hay?", [], {"items": []})
        self.assertIn(LOSETASCHILE_WHATSAPP_CATALOG_URL, first_contact)
        self.assertIn("¿Qué producto buscas?", first_contact)
        self.assertIsNone(pool_border_models_reply("¿Qué modelos de pago hay?", [],
                                                  {"items": []}))
        no_priced_models = pool_border_models_reply(
            "¿Qué modelos hay?", [{"role": "lead", "text": "Necesito bordes de piscina"}],
            {"items": []})
        self.assertIn(LOSETASCHILE_WHATSAPP_CATALOG_URL, no_priced_models)
        self.assertNotIn("precio", no_priced_models)
        other_borders = pool_border_models_reply(
            "¿Qué bordes tienen?", [], {"items": [
                {"id": "borde-ballena-50x40", "name": "Borde ballena 50x40"}]})
        self.assertIn("Borde ballena 50x40", other_borders)
        self.assertIn(LOSETASCHILE_WHATSAPP_CATALOG_URL, other_borders)
        for request in ("¿Tienen catálogo?", "¿Me mandas el catálogo?",
                        "Catalogo", "Catálogo", "catálogo!",
                        "Me puedes mandar el catálogo de bordes",
                        "Podrías mandarme el catálogo de bordes",
                        "Envíame el catálogo de bordes de piscina",
                        "Solo envía el catálogo",
                        "No me mandes precios, solo el catálogo por favor",
                        "No me mandes presupuesto, mándame el catálogo",
                        "Todavía no me mandes presupuesto; envíame el catálogo",
                        "Quisiera cotizar bordes de piscina, ¿tienes catalogo?"):
            with self.subTest(request=request):
                catalog_reply = pool_border_models_reply(request, [], {"items": [
                    {"id": "borde-ballena-50x40", "name": "Borde ballena 50x40"}]})
                self.assertEqual(catalog_reply, LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE)
        for mention in ("Ya vi el catálogo, quiero cotizar", "Ya vi el catálogo?",
                        "¿Está actualizado el catálogo?", "¿Ese es su catálogo?",
                        "No quiero ver el catálogo", "No me mandes el catálogo",
                        "No me mandes catálogos por favor",
                        "No quiero catálogos por favor",
                        "¿Tienen catálogo? No me mandes nada todavía",
                        "¿Tienen catálogo? Solo quería saber, no me envíes el enlace",
                        "Quiero ver el catálogo pero todavía no lo mandes",
                        "Envíame el catálogo, pero no ahora",
                        "Quiero ver el catálogo, pero no me lo mandes hasta mañana",
                        "No me mandes catálogo, ¿qué modelos hay?"):
            with self.subTest(mention=mention):
                self.assertIsNone(pool_border_models_reply(mention, [], {"items": []}))
        self.assertIsNone(pool_border_models_reply(
            "¿Qué modelos de pastelones hay?",
            [{"role": "lead", "text": "Necesito bordes para piscina"}],
            {"items": [{"id": "borde-ballena-50x40", "name": "Borde ballena 50x40"}]}))

    def test_category_catalogs_route_to_separate_documents(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        borders = zero.converse_result("losetaschile", "Envíame el catálogo de bordes",
                                       channel="whatsapp")
        pavers = zero.converse_result("losetaschile", "Catálogo de pastelones",
                                      channel="whatsapp")
        generic = zero.converse_result("losetaschile", "Catálogo", channel="whatsapp")
        self.assertEqual(borders["reply"], "Catálogo Bordes de Piscina")
        self.assertEqual(pavers["reply"], "Catálogo Pastelones")
        self.assertEqual(borders["catalog_document"]["category"], "bordes")
        self.assertEqual(pavers["catalog_document"]["category"], "pastelones")
        self.assertEqual(borders["catalog_document"]["pricing"]["items"][0]["unit_price"], 6000)
        self.assertEqual(generic["reply"], LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE)
        self.assertNotIn("catalog_document", generic)
        postponed = zero.converse_result(
            "losetaschile", "Envíame el catálogo de bordes, pero no ahora",
            channel="whatsapp")
        self.assertNotIn("catalog_document", postponed)

    def test_recent_catalog_messages_route_to_documents_despite_typo(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        for message, category in (("Catalogo bordes", "bordes"),
                                  ("Cagalogo de pastelones", "pastelones")):
            with self.subTest(message=message):
                result = zero.converse_result("losetaschile", message,
                                              channel="whatsapp")
                self.assertEqual(result["catalog_document"]["category"], category)
        postponed = zero.converse_result(
            "losetaschile", "Cagalogo de pastelones, pero no ahora",
            channel="whatsapp")
        self.assertNotIn("catalog_document", postponed)

    def test_category_catalog_waits_when_customer_postpones_or_only_asks_availability(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        for message in ("Mándame el catálogo de bordes mañana",
                        "¿Tienen catálogo de bordes? No me lo envíen todavía",
                        "No tienen catálogo de bordes, ¿verdad?"):
            with self.subTest(message=message):
                result = zero.converse_result("losetaschile", message,
                                              channel="whatsapp")
                self.assertNotIn("catalog_document", result)

    def test_category_catalog_uncertain_document_result_stops_without_text(self):
        memory = self.priced_memory()
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        zero = Zero(build_agents(mock=True), memory=memory, crm=CRM(None))
        zero._deliver = mock.Mock()
        with mock.patch("zero.whatsapp_web.send_catalog_document",
                        side_effect=RuntimeError("resultado incierto")) as send_document:
            result = zero.handle_inbound(
                "56933333333", "Envíame el catálogo de bordes",
                to_phone_id="56911111111", whatsapp_chat_id="56933333333@c.us")
        send_document.assert_called_once()
        zero._deliver.assert_not_called()
        self.assertEqual(result["delivery"]["status"], "error")
        self.assertIn("resultado incierto", result["delivery"]["error"])

    def test_category_catalog_sends_one_document_without_text_reply(self):
        memory = self.priced_memory()
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        zero = Zero(build_agents(mock=True), memory=memory, crm=CRM(None))
        zero._deliver = mock.Mock()
        with mock.patch("zero.whatsapp_web.send_catalog_document",
                        return_value={"id": "catalog-1", "ack": 0}) as send_document:
            result = zero.handle_inbound(
                "56933333333", "Envíame el catálogo de pastelones",
                to_phone_id="56911111111", whatsapp_chat_id="56933333333@c.us")
        send_document.assert_called_once()
        zero._deliver.assert_not_called()
        self.assertEqual(result["delivery"]["status"], "sent")
        self.assertEqual(result["delivery"]["id"], "catalog-1")
        self.assertEqual(send_document.call_args.args[3], "pastelones")

    def test_simple_greeting_does_not_dispatch_model(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        with mock.patch("zero.orchestrator.whatsapp_greeting", return_value="Buenas noches"), \
             mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result("losetaschile", "hola buenas",
                                          lead={"key": "new-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertEqual(result["reply"], "¡Buenas noches! ¿En qué puedo ayudarte?")

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
        self.assertIn(LOSETASCHILE_WHATSAPP_CATALOG_URL, first["reply"])
        self.assertIn("\n\n", first["reply"])
        self.assertIn(LOSETASCHILE_WHATSAPP_CATALOG_URL, second["reply"])
        self.assertIn(LOSETASCHILE_WHATSAPP_CATALOG_URL,
                      zero._deliver.call_args.args[3]["body"])
        self.assertNotIn("Necesito revisar", second["reply"])

    def test_repeated_catalog_request_sends_only_link(self):
        for question in ("Catalogo", "¿Tienen catálogo y hacen despacho?",
                         "¿Cuánto cuesta el despacho y tienen catálogo?"):
            with self.subTest(question=question):
                memory = self.priced_memory(include_tone=False)
                memory.set_client_agent_profile("losetaschile", {
                    "whatsapp_number": "56911111111", "response_mode": "automatic"})
                crm = CRM(None)
                crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
                zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
                zero._deliver = mock.Mock(return_value={
                    "status": "sent", "via": "whatsapp_web", "id": "reply-1"})
                with mock.patch("zero.whatsapp_web.send_delivery_poll") as send_poll, \
                     mock.patch.object(zero, "dispatch") as dispatch:
                    first = zero.handle_inbound(
                        "56933333333", question, to_phone_id="56911111111",
                        whatsapp_chat_id="56933333333@c.us")
                    second = zero.handle_inbound(
                        "56933333333", question, to_phone_id="56911111111",
                        whatsapp_chat_id="56933333333@c.us")
                dispatch.assert_not_called()
                send_poll.assert_not_called()
                for result in (first, second):
                    self.assertEqual(result["delivery"]["status"], "sent")
                    self.assertEqual(result["reply"], LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE)
                    self.assertFalse(result.get("manual_review", False))

    def test_catalog_request_wins_over_pending_offer(self):
        memory = self.priced_memory(include_tone=False)
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic",
            "offer_flow": True})
        crm = CRM(None)
        rec = crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
        memory.set_pending_offer("losetaschile", rec["key"], "summary")
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={
            "status": "sent", "via": "whatsapp_web", "id": "reply-1"})
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.handle_inbound(
                "56933333333", "Sí, me mandas el catálogo?",
                to_phone_id="56911111111", whatsapp_chat_id="56933333333@c.us")
        dispatch.assert_not_called()
        self.assertEqual(result["intent"], "catalog")
        self.assertEqual(result["reply"], LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE)
        self.assertEqual(zero._deliver.call_args.args[3]["body"],
                         LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE)
        self.assertIsNotNone(memory.get_pending_offer("losetaschile", rec["key"]))

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
        self.assertIn("¿Qué color prefieres?", result["reply"])
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

    def test_generic_pastelon_request_sends_catalog_and_asks_color(self):
        zero = Zero(build_agents(mock=True), memory=self.priced_memory())
        for request in ("Necesito pastelones", "Hola, necesito pastelones",
                        "Necesito pastelones para mi piscina de 6x3",
                        "Necesito pastelones de 50x50", "Quiero precio de pastelones"):
            with self.subTest(request=request), mock.patch.object(zero, "dispatch") as dispatch:
                result = zero.converse_result(
                    "losetaschile", request,
                    lead={"key": "test-lead"}, channel="whatsapp")
                dispatch.assert_not_called()
                self.assertEqual(result["catalog_document"]["category"], "pastelones")
                self.assertEqual(result["customer_poll"], "color")
                self.assertIn("¿Qué color prefieres?", result["reply"])
                self.assertNotIn("necesitarás", result["reply"].lower())

    def test_pastelon_delivery_waits_for_both_model_and_area(self):
        memory = self.priced_memory()
        memory.clients["losetaschile"]["conversations"]["test-lead"] = [
            {"role": "agent", "text": PRODUCT_POLL_QUESTION},
            {"role": "lead", "text": "Pastelones"},
            {"role": "agent", "text": color_question()},
            {"role": "lead", "text": "beige"},
            {"role": "agent", "text": "¿Qué modelo del catálogo te interesa y cuántos m² necesitas cubrir?"},
        ]
        zero = Zero(build_agents(mock=True), memory=memory)
        with mock.patch.object(zero, "dispatch") as dispatch:
            only_model = zero.converse_result("losetaschile", "Laja española",
                                               lead={"key": "test-lead"}, channel="whatsapp")
            memory.add_turn("losetaschile", "test-lead", "lead", "Laja española")
            memory.add_turn("losetaschile", "test-lead", "agent", only_model["reply"])
            both = zero.converse_result("losetaschile", "18 m²",
                                        lead={"key": "test-lead"}, channel="whatsapp")
            memory.add_turn("losetaschile", "test-lead", "lead", "18 m²")
            memory.add_turn("losetaschile", "test-lead", "agent", DELIVERY_POLL_QUESTION)
            pickup = zero.converse_result("losetaschile", DELIVERY_POLL_FACTORY_PICKUP,
                                          lead={"key": "test-lead"}, channel="whatsapp")
        dispatch.assert_not_called()
        self.assertIn("¿Cuántos m²", only_model["reply"])
        self.assertNotIn("delivery_poll", only_model)
        self.assertTrue(both.get("delivery_poll"))
        self.assertIn("confirmar el tamaño", pickup["reply"])

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
        address_poll_history = [{"role": "agent", "text": DELIVERY_ADDRESS_PROMPT}]
        self.assertTrue(shipping_delivery_followup("Av. Central 123", address_poll_history))
        self.assertEqual(delivery_detail("Av. Central 123", address_poll_history),
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
        meta = {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "56911111111"},
            "messages": [{"from": "56933333333", "type": "location",
                          "location": {"latitude": -33.610397,
                                       "longitude": -70.643376}}],
        }}]}]}
        inbound = parse_meta(meta)[0]
        with mock.patch.object(zero, "dispatch") as dispatch, \
                mock.patch("zero.whatsapp_web.send_group_text",
                           return_value={"id": "internal-1", "ack": 0}) as send_group, \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": "123456789@g.us"}):
            result = zero.handle_inbound(
                inbound["from"], inbound["text"], to_phone_id=inbound["to_phone_id"],
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
        self.assertIn("https://www.google.com/maps?q=-33.610397,-70.643376", internal)
        self.assertIn("*Total productos: $230.400*", internal)

    def test_pastelon_selection_does_not_create_budget_without_model_and_area(self):
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
        with mock.patch("zero.whatsapp_web.send_catalog_document",
                        return_value={"id": "document-1", "ack": 0}), \
             mock.patch("zero.whatsapp_web.send_catalog_image",
                        return_value={"id": "image-1", "ack": 0}), \
             mock.patch("zero.whatsapp_web.send_choice_poll",
                        return_value={"status": "sent", "id": "poll-1"}) as send_poll, \
             mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": ""}):
            result = zero.handle_inbound(
                "56933333333", "Necesito pastelones", to_phone_id="56911111111",
                whatsapp_chat_id="56933333333@c.us")
        self.assertEqual(result["delivery"]["id"], "image-1")
        self.assertEqual(send_poll.call_args.args[-1], "color")
        zero._deliver.assert_not_called()

    def test_catalog_request_sends_only_link_without_budget(self):
        memory = self.priced_memory()
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        crm = CRM(None)
        rec = crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
        for text in ("Mi piscina es rectangular de 6x3", "Borde recto con nariz"):
            memory.add_turn("losetaschile", rec["key"], "lead", text)
        memory.add_turn("losetaschile", rec["key"], "agent", color_question())
        memory.add_turn("losetaschile", rec["key"], "lead", "beige")
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={
            "status": "sent", "via": "whatsapp_web", "id": "ack-1"})
        with mock.patch("zero.whatsapp_web.send_group_text") as send_group, \
             mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": "123456789@g.us"}), \
             mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.handle_inbound(
                "56933333333", "Me mandas el catálogo y el presupuesto?",
                to_phone_id="56911111111", whatsapp_chat_id="56933333333@c.us")
        dispatch.assert_not_called()
        send_group.assert_not_called()
        self.assertEqual(result["delivery"]["status"], "sent")
        self.assertEqual(result["reply"], LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE)
        self.assertEqual(zero._deliver.call_args.args[3]["body"],
                         LOSETASCHILE_WHATSAPP_CATALOG_MESSAGE)
        self.assertNotIn("customer_ack", result)

    def test_pastelon_catalog_does_not_submit_budget_before_model_and_area(self):
        memory = self.priced_memory()
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        crm = CRM(None)
        rec = crm.upsert("losetaschile", {"phone": "56933333333", "source": "test"})
        for turn in memory.get_conversation("losetaschile", "test-lead"):
            memory.add_turn("losetaschile", rec["key"], turn["role"], turn["text"])
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={"status": "error", "error": "outcome uncertain"})
        with mock.patch("zero.whatsapp_web.send_catalog_document",
                        return_value={"id": "document-1", "ack": 0}), \
                mock.patch("zero.whatsapp_web.send_catalog_image",
                        return_value={"id": "image-1", "ack": 0}), \
                mock.patch("zero.whatsapp_web.send_choice_poll",
                        return_value={"status": "sent", "id": "poll-1"}) as send_poll, \
                mock.patch("zero.whatsapp_web.send_group_text") as send_group, \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": "123456789@g.us"}):
            result = zero.handle_inbound(
                "56933333333", "Necesito pastelones", to_phone_id="56911111111",
                whatsapp_chat_id="56933333333@c.us")
        send_group.assert_not_called()
        self.assertEqual(result["delivery"]["id"], "image-1")
        self.assertEqual(send_poll.call_args.args[-1], "color")
        zero._deliver.assert_not_called()

    def test_color_image_then_pastelon_choice_asks_for_model_and_area(self):
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
        with mock.patch("zero.whatsapp_web.send_catalog_document",
                        return_value={"id": "document-1", "ack": 0}) as send_document, \
                mock.patch("zero.whatsapp_web.send_catalog_image",
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
        self.assertEqual(send_document.call_args.args[3], "pastelones")
        self.assertIn("gama-bordes-piscina.jpeg", send_image.call_args.args)
        self.assertEqual(second["delivery"]["status"], "sent")
        self.assertIn("modelo", second["reply"])
        self.assertIn("m²", second["reply"])
        send_group.assert_not_called()


if __name__ == "__main__":
    unittest.main()
