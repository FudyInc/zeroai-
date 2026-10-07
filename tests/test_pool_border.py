import unittest
from unittest import mock

from zero.agents import build_agents
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.pool_border import border_count_reply


class PoolBorderCountTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
