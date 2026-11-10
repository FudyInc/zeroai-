"""A complete paver order reaches the review group, and repeats do not undo it.

The chat is a real one, anonymized: pastelones, 40 m², Gregoriano, amarillo, despacho
by shared location, the location sent twice, then «¿cómo me llamo?».
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from zero import config
from zero.agents import build_agents
from zero.crm import CRM
from zero.losetas_budget import format_paver_order_draft
from zero.losetas_polls import (PAVER_MODEL_OPTIONS, PAVER_REVIEW_SUFFIX,
                                paver_review_sentence, paver_review_status)
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.whatsapp_inbound import parse_inbound as parse_meta

PHONE = "56900000001"
BOT = "56911111111"
GROUP = "123456789@g.us"
CHAT = PHONE + "@c.us"
LOCATION = parse_meta({"entry": [{"changes": [{"value": {
    "metadata": {"phone_number_id": BOT},
    "messages": [{"from": PHONE, "type": "location",
                  "location": {"latitude": -33.5, "longitude": -70.6}}]}}]}]})[0]["text"]
REVIEW_SENTENCE = "Tu presupuesto de 40 m² de Gregoriano amarillo con despacho está en revisión"


def _chat(priced=True):
    memory = SessionMemory(None)
    memory.register_client("losetaschile", "STARTER")
    memory.set_client_agent_profile("losetaschile", {
        "whatsapp_number": BOT, "response_mode": "automatic"})
    if priced:
        memory.set_client_pricing("losetaschile", {"currency": "CLP", "iva_rate": 0, "items": [
            {"id": "pastelones-40x40", "name": "Pastelón 40x40", "unit_price": 1600,
             "unit": "unidad"}]})
    crm = CRM(None)
    crm.upsert("losetaschile", {"phone": PHONE, "source": "test"})
    zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
    zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web", "id": "t"})
    return zero


class PaverOrderReviewTest(unittest.TestCase):
    def run_chat(self, messages, priced=True, model="Gregoriano"):
        zero = _chat(priced)
        results, bodies = [], []
        with mock.patch("zero.whatsapp_web.send_catalog_document",
                        return_value={"id": "document-1", "ack": 0}), \
                mock.patch("zero.whatsapp_web.send_group_text",
                           return_value={"id": "group-1", "ack": 0}) as send_group, \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": GROUP}), \
                mock.patch.object(zero, "dispatch"):
            for text in messages:
                results.append(zero.handle_inbound(
                    PHONE, text.replace("{model}", model), to_phone_id=BOT, profile_name="Cliente Uno",
                    whatsapp_chat_id=CHAT))
                bodies.append(zero._deliver.call_args.args[3]["body"])
        self.zero, self.send_group = zero, send_group
        return results, bodies

    ORDER = ["Hola buenas noches", "Pastelones", "40", "{model}", "amarillo", LOCATION]

    def test_complete_order_reaches_the_group_with_a_draft(self):
        results, bodies = self.run_chat(self.ORDER)
        self.assertEqual(self.send_group.call_count, 1)
        draft = self.send_group.call_args.args[3]
        for expected in ("PEDIDO PASTELONES", "Cliente: Cliente Uno", f"Número: +{PHONE}",
                         "Modelo: Gregoriano", "amarillo", "40 m²", "q=-33.500000,-70.600000"):
            self.assertIn(expected, draft)
        self.assertIn("Precio unitario: $1.600", draft)
        self.assertEqual(results[-1]["delivery"]["status"], "accepted")
        self.assertIn(REVIEW_SENTENCE, bodies[-1])
        self.assertNotIn("$", bodies[-1])

    def test_priced_model_shows_its_unit_price_unpriced_says_pending(self):
        self.run_chat(self.ORDER, model="Laja española")
        draft = self.send_group.call_args.args[3]
        self.assertIn("Precio unitario: $1.600", draft)
        self.assertNotIn("Precio pendiente", draft)

    def test_priced_order_counts_pieces_and_total(self):
        # 40 m² de 40×40 a 6 piezas por m² (Diego, 2026-11-09) = 240 piezas.
        self.run_chat(self.ORDER, model="Laja española")
        draft = self.send_group.call_args.args[3]
        self.assertIn("240 × Laja española · $1.600 c/u = $384.000", draft)
        self.assertIn("*Total productos: $384.000*", draft)
        self.assertNotIn("pendientes de calcular", draft)

    def test_piece_count_rounds_up_and_uses_the_size_yield(self):
        order = {"model": "Sol", "area_m2": "45", "color": None, "delivery_detail": None,
                 "unit_price": 1600, "price_id": config.LOSETASCHILE_PAVER_PRICE_ID}
        draft = format_paver_order_draft(order, profile_name=None, phone=PHONE)
        self.assertIn("270 × Sol · $1.600 c/u = $432.000", draft)
        draft = format_paver_order_draft({**order, "area_m2": "12,3"}, profile_name=None,
                                         phone=PHONE)
        self.assertIn("74 × Sol", draft)  # 73,8 piezas: nunca se cotiza de menos.
        draft = format_paver_order_draft(
            {**order, "price_id": config.LOSETASCHILE_PRICE_ID_PASTELON_50},
            profile_name=None, phone=PHONE)
        self.assertIn("180 × Sol", draft)
        for broken in ({"price_id": "otro"}, {"unit_price": None}):
            draft = format_paver_order_draft({**order, **broken}, profile_name=None,
                                             phone=PHONE)
            self.assertIn("pendientes de calcular", draft)
            self.assertNotIn("Total productos", draft)

    def test_missing_price_list_is_pending_not_unsent(self):
        self.run_chat(self.ORDER, priced=False, model="Laja española")
        self.assertEqual(self.send_group.call_count, 1)
        self.assertIn("Precio pendiente", self.send_group.call_args.args[3])

    def test_draft_needs_model_area_and_a_valid_number(self):
        order = {"model": "Sol", "area_m2": "10", "color": None, "delivery_detail": None}
        self.assertIn("Color indicado por cliente: pendiente", format_paver_order_draft(
            order, profile_name=None, phone="+56 9 0000 0001"))
        self.assertIsNone(format_paver_order_draft(order, profile_name=None, phone="12"))
        self.assertIsNone(format_paver_order_draft(
            {**order, "area_m2": None}, profile_name=None, phone=PHONE))

    def test_repeated_location_gets_a_normal_acknowledgement(self):
        results, bodies = self.run_chat(self.ORDER + [LOCATION])
        self.assertEqual(self.send_group.call_count, 1)  # no second notice
        self.assertNotIn("revisar tu consulta", bodies[-1].casefold())
        self.assertIn(REVIEW_SENTENCE, bodies[-1])
        self.assertFalse(results[-1].get("manual_review") and results[-1].get("intent") == "handoff")

    def test_repeat_does_not_open_a_question_gap(self):
        self.run_chat(self.ORDER + [LOCATION])
        gaps = self.zero.memory.list_knowledge_gaps("losetaschile")
        self.assertNotIn("pregunta", [gap["tipo"] for gap in gaps])

    def test_gap_keeps_order_type_when_a_question_repeats_its_text(self):
        memory = SessionMemory(None)
        memory.add_knowledge_gap("c", "Ubicación X", "Pastelones: cotizar", tipo="pedido")
        memory.add_knowledge_gap("c", "Ubicación X", "El agente repitió una respuesta",
                                 tipo="pregunta")
        (gap,) = memory.list_knowledge_gaps("c")
        self.assertEqual((gap["tipo"], gap["reason"], gap["veces"]),
                         ("pedido", "Pastelones: cotizar", 2))

    def test_status_and_thanks_are_answered_from_the_order_state(self):
        for text in ("ok gracias", "Gracias", "listo", "👍", "¿Y?", "¿ya?",
                     "¿Cuándo me llega el presupuesto?", "¿Cómo me llamo?"):
            with self.subTest(text=text):
                results, bodies = self.run_chat(self.ORDER + [text])
                self.assertIn(REVIEW_SENTENCE, bodies[-1])
                self.assertEqual(self.send_group.call_count, 1)
                self.assertEqual(self.zero.memory.list_knowledge_gaps("losetaschile"), [])

    def test_other_messages_go_through_the_flow_and_open_a_pedido_gap(self):
        for text in ("cancela el pedido", "mejor con otro color",
                     "¿cuánto cuesta el despacho a Maipú?"):
            with self.subTest(text=text):
                _, bodies = self.run_chat(self.ORDER + [text])
                self.assertNotIn(REVIEW_SENTENCE, bodies[-1])
                gaps = self.zero.memory.list_knowledge_gaps("losetaschile")
                mine = [gap for gap in gaps if gap["pregunta"].startswith(
                    "Pedido en revisión") and text in gap["pregunta"]]
                self.assertEqual([gap["tipo"] for gap in mine], ["pedido"])

    def test_greeting_mid_review_gives_the_status_not_the_product_menu(self):
        # Live 2026-11-09: a «hola» restarted the catalog while the budget sat in review.
        _, bodies = self.run_chat(self.ORDER + ["Hola buenas noches"])
        self.assertIn(REVIEW_SENTENCE, bodies[-1])
        self.assertNotIn("¿Qué producto estás buscando?", bodies[-1])

    def test_the_state_expires_after_the_configured_hours(self):
        self.run_chat(self.ORDER)
        zero = self.zero
        turns = next(iter(zero.memory.clients["losetaschile"]["conversations"].values()))
        old = (datetime.now(timezone.utc) -
               timedelta(hours=config.LOSETASCHILE_PAVER_REVIEW_STATE_HOURS + 1)).isoformat()
        for turn in turns:
            turn["at"] = old
        self.assertIsNone(paver_review_status(turns))
        with mock.patch("zero.whatsapp_web.send_group_text"), \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": GROUP}), \
                mock.patch.object(zero, "dispatch"):
            zero.handle_inbound(PHONE, "ok gracias", to_phone_id=BOT,
                                whatsapp_chat_id=CHAT)
        self.assertNotIn(REVIEW_SENTENCE, zero._deliver.call_args.args[3]["body"])

    def test_greeting_a_week_later_starts_normally_without_a_gap(self):
        self.run_chat(self.ORDER)
        zero = self.zero
        turns = next(iter(zero.memory.clients["losetaschile"]["conversations"].values()))
        for turn in turns:
            turn["at"] = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        before = len(zero.memory.list_knowledge_gaps("losetaschile"))
        zero.handle_inbound(PHONE, "Hola", to_phone_id=BOT, whatsapp_chat_id=CHAT)
        body = zero._deliver.call_args.args[3]["body"]
        self.assertNotIn(REVIEW_SENTENCE, body)
        self.assertIn("Qué producto", body)
        self.assertEqual(len(zero.memory.list_knowledge_gaps("losetaschile")), before)

    def test_a_turn_without_timestamp_counts_as_expired(self):
        history = [{"role": "agent", "text": REVIEW_SENTENCE + PAVER_REVIEW_SUFFIX[len(
            " está en revisión"):]}]
        self.assertIsNone(paver_review_status(history))
        history[0]["at"] = "not a date"
        self.assertIsNone(paver_review_status(history))

    def test_sentence_mentions_delivery_only_when_known(self):
        order = {"model": "Sol", "area_m2": "10", "color": None}
        self.assertNotIn("despacho", paver_review_sentence(order))
        self.assertIn("con despacho", paver_review_sentence(
            {**order, "delivery_detail": "Dirección indicada: X"}))
        self.assertIn("retiro en fábrica", paver_review_sentence(
            {**order, "delivery_detail": "Retiro en fábrica: Y"}))

    def test_group_not_configured_still_acknowledges_and_opens_the_gap(self):
        zero = _chat()
        with mock.patch("zero.whatsapp_web.send_catalog_document",
                        return_value={"id": "d", "ack": 0}), \
                mock.patch("zero.whatsapp_web.send_group_text") as send_group, \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": ""}), \
                mock.patch.object(zero, "dispatch"):
            for text in self.ORDER:
                zero.handle_inbound(PHONE, text.replace("{model}", "Gregoriano"),
                                    to_phone_id=BOT, whatsapp_chat_id=CHAT)
        send_group.assert_not_called()
        self.assertIn(REVIEW_SENTENCE, zero._deliver.call_args.args[3]["body"])
        (gap,) = zero.memory.list_knowledge_gaps("losetaschile")
        self.assertEqual(gap["tipo"], "pedido")

    def test_failed_group_send_acknowledges_opens_the_gap_and_is_not_retried(self):
        zero = _chat()
        with mock.patch("zero.whatsapp_web.send_catalog_document",
                        return_value={"id": "d", "ack": 0}), \
                mock.patch("zero.whatsapp_web.send_group_text",
                           side_effect=RuntimeError("bridge 502")) as send_group, \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": GROUP}), \
                mock.patch.object(zero, "dispatch"):
            for text in self.ORDER:
                zero.handle_inbound(PHONE, text.replace("{model}", "Gregoriano"),
                                    to_phone_id=BOT, whatsapp_chat_id=CHAT)
            self.assertIn(REVIEW_SENTENCE, zero._deliver.call_args.args[3]["body"])
            self.assertEqual(
                [gap["tipo"] for gap in zero.memory.list_knowledge_gaps("losetaschile")],
                ["pedido"])
            zero.handle_inbound(PHONE, LOCATION, to_phone_id=BOT, whatsapp_chat_id=CHAT)
            zero.handle_inbound(PHONE, "ok", to_phone_id=BOT, whatsapp_chat_id=CHAT)
        self.assertEqual(send_group.call_count, 1)

    def test_reply_to_a_paver_draft_is_logged_not_silent(self):
        from zero.losetas_review import handle_review_message, store_review_draft
        memory = SessionMemory(None)
        store_review_draft(memory, "losetaschile", "g-1", {
            "lead": "k", "quote": None, "order": "pastelones", "text": "borrador"})
        with mock.patch.object(memory, "log") as log:
            out = handle_review_message(memory, {"client": "losetaschile", "quoted_id": "g-1",
                                                 "text": "ok"})
        self.assertTrue(out["review_group"])
        self.assertEqual(log.call_args.args[0], "review_paver_reply_ignored")

    def test_a_new_product_request_is_not_swallowed_by_the_state(self):
        _, bodies = self.run_chat(self.ORDER + ["Bordes de piscina"])
        self.assertNotIn(REVIEW_SENTENCE, bodies[-1])


class PaverMenuPricingTest(unittest.TestCase):
    def test_every_offered_model_is_priced_or_declared_pending(self):
        unbacked = [model for model in PAVER_MODEL_OPTIONS
                    if model not in config.LOSETASCHILE_PAVER_PRICE_IDS
                    and model not in config.LOSETASCHILE_PAVER_PRICE_PENDING]
        self.assertEqual(unbacked, [], "modelo ofrecido sin precio respaldado ni declarado "
                                       "pendiente en config.LOSETASCHILE_PAVER_PRICE_PENDING")

    def test_a_model_is_not_both_priced_and_pending(self):
        self.assertFalse(set(config.LOSETASCHILE_PAVER_PRICE_IDS) &
                         config.LOSETASCHILE_PAVER_PRICE_PENDING)

    def test_config_lists_only_models_the_menu_offers(self):
        listed = set(config.LOSETASCHILE_PAVER_PRICE_IDS) | config.LOSETASCHILE_PAVER_PRICE_PENDING
        self.assertEqual(listed - set(PAVER_MODEL_OPTIONS), set())

    def test_gregoriano_costs_the_same_as_every_40x40(self):
        self.assertEqual(config.LOSETASCHILE_PAVER_PRICE_IDS["Gregoriano"],
                         config.LOSETASCHILE_PAVER_PRICE_ID)
        self.assertNotIn("Gregoriano", config.LOSETASCHILE_PAVER_PRICE_PENDING)

    def test_a_pending_model_says_price_pending(self):
        from unittest import mock
        with mock.patch.dict(config.LOSETASCHILE_PAVER_PRICE_IDS, clear=False) as ids:
            ids.pop("Gregoriano")
            with mock.patch.object(config, "LOSETASCHILE_PAVER_PRICE_PENDING",
                                   frozenset({"Gregoriano"})):
                PaverOrderReviewTest.run_chat(self, PaverOrderReviewTest.ORDER)
        self.assertIn("Precio pendiente", self.send_group.call_args.args[3])


if __name__ == "__main__":
    unittest.main()
