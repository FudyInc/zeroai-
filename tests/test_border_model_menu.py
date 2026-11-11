"""The border model menu reads what the customer says instead of handing it to the model.

Ensayo 2026-11-09: at the open border model list, «me gustó el bullnose» got
«Perfecto, el bullnose queda muy bien… ¿me confirmas la comuna?» plus «elige una
opción de la lista»; «blanco» got the bare list again, as if unheard. Later
«Juan Pérez» got «Buenas noches Juan» mid-chat.
"""
from datetime import datetime, timedelta, timezone
import unittest

from tests import test_border_review_state as review
from zero.losetas_polls import unknown_option_named
from zero.orchestrator import _greets, _recent_agent_turn, _without_salutation

MENU = "¿Qué modelo de borde le interesó más?"
REHEARSAL = ["Hola buenas tardes, quiero cotizar bordes para mi piscina",
             "mide 8 x 4 metros, es rectangular"]


class BorderModelMenuTest(review.BorderReviewStateTest):
    # Reuse the chat harness only; the review tests stay in their own module.
    test_the_order_reaches_the_group_and_the_ack_states_the_review = None
    test_live_follow_ups_get_the_status_not_the_model = None
    test_thanks_after_the_status_is_not_taken_as_accepting_an_offer = None
    test_a_new_request_still_goes_through_the_flow = None

    def test_an_unknown_model_is_named_as_not_offered(self):
        body = self.run_chat(REHEARSAL + ["me gustó el bullnose"])[-1]
        self.assertTrue(body.startswith("No tengo el modelo «bullnose» en la lista"), body)
        self.assertIn(MENU, body)
        self.assertNotIn("comuna", body)
        self.assertNotIn("elige una opción", body.casefold())

    def test_a_color_at_the_model_menu_is_kept_and_acknowledged(self):
        bodies = self.run_chat(REHEARSAL + ["blanco", "2"])
        self.assertTrue(bodies[-2].startswith("Anoté el color blanco."), bodies[-2])
        self.assertIn(MENU, bodies[-2])
        # The color is not asked again: the next step is delivery.
        self.assertIn("¿Cómo prefiere recibir su pedido?", bodies[-1])

    def test_a_listed_model_by_name_still_advances(self):
        body = self.run_chat(REHEARSAL + ["prefiero el ballena"])[-1]
        self.assertNotIn("No tengo el modelo", body)
        self.assertNotIn(MENU, body)


class MenuHelpersTest(unittest.TestCase):
    def test_unknown_option_named(self):
        self.assertEqual(unknown_option_named("me gustó el bullnose", "border_model"),
                         "bullnose")
        for text in ("prefiero el ballena", "me gusta el más barato", "quiero el recto",
                     "bullnose", "quiero el otro", "quiero el pulido", "quiero la esquina",
                     "me interesa el celeste", "quiero el antideslizante"):
            self.assertIsNone(unknown_option_named(text, "border_model"), text)

    def test_salutation_removed_only_at_the_start(self):
        self.assertEqual(_without_salutation("Buenas noches Juan. Ya tomé tus datos."),
                         "Ya tomé tus datos.")
        self.assertEqual(_without_salutation("Holanda queda lejos."), "Holanda queda lejos.")
        self.assertEqual(_without_salutation("Hola."), "Hola.")

    def test_closing_question_trim_keeps_prices(self):
        import re
        trim = r"(^|[.!\n])[^.!?\n¿\d]*¿[^¿?]*\?[^\w¿?]*$"
        source = open("zero/orchestrator.py", encoding="utf-8").read()
        self.assertIn(trim, source)  # the pattern under test is the one in use
        cut = lambda a: re.sub(trim, r"\1", a).strip() or a
        self.assertEqual(cut("Queda muy bien. Para avanzar, ¿me confirmas la comuna?"),
                         "Queda muy bien.")
        for kept in ("El total es $5.000, ¿te sirve?", "Son 12.5 m2, ¿confirmas?"):
            self.assertIn(kept.split(",")[0], cut(kept))

    def test_greeting_detection(self):
        self.assertFalse(_greets("Juan Pérez"))
        self.assertTrue(_greets("Hola, soy Juan"))

    def test_recent_agent_turn(self):
        now = datetime.now(timezone.utc)
        self.assertTrue(_recent_agent_turn([{"role": "agent", "at": now.isoformat()}]))
        old = (now - timedelta(days=2)).isoformat()
        self.assertFalse(_recent_agent_turn([{"role": "agent", "at": old}]))
        self.assertFalse(_recent_agent_turn([{"role": "lead", "at": now.isoformat()}]))


if __name__ == "__main__":
    unittest.main()
