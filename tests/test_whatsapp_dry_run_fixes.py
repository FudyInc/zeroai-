"""Fallas del ensayo de WhatsApp de LosetasChile (2026-11-08)."""
import os
import unittest
from datetime import datetime, timezone
from unittest import mock

from zero.agents import build_agents
from zero.config import (LOSETASCHILE_PAVER_REVIEW_SHIPPING_REPLY, WHATSAPP_CLOSING_REPLY)
from zero.losetas_polls import (CHOICE_SLIP_MARK, MENU_ASIDE_CLOSING, PAVER_AREA_QUESTION,
                                canonical_choice, choice_slip_reply, customer_acknowledges,
                                customer_closes, direct_product_category, invalid_choice,
                                open_choice, paver_order_details, paver_review_sentence,
                                without_choice_slips)
from zero.losetas_shipping import SHIPPING_PRICE_REPLY, shipping_delivery_followup
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.pool_border import border_plan, paver_price_reply, wants_product_quote
from zero.customer_text import normalize as normalize_customer_input
from zero.config import WHATSAPP_HUMAN_REQUEST_ACK
from tests.test_whatsapp_live_errors import _LiveChat

PRICING = {"currency": "CLP", "iva_rate": 0, "items": [
    {"id": "pastelones-40x40", "name": "Pastelón 40x40", "unit_price": 1600, "unit": "unidad"},
    {"id": "pastelones-50x50", "name": "Pastelón 50x50", "unit_price": 2600, "unit": "unidad"},
    {"id": "durmiente-16x40", "name": "Durmiente 16x40", "unit_price": 900, "unit": "unidad"},
    {"id": "deck-madera-50x50", "name": "Deck madera 50x50", "unit_price": 3600, "unit": "unidad"}]}
COLOR_MENU = ("Le comparto la gama de colores disponible.\n\n¿Qué color prefiere?\n\n"
              "1. Anaranjado\n2. Blanco\n3. Rojo\n4. Crema\n5. Beige\n6. Gris\n7. Amarillo\n\n"
              "Responda con el número o el nombre.")
DELIVERY_MENU = ("¿Cómo prefiere recibir su pedido?\n\n1. 📍 Despacho · compartir ubicación\n"
                 "2. ✍️ Despacho · escribir dirección\n3. 🏭 Retiro en fábrica\n\n"
                 "Responda con el número o el nombre.")


def turns(*pairs):
    return [{"role": role, "text": text} for role, text in pairs]


class MenuReaskTest(unittest.TestCase):
    """Real chat: «8» to the colour list, the model re-asks in its own words, then «7»."""
    HISTORY = turns(("lead", "hola"), ("agent", DELIVERY_MENU), ("lead", "1"),
                    ("agent", COLOR_MENU), ("lead", "8"))

    def test_number_after_a_free_text_reask_answers_the_colour_menu(self):
        for reask in ("Elige un color del 1 al 7. ¿Cuál te gusta?",
                      "El número 8 no está en la lista de colores disponibles. "
                      "Por favor, elige un color entre 1 y 7."):
            history = self.HISTORY + turns(("agent", reask))
            self.assertEqual(open_choice(history), "color")
            self.assertEqual(canonical_choice("7", history), "Amarillo")
            self.assertEqual(canonical_choice("3", history), "Rojo")
            self.assertEqual(invalid_choice("8", history), "color")

    def test_slip_text_names_the_menu_that_was_asked(self):
        self.assertEqual(choice_slip_reply("8", "color"),
                         f"El 8 {CHOICE_SLIP_MARK}. Elija un número del 1 al 7.")

    def test_a_reask_without_a_menu_topic_opens_nothing(self):
        history = turns(("agent", "Elige lo que quieras."), ("lead", "3"))
        self.assertIsNone(open_choice(history[:1]))

    def test_filler_around_an_out_of_range_number_is_still_a_slip(self):
        history = turns(("agent", "¿Qué modelo de borde le interesó más?\n\n"
                                  "1. Borde recto con nariz 50×50\n2. Borde ballena 50×40"))
        for message in ("6 perdon", "el 6", "opción 7", "6"):
            self.assertEqual(invalid_choice(message, history), "border_model", message)
        for message in ("2 perdon", "20", "6 metros", "hola 6"):
            self.assertIsNone(invalid_choice(message, history), message)
        self.assertEqual(choice_slip_reply("6 perdon", "border_model"),
                         f"El 6 {CHOICE_SLIP_MARK}. Elija 1 o 2.")


class CustomerTextNormalizationTest(unittest.TestCase):
    def test_measurement_inputs_normalize_without_decimal_truncation(self):
        expected = {
            "7,25 x 3,5": "7,25 x 3,5",
            "7.25 por 3.5": "7.25 por 3.5",
            "8 ,5 x 4": "8,5 x 4",
            "8 1/2 x 4": "8,5 x 4",
            "8 y medio por 4": "8,5 por 4",
            "ocho por cuatro": "8 por 4",
            "8 de largo y 4 de ancho": "8 x 4",
            "largo 8 ancho 4": "8 x 4",
            "8 * 4": "8 x 4",
        }
        for source, result in expected.items():
            with self.subTest(source=source):
                self.assertEqual(normalize_customer_input(source), result)

    def test_common_product_typos_normalize(self):
        for source, result in (
            ("quiero cotisar bordes para la pisina", "quiero cotizar bordes para la piscina"),
            ("nesesito bordes de piscina", "necesito bordes de piscina"),
            ("pasteones", "pastelones"),
            ("kiero pastelones", "quiero pastelones"),
            ("bordez para piscina", "bordes para piscina"),
            ("borde de picina", "borde de piscina"),
        ):
            with self.subTest(source=source):
                self.assertEqual(normalize_customer_input(source), result)

    def test_pool_size_uses_normalized_decimal_and_written_numbers(self):
        prefix = "borde recto con nariz piscina rectangular "
        for source, straight in (("ocho por cuatro", 48), ("largo 8 ancho 4", 48),
                                 ("8 de largo y 4 de ancho", 48), ("8 * 4", 48),
                                 ("8 ,5 x 4", 50), ("8 1/2 x 4", 50), ("8 y medio por 4", 50)):
            with self.subTest(source=source):
                plan, _ = border_plan(prefix + source, [])
                self.assertIsNotNone(plan)
                self.assertEqual((plan["straight"], plan["corners"]), (straight, 4))

    def test_quarter_metre_decimal_is_not_read_as_a_whole_side(self):
        # Ensayo 2026-11-09: «7,25 x 3,5» se leía como 25 m y cotizaba 114 bordes.
        for source in ("7,25 x 3,5", "7.25 por 3.5"):
            with self.subTest(source=source):
                plan, ask = border_plan("borde recto con nariz piscina rectangular " + source, [])
                self.assertEqual(ask, "")
                self.assertEqual(str(plan["width"]), "7.5")   # nunca 25 m
                self.assertIn("redondeadas a 7,5 × 3,5 m", plan["review_notes"][0])

    def test_paver_area_accepts_variants_and_dimension_product(self):
        history = turns(("agent", PAVER_AREA_QUESTION))
        for source, expected in (("30 mts2", "30"), ("treinta metros", "30"),
                                 ("unos 30 metros", "30"), ("30 mtrs cuadrados", "30"),
                                 ("5x6", "30"), ("5 x 6 metros", "30")):
            with self.subTest(source=source):
                self.assertEqual(paver_order_details(source, history)["area_m2"], expected)

    def test_lengths_and_piece_sizes_are_not_an_area(self):
        # Revisor 2026-11-09: «3 metros de ancho» se anotaba como 3 m².
        history = turns(("agent", PAVER_AREA_QUESTION))
        for source in ("tengo 3 metros de ancho", "10 metros de largo", "80 x 40", "40x40"):
            with self.subTest(source=source):
                self.assertIsNone(paver_order_details(source, history)["area_m2"])
        self.assertEqual(paver_order_details("8 x 4 y 20 m2", history)["area_m2"], "20")

    def test_area_correction_on_the_model_menu_ignores_piece_sizes(self):
        from zero.losetas_polls import PAVER_MODEL_QUESTION, area_correction
        history = turns(("agent", f"Anoté 30 m². {PAVER_MODEL_QUESTION}"))
        for source in ("son 80 por 40", "100 x 100", "60 x 40", "2 por 1"):
            with self.subTest(source=source):
                self.assertIsNone(area_correction(source, history))
        self.assertEqual(area_correction("8 x 4 y 20 m2", history), "20")
        self.assertEqual(area_correction("mejor 6 x 5", history), "30")


class PollsTest(unittest.TestCase):
    def test_pavers_for_the_pool_start_the_paver_flow(self):
        for message in ("Pastelones para piscina", "pastelones de la piscina",
                        "quiero pastelones para mi terraza", "Pastelones"):
            self.assertEqual(direct_product_category(message), "pastelones", message)
        self.assertEqual(direct_product_category("bordes para piscina"), "bordes")

    def test_border_request_with_possessive_skips_the_product_menu(self):
        # Ensayo 2026-11-09: «bordes para mi piscina» recibía el menú «¿Qué producto?».
        for message in ("Hola buenas tardes, quiero cotizar bordes para mi piscina",
                        "necesito bordes para una piscina", "busco bordes de nuestra piscina"):
            self.assertEqual(direct_product_category(message), "bordes", message)
        self.assertIsNone(direct_product_category("quiero bordes para mi piscina y pastelones"))

    def test_closing_and_bare_acknowledgments_are_different(self):
        for message in ("Okay gracias luego consulto", "no quiero nada", "gracias",
                        "después veo", "lo voy a pensar"):
            self.assertTrue(customer_closes(message), message)
        for message in ("ok", "oka", "dale", "listo", "👍"):
            self.assertTrue(customer_acknowledges(message), message)
            self.assertFalse(customer_closes(message), message)
        self.assertFalse(customer_closes("no quiero el rojo, quiero el gris"))


class PaverPriceTest(unittest.TestCase):
    def test_price_comes_from_the_client_list(self):
        self.assertEqual(paver_price_reply("¿cuánto vale el gregoriano?", PRICING),
                         "El pastelón Gregoriano es de 40x40 y vale $1.600 c/u.")
        self.assertEqual(paver_price_reply("precio del sol rústico", PRICING),
                         "El pastelón Sol rústico es de 40x40 y vale $1.600 c/u.")
        self.assertEqual(paver_price_reply("precio de los pastelones", PRICING),
                         "Los pastelones de 40x40 valen $1.600 c/u y los de 50x50, $2.600 c/u.")
        self.assertEqual(paver_price_reply("¿cuánto vale el deck?", PRICING),
                         "El pastelón Deck madera es de 50x50 y vale $3.600 c/u.")
        self.assertEqual(paver_price_reply("precio del adoquín", PRICING),
                         "El pastelón Adoquín es de 40x40 y vale $1.600 c/u.")
        self.assertEqual(paver_price_reply("precio del corrugado", PRICING),
                         "El pastelón Corrugado es de 50x50 y vale $2.600 c/u.")
        self.assertEqual(paver_price_reply("cuánto cuesta el durmiente", PRICING),
                         "El durmiente es de 16x40 y vale $900 c/u.")
        changed = {"items": [{"id": "pastelones-40x40", "unit_price": 1700}]}
        self.assertEqual(paver_price_reply("precio de los pastelones", changed),
                         "Los pastelones de 40x40 valen $1.700 c/u.")
        self.assertIsNone(paver_price_reply("precio de los pastelones", {"items": []}))

    def test_other_questions_are_not_paver_prices(self):
        for message in ("precio del borde recto", "cuánto cuesta el despacho a Maipú",
                        "quiero el gregoriano"):
            self.assertIsNone(paver_price_reply(message, PRICING), message)

    def test_any_paver_model_leaves_the_border_quote(self):
        for message in ("cuánto vale el gregoriano", "precio sol", "precio sol rústico",
                        "precio durmiente"):
            self.assertFalse(wants_product_quote(message), message)
        self.assertTrue(wants_product_quote("precio del borde recto"))


class PoolSizeTest(unittest.TestCase):
    HISTORY = turns(("lead", "bordes de piscina"))

    def test_metres_are_not_read_as_centimetres(self):
        plan, question = border_plan("200 x 150 m", self.HISTORY)
        self.assertIsNone(plan)
        self.assertIn("necesitan confirmación", question)
        for message in ("600x300", "600 x 300 cm"):
            self.assertNotIn("necesitan confirmación", border_plan(message, self.HISTORY)[1])


class DeliveryTextTest(unittest.TestCase):
    HISTORY = turns(("agent", SHIPPING_PRICE_REPLY))

    def test_only_a_destination_counts(self):
        for message in ("cancela el pedido", "ya no lo quiero", "me pueden llamar",
                        "quiero cambiar el pedido", "¿y si lo anulo?"):
            self.assertFalse(shipping_delivery_followup(message, self.HISTORY), message)
        for message in ("Los Aromos 123, Maipú", "maipú", "Av. Pajaritos 4500"):
            self.assertTrue(shipping_delivery_followup(message, self.HISTORY), message)


class _Flow(unittest.TestCase):
    def setUp(self):
        self.memory = SessionMemory(None)
        self.memory.register_client("losetaschile", "STARTER")
        self.memory.set_client_pricing("losetaschile", PRICING)
        self.zero = Zero(build_agents(mock=True), memory=self.memory)

    def converse(self, message, history):
        return self.zero.converse_result("losetaschile", message, lead={"key": "k"},
                                         history=history)


class PriceFlowTest(_Flow):
    def test_price_question_asks_the_paver_area_and_the_next_number_continues(self):
        greeting = turns(("lead", "Hola"), ("agent", "¿Qué producto está buscando?"))
        result = self.converse("¿cuánto vale el gregoriano?", greeting)
        self.assertEqual(result["reply"], "El pastelón Gregoriano es de 40x40 y vale $1.600 c/u. "
                         + PAVER_AREA_QUESTION)
        history = greeting + turns(("lead", "¿cuánto vale el gregoriano?"),
                                   ("agent", result["reply"]))
        follow = self.converse("25", history)
        self.assertTrue(follow["reply"].startswith("Anoté 25 m²."))
        self.assertEqual(follow["customer_poll"], "paver_model")

    def test_price_during_a_paver_order_does_not_ask_the_area_again(self):
        history = turns(("lead", "Pastelones"), ("agent", PAVER_AREA_QUESTION))
        result = self.converse("cuánto cuesta la laja", history)
        self.assertEqual(result["reply"], "El pastelón Laja española es de 40x40 y vale $1.600 c/u.")


class FirstContactTest(_Flow):
    def test_vague_first_messages_get_greeting_and_product_menu(self):
        for message in ("Hola PoolEdge, vi el catálogo y quiero cotizar",
                        "Hola PoolEdge, vi la web y quiero cotizar",
                        "Hola vi su anuncio en Instagram", "vi su publicación",
                        "Buenas, quiero cotizar", "info"):
            result = self.converse(message, [])
            self.assertRegex(result["reply"], r"^¡[^!]+! ¿En qué puedo ayudarle\?$", message)
            self.assertEqual(result["customer_poll"], "product", message)

    def test_concrete_first_questions_keep_their_answer(self):
        result = self.converse("Hola, ¿aceptan tarjeta?", [])
        self.assertNotEqual(result.get("customer_poll"), "product")
        result = self.converse("¿cuánto vale el gregoriano?", [])
        self.assertIn("$1.600", result["reply"])


class GreetingMidOrderTest(_Flow):
    """Eval 2026-11-08: a «hola» while the colour question was open restarted
    the product menu. Diego: the agent always picks up each client's chat."""

    def test_greeting_with_an_open_menu_resumes_that_question(self):
        history = turns(("lead", "bordes"), ("agent", "Catálogo Bordes de Piscina"),
                        ("lead", "Borde recto con nariz 50×50"), ("agent", COLOR_MENU))
        result = self.converse("hola", history)
        self.assertRegex(result["reply"], r"^¡[^!]+! ¿Qué color prefiere\?$")
        self.assertEqual(result["customer_poll"], "color")

    def test_greeting_with_delivery_open_resumes_delivery(self):
        history = turns(("lead", "Amarillo"), ("agent", DELIVERY_MENU))
        result = self.converse("Buenas", history)
        self.assertIn("¿Cómo prefiere recibir su pedido?", result["reply"])
        self.assertTrue(result.get("delivery_poll"))

    def test_greeting_after_the_area_question_asks_it_again(self):
        history = turns(("lead", "Pastelones"), ("agent", PAVER_AREA_QUESTION))
        result = self.converse("hola", history)
        self.assertTrue(result["reply"].endswith(PAVER_AREA_QUESTION))
        self.assertNotEqual(result.get("customer_poll"), "product")

    def test_greeting_with_nothing_open_still_offers_the_products(self):
        result = self.converse("hola", [])
        self.assertEqual(result["customer_poll"], "product")


class ClosingTest(_Flow):
    MENU = turns(("lead", "bordes"), ("agent", "¿Qué modelo de borde le interesó más?\n\n"
                                               "1. Borde recto con nariz 50×50\n"
                                               "2. Borde ballena 50×40"))

    def test_closing_gets_the_fixed_line_without_the_menu_suffix(self):
        for message in ("Okay gracias luego consulto", "no quiero nada", "gracias"):
            result = self.converse(message, self.MENU)
            self.assertEqual(result["reply"], WHATSAPP_CLOSING_REPLY, message)

    def test_a_bare_ok_repeats_the_open_menu(self):
        result = self.converse("ok", self.MENU)
        self.assertEqual(result["customer_poll"], "border_model")
        self.assertIn("¿Qué modelo de borde le interesó más?", result["reply"])
        area = turns(("lead", "Pastelones"), ("agent", PAVER_AREA_QUESTION))
        self.assertEqual(self.converse("dale", area)["reply"], PAVER_AREA_QUESTION)


class ChatTest(_LiveChat):
    def review_turns(self):
        sentence = paver_review_sentence({"area_m2": "40", "model": "Gregoriano",
                                          "color": "Amarillo", "delivery_detail": "Ubicación"})
        now = datetime.now(timezone.utc).isoformat()
        self.memory.add_turn("losetaschile", "56933333333", "lead", "Pastelones")
        self.memory.add_turn("losetaschile", "56933333333", "agent",
                             "Gracias, recibí los datos de entrega. " + sentence)
        for turn in self.memory.get_conversation("losetaschile", "56933333333"):
            turn["at"] = now

    def test_human_request_is_acknowledged_once_and_opens_an_attention_case(self):
        self.inbound("quiero hablar con una persona")
        self.assertEqual(self.sent(), [WHATSAPP_HUMAN_REQUEST_ACK])
        gaps = self.memory.list_knowledge_gaps("losetaschile")
        self.assertEqual([gap["tipo"] for gap in gaps], ["pedido"])
        self.inbound("hola?")
        self.assertEqual(len(self.sent()), 1)  # the bot stays paused

    def test_shipping_price_with_an_order_in_review_has_a_fixed_reply_and_no_menu(self):
        self.review_turns()
        self.memory.set_client_pricing("losetaschile", PRICING)
        self.inbound("¿cuánto cuesta el despacho a Maipú?")
        self.assertEqual(self.sent(), [LOSETASCHILE_PAVER_REVIEW_SHIPPING_REPLY])

    def test_cancelling_an_order_in_review_goes_to_a_person_and_sends_nothing_to_the_group(self):
        self.review_turns()
        with mock.patch("zero.whatsapp_web.send_group_text") as send_group, \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": "1@g.us"}):
            result = self.inbound("cancela el pedido")
        send_group.assert_not_called()
        self.assertEqual(result["intent"], "handoff")
        self.assertNotIn("cancelado", " ".join(self.sent()).casefold())

    def test_the_menu_suffix_is_never_doubled(self):
        reply = {"reply": f"Es de 40x40. {MENU_ASIDE_CLOSING}", "intent": "info", "aside": True}
        self.turns(("agent", "¿Qué modelo de borde le interesó más?\n\n1. Borde recto con nariz "
                             "50×50\n2. Borde ballena 50×40"))
        with mock.patch.object(self.zero, "converse_result", return_value=reply):
            self.inbound("¿de qué medida es?")
        self.assertEqual(self.sent()[-1].count(MENU_ASIDE_CLOSING), 1)
