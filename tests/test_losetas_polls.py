import unittest

from zero.losetas_polls import (COLOR_POLL_QUESTION, DELIVERY_POLL_FACTORY_PICKUP,
                                DELIVERY_POLL_OPTIONS,
                                PRODUCT_POLL_QUESTION, canonical_choice,
                                numbered_choices, paver_order_details)


class PaverOrderDetailsTest(unittest.TestCase):
    def setUp(self):
        self.history = [
            {"role": "agent", "text": "¿Qué modelo del catálogo te interesa y cuántos m² necesitas cubrir?"},
        ]

    def test_collects_model_and_area_in_either_order(self):
        self.assertEqual(paver_order_details("Laja española", self.history),
                         {"model": "Laja española", "area_m2": None})
        history = [*self.history, {"role": "lead", "text": "Laja española"}]
        self.assertEqual(paver_order_details("18 m²", history),
                         {"model": "Laja española", "area_m2": "18"})

    def test_area_alone_does_not_count_as_model(self):
        self.assertEqual(paver_order_details("18 m²", self.history),
                         {"model": None, "area_m2": "18"})

    def test_ignores_details_from_before_the_prompt(self):
        history = [
            {"role": "lead", "text": "Necesito Laja española para 20 m²"},
            *self.history,
        ]
        self.assertEqual(paver_order_details("Hola", history),
                         {"model": None, "area_m2": None})


    def test_bare_number_counts_only_right_after_the_area_question(self):
        prompt = [{"role": "agent", "text": "¿Cuántos m² necesitas cubrir con pastelones?"}]
        self.assertEqual(paver_order_details("20", prompt)["area_m2"], "20")
        self.assertIsNone(paver_order_details("0", prompt)["area_m2"])
        later = [*prompt, {"role": "lead", "text": "no sé"},
                 {"role": "agent", "text": "¿Qué pastelón del catálogo te interesó más?"}]
        self.assertIsNone(paver_order_details("1", later)["area_m2"])


class NumberedChoiceTest(unittest.TestCase):
    def test_number_name_and_keycap_map_to_the_option(self):
        history = [{"role": "agent", "text": "¡Hola! " + numbered_choices("product")}]
        for answer in ("1", "1.", "opción 1", "1️⃣", "bordes de piscina", "BORDES DE PISCINA"):
            with self.subTest(answer=answer):
                self.assertEqual(canonical_choice(answer, history), "Bordes de piscina")
        self.assertEqual(canonical_choice("2", history), "Pastelones")

    def test_out_of_range_or_free_text_is_left_alone(self):
        history = [{"role": "agent", "text": numbered_choices("product")}]
        for answer in ("3", "0", "6x3", "hola"):
            with self.subTest(answer=answer):
                self.assertIsNone(canonical_choice(answer, history))
        # The word names the product; the «2» is a quantity, never option 2.
        self.assertEqual(canonical_choice("quiero 2 bordes", history), "Bordes de piscina")

    def test_only_the_latest_agent_prompt_counts(self):
        history = [{"role": "agent", "text": numbered_choices("product")},
                   {"role": "lead", "text": "1"},
                   {"role": "agent", "text": "¿Cuáles son las medidas de tu piscina?"}]
        self.assertIsNone(canonical_choice("2", history))

    def test_delivery_number_and_accentless_name(self):
        history = [{"role": "agent", "text": numbered_choices("delivery")}]
        self.assertEqual(canonical_choice("3", history), DELIVERY_POLL_FACTORY_PICKUP)
        self.assertEqual(canonical_choice("retiro en fabrica", history), DELIVERY_POLL_FACTORY_PICKUP)

    def test_question_is_not_repeated_when_reply_already_asks_it(self):
        text = numbered_choices("color", "Te comparto la gama. " + COLOR_POLL_QUESTION)
        self.assertNotIn(COLOR_POLL_QUESTION, text)
        self.assertIn("7. Amarillo", text)
        self.assertTrue(numbered_choices("product").startswith(PRODUCT_POLL_QUESTION))



class LooseAnswerTest(unittest.TestCase):
    """Answers as customers really type them (measured 2026-10-16)."""

    def ask(self, key):
        from zero.losetas_color import color_question
        reply = color_question() if key == "color" else ""
        return [{"role": "agent", "text": reply + "\n" + numbered_choices(key, reply)}]

    def test_menu_answers_in_words(self):
        product = self.ask("product")
        for answer in ("el 1", "uno", "la uno", "primera", "quiero el 1 porfa", "1️⃣ bordes",
                       "bordes de pisina", "borde piscina"):
            with self.subTest(answer=answer):
                self.assertEqual(canonical_choice(answer, product), "Bordes de piscina")
        for answer in ("quiero el 2", "dos", "pasteloness", "pasteones", "pastelon"):
            with self.subTest(answer=answer):
                self.assertEqual(canonical_choice(answer, product), "Pastelones")

    def test_colors_with_typos(self):
        color = self.ask("color")
        for answer, expected in (("amarrillo", "Amarillo"), ("bage", "Beige"),
                                 ("beich", "Beige"), ("naranjo", "Anaranjado"),
                                 ("blanko", "Blanco"), ("el gris", "Gris"), ("rojo porfa", "Rojo")):
            with self.subTest(answer=answer):
                self.assertEqual(canonical_choice(answer, color), expected)

    def test_delivery_in_loose_words(self):
        delivery = self.ask("delivery")
        for answer in ("retiro", "lo retiro yo", "retiro en fabrica", "fabrica", "paso a buscar"):
            with self.subTest(answer=answer):
                self.assertEqual(canonical_choice(answer, delivery), DELIVERY_POLL_FACTORY_PICKUP)
        for answer in ("despacho", "a domicilio", "te mando la ubicacion"):
            with self.subTest(answer=answer):
                self.assertEqual(canonical_choice(answer, delivery), DELIVERY_POLL_OPTIONS[0])
        self.assertEqual(canonical_choice("te escribo la direccion", delivery),
                         DELIVERY_POLL_OPTIONS[1])

    def test_models_and_shape_in_loose_words(self):
        self.assertEqual(canonical_choice("el recto", self.ask("border_model")),
                         "Borde recto con nariz 50×50")
        self.assertEqual(canonical_choice("ballena", self.ask("border_model")),
                         "Borde ballena 50×40")
        paver = self.ask("paver_model")
        for answer, expected in (("laja", "Laja española"), ("el ladrillo", "Ladrillo cruzado"),
                                 ("sol", "Sol"), ("sol rustico", "Sol rústico"),
                                 ("gregoriano", "Gregioriano"), ("octogonal", "Octagonal Piedra")):
            with self.subTest(answer=answer):
                self.assertEqual(canonical_choice(answer, paver), expected)
        shape = self.ask("shape")
        self.assertEqual(canonical_choice("sip", shape), "Sí, es rectangular")
        self.assertEqual(canonical_choice("es redonda", shape), "No es rectangular")

    def test_phrases_that_only_mention_an_option_do_not_pick_it(self):
        cases = (("shape", "si pero tiene forma de L"), ("shape", "no sé"),
                 ("delivery", "¿hacen despacho a Rancagua?"),
                 ("delivery", "cuanto cuesta el despacho"), ("delivery", "no gracias, retiro"),
                 ("delivery", "mi casa"), ("border_model", "no me gusta el recto"),
                 ("product", "precio del borde"), ("product", "los dos"),
                 ("color", "el gris claro me gusta mas pero no se"))
        for key, answer in cases:
            with self.subTest(answer=answer):
                self.assertIsNone(canonical_choice(answer, self.ask(key)))

    def test_real_words_are_not_corrected(self):
        from zero.losetas_text import normalize_customer_text
        for text in ("Pasaje Los Grises 120", "Pasaje Los Pastelitos 45", "me retira mi hermano",
                     "una linea recta", "la crema y las cremas", "casa blanca", "medida"):
            with self.subTest(text=text):
                self.assertEqual(normalize_customer_text(text), text)

    def test_sizes_written_loosely(self):
        from zero.losetas_text import normalize_measurements
        for answer in ("6mts x 3mts", "seis por tres", "largo 6 ancho 3",
                       "6 de largo y 3 de ancho", "6x3"):
            with self.subTest(answer=answer):
                self.assertRegex(normalize_measurements(answer), r"6\s*m?\s*x\s*3")
        self.assertEqual(normalize_measurements("Avenida Grecia 2020"), "Avenida Grecia 2020")


if __name__ == "__main__":
    unittest.main()
