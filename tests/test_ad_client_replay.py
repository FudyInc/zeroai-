"""Clientes reales de los anuncios de Meta (2026-11-10), anonimizados.

El agente quedó en manual para todos por estos errores:
- un sufijo «Para seguir, elige una opción de la lista con su número» en respuestas sin lista;
- «No tengo una lista numérica disponible» ante «¿cuál lista?»;
- 9,60 × 4 m bloqueaba el cálculo con «Necesito confirmar los cortes»;
- «boldes», «rompeolas» y «bordes y extensión» no se entendían, y la extensión se perdía;
- al vencer la pausa, el agente retomaba chats que Diego atendía desde el teléfono.
"""
import os
import unittest
from unittest import mock

from zero.agents import build_agents
from zero.crm import CRM
from zero.losetas_polls import (MENU_ASIDE_CLOSING, _LEGACY_ASIDE_CLOSING, asks_which_list,
                                menu_aside_closing, without_choice_slips)
from zero.losetas_shipping import DELIVERY_PLACE_REPLY, delivery_with_place
from zero.losetas_text import normalize_customer_text
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.pool_border import mentions_extension, mixed_order_notes, named_border_model
from zero.whatsapp_web import parse_message

from tests.test_border_review_state import PRICING

PHONE = "56900000077"
BOT = "56911111111"
GROUP = "123456789@g.us"
CHAT = PHONE + "@c.us"
EXTENSION_NOTE = "El cliente también pidió extensión"


class AdClientReplayTest(unittest.TestCase):
    def setUp(self):
        self.memory = SessionMemory(None)
        self.memory.register_client("losetaschile", "STARTER")
        self.memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": BOT, "response_mode": "automatic"})
        self.memory.set_client_pricing("losetaschile", PRICING)
        self.crm = CRM(None)
        self.crm.upsert("losetaschile", {"phone": PHONE, "source": "test"})
        self.zero = Zero(build_agents(mock=True), memory=self.memory, crm=self.crm)
        self.zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web"})

    def run_chat(self, messages):
        sent = {"id": "x", "ack": 0}
        bodies = []
        with mock.patch("zero.whatsapp_web.send_catalog_document", return_value=sent), \
                mock.patch("zero.whatsapp_web.send_catalog_image", return_value=sent) as image, \
                mock.patch("zero.whatsapp_web.send_choice_poll", return_value=sent), \
                mock.patch("zero.whatsapp_web.send_delivery_poll", return_value=sent), \
                mock.patch("zero.whatsapp_web.send_group_text",
                           return_value={"id": "group-1", "ack": 0}) as group, \
                mock.patch("urllib.request.urlopen", side_effect=AssertionError("sin red")), \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": GROUP}), \
                mock.patch.object(self.zero, "dispatch") as dispatch:
            for text in messages:
                before = self.zero._deliver.call_count
                self.zero.handle_inbound(PHONE, text, to_phone_id=BOT, whatsapp_chat_id=CHAT)
                bodies.append(self.zero._deliver.call_args.args[3]["body"]
                              if self.zero._deliver.call_count > before else "")
        self.group, self.dispatch, self.image = group, dispatch, image
        return bodies

    def test_the_ad_client_chat_reaches_the_review_group(self):
        bodies = self.run_chat([
            "¡Hola! Quiero más información", "Boldes y extension",
            "Boldes con rompeolas y nariz", "Cual lista?", "10,5 x 4 m", "5",
            "Con despacho 7 región", "Molina, 7 región"])
        self.dispatch.assert_not_called()
        self.assertIn("Bordes de piscina", bodies[0])
        self.assertIn("¿Cuáles son las medidas de tu piscina?", bodies[1])
        self.assertIn("Anoté el borde recto con nariz 50×50", bodies[2])
        self.assertIn("no hay una lista pendiente", bodies[3])
        self.assertIn("¿Cuáles son las medidas de tu piscina?", bodies[3])
        self.assertEqual(self.image.call_count, 1)   # la gama de colores va con la imagen
        self.assertIn("¿Cómo prefieres recibir tu pedido?", bodies[5])
        self.assertEqual(bodies[6], DELIVERY_PLACE_REPLY)
        self.assertIn("en revisión del equipo", bodies[7])
        for body in bodies:
            self.assertNotIn("lista numérica", body)
            self.assertNotIn(_LEGACY_ASIDE_CLOSING, body)
            self.assertNotRegex(body, r"\$\d")   # al cliente nunca le llega un importe
        self.assertEqual(self.group.call_count, 1)
        draft = self.group.call_args.args[-1]
        self.assertIn("58 × Borde recto con nariz 50x50", draft)
        self.assertIn("4 × Esquina piscina 50x50", draft)
        self.assertIn(EXTENSION_NOTE, draft)

    def test_sides_off_the_half_metre_reach_the_group_with_a_note(self):
        bodies = self.run_chat(["Hola", "1", "9,60x4,00", "1", "5", "3"])
        self.assertNotIn("confirmar los cortes", " ".join(bodies))
        self.assertEqual(self.group.call_count, 1)
        draft = self.group.call_args.args[-1]
        self.assertIn("Nota: Medidas 9,6 × 4 m redondeadas a 10 × 4 m", draft)
        self.assertNotIn(EXTENSION_NOTE, draft)

    def test_the_extension_survives_the_canonical_option(self):
        self.run_chat(["Hola", "Bordes y extensión"])
        stored = [t["text"] for t in self.memory.get_conversation("losetaschile", PHONE)
                  if t["role"] == "lead"]
        self.assertNotIn("extensión", " ".join(stored).lower())   # el historial la pierde
        self.assertEqual(self.memory.lead_notes("losetaschile", PHONE), {"extension": True})

    def test_an_owner_pause_keeps_the_agent_quiet(self):
        self.memory.set_whatsapp_handoff("losetaschile", CHAT,
                                         "El equipo respondió desde el teléfono")
        bodies = self.run_chat(["Hola", "1"])
        self.assertEqual(bodies, ["", ""])


class VocabularyAndListsTest(unittest.TestCase):
    def test_boldes_is_bordes(self):
        self.assertIn("bordes", normalize_customer_text("Boldes y extension").lower())

    def test_named_models(self):
        self.assertIn("recto", named_border_model("Boldes con rompeolas y nariz"))
        self.assertIn("ballena", named_border_model("borde ballena sin nariz"))
        self.assertIsNone(named_border_model("¿cuál me recomiendas?"))

    def test_which_list(self):
        for text in ("Cual lista?", "¿Qué lista?", "no me llegó la lista", "¿Qué opciones?"):
            with self.subTest(text=text):
                self.assertTrue(asks_which_list(text))
        for text in ("Me gusta la lista de colores", "10 x 4", "listo"):
            with self.subTest(text=text):
                self.assertFalse(asks_which_list(text))

    def test_delivery_with_place(self):
        self.assertTrue(delivery_with_place("Con despacho 7 región"))
        self.assertFalse(delivery_with_place("retiro en fábrica"))

    def test_extension_notes(self):
        self.assertTrue(mentions_extension("bordes y extensión"))
        self.assertEqual(mixed_order_notes("10 x 4", [], {"extension": True})[0][:34],
                         EXTENSION_NOTE)
        self.assertEqual(mixed_order_notes("10 x 4", [{"role": "lead", "text": "bordes"}]), [])

    def test_the_aside_closing_repeats_the_open_menu(self):
        closing = menu_aside_closing("border_model")
        self.assertTrue(closing.startswith(MENU_ASIDE_CLOSING))
        self.assertIn("1. Borde recto con nariz", closing)

    def test_old_aside_closings_are_still_dropped_from_the_history(self):
        turns = [{"role": "agent", "text": "Es de 40x40. " + _LEGACY_ASIDE_CLOSING},
                 {"role": "agent", "text": "Es de 40x40.\n\n" + menu_aside_closing("color")}]
        self.assertEqual(without_choice_slips(turns), [])


class OwnerPhoneMessageTest(unittest.TestCase):
    PAYLOAD = {"kind": "owner_message", "id": "true_56900000077@c.us_ABC", "chat_id": CHAT,
               "to": PHONE, "type": "chat", "text": "Hola, te mando el presupuesto",
               "to_phone_id": BOT}

    def setUp(self):
        self.memory = SessionMemory(None)
        self.memory.register_client("losetaschile", "STARTER")
        self.crm = CRM(None)
        self.crm.upsert("losetaschile", {"phone": PHONE, "source": "test"})
        self.key = self.crm.find_by_contact(phone=PHONE, client_id="losetaschile")["key"]

    def process(self, payload):
        from api import _process_owner_message
        message = parse_message(payload)
        message["client"] = "losetaschile"
        return _process_owner_message(self.memory, self.crm, message)

    def test_parse(self):
        message = parse_message(dict(self.PAYLOAD))
        self.assertEqual((message["kind"], message["phone"]), ("owner_message", PHONE))
        self.assertIsNone(parse_message({**self.PAYLOAD, "chat_id": GROUP}))
        self.assertIsNone(parse_message({**self.PAYLOAD, "to": "abc"}))

    def test_owner_message_pauses_without_expiry_and_enters_the_history(self):
        # Una pausa de 2 h por un adjunto ilegible ya no vence: Diego tomó el chat.
        self.memory.set_whatsapp_handoff("losetaschile", CHAT, "Mensaje ilegible", ttl_hours=2)
        result = self.process(dict(self.PAYLOAD))
        self.assertTrue(result["stored"])
        handoff = self.memory.get_whatsapp_handoff("losetaschile", CHAT)
        self.assertEqual(handoff["reason"], "El equipo respondió desde el teléfono")
        self.assertNotIn("expires", handoff)
        turns = self.memory.get_conversation("losetaschile", self.key)
        self.assertEqual(turns[-1], {**turns[-1], "role": "agent",
                                     "text": "Hola, te mando el presupuesto"})

    def test_a_reply_already_stored_is_not_duplicated(self):
        self.memory.add_turn("losetaschile", self.key, "agent", "Hola, te mando\n\nel presupuesto")
        self.assertFalse(self.process(dict(self.PAYLOAD))["stored"])
        self.assertEqual(len(self.memory.get_conversation("losetaschile", self.key)), 1)

    def test_media_only_pauses(self):
        result = self.process({**self.PAYLOAD, "type": "image", "text": ""})
        self.assertFalse(result["stored"])
        self.assertTrue(self.memory.get_whatsapp_handoff("losetaschile", CHAT))

    def test_other_businesses_are_left_alone(self):
        from api import _process_owner_message
        message = {**parse_message(dict(self.PAYLOAD)), "client": "otra"}
        self.assertTrue(_process_owner_message(self.memory, self.crm, message)["ignored"])
        self.assertIsNone(self.memory.get_whatsapp_handoff("otra", CHAT))


if __name__ == "__main__":
    unittest.main()
