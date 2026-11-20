"""Contactos de anuncio que el agente dejaba sin respuesta (auditoría 2026-11-20).

El aviso del anuncio se filtra en el puente (whatsapp-web-bridge/test-chat-history.js).
Aquí queda la segunda causa: el tamaño de la pieza leído como medidas de la piscina.
"""
import unittest

from zero.orchestrator import _asks_again_for_supplied_measurements

ASK = "¿Cuáles son las medidas de su piscina? Necesito largo y ancho en metros."


class PieceSizeIsNotPoolMeasurementTest(unittest.TestCase):
    def test_piece_size_does_not_block_the_measurement_question(self):
        for text in ("Borde de 50x50 con nariz", "Borde 50 x 50 cm", "pastelón 40x40",
                     "borde ballena 50×40"):
            with self.subTest(text=text):
                self.assertFalse(_asks_again_for_supplied_measurements(text, ASK, []))

    def test_pool_measurements_still_count(self):
        for text in ("piscina de 7x3,5", "7 x 3.50 y el borde 50x50", "son 8 metros de largo"):
            with self.subTest(text=text):
                self.assertTrue(_asks_again_for_supplied_measurements(text, ASK, []))

    def test_pool_measurements_in_history_still_count(self):
        history = [{"role": "lead", "text": "La piscina es de 6 x 3"}]
        self.assertTrue(_asks_again_for_supplied_measurements("Borde 50x50", ASK, history))


if __name__ == "__main__":
    unittest.main()
