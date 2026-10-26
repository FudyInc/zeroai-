"""revisar-salud.py avisa por correo/WhatsApp solo lo urgente, y no repite el mismo aviso."""
import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock

_RUTA = Path(__file__).resolve().parent.parent / "scripts" / "revisar-salud.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("revisar_salud", _RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class AvisosSoloUrgentes(unittest.TestCase):
    def setUp(self):
        self.salud = _cargar()

    def _correr(self, fallas):
        with mock.patch.object(self.salud, "revisar", return_value=fallas), \
                mock.patch.object(self.salud, "notify_owner",
                                  return_value={"status": "sent"}) as aviso, \
                mock.patch("sys.argv", ["revisar-salud.py"]):
            codigo = self.salud.main()
        return codigo, aviso

    def test_mensajes_por_revisar_no_mandan_correo(self):
        codigo, aviso = self._correr([self.salud.NO_URGENTE + "WhatsApp: 25 mensajes requieren revisión"])
        aviso.assert_not_called()
        self.assertEqual(codigo, 0)

    def test_una_caida_si_avisa_y_sin_lo_no_urgente(self):
        codigo, aviso = self._correr(["el servicio ollama está caído",
                                      self.salud.NO_URGENTE + "WhatsApp: 3 mensajes requieren revisión"])
        self.assertEqual(codigo, 1)
        texto = aviso.call_args.args[0]
        self.assertIn("ollama", texto)
        self.assertNotIn("revisión", texto)
        self.assertEqual(aviso.call_args.kwargs["throttle_minutes"],
                         self.salud.SALUD_REPETIR_MISMO_AVISO_HORAS * 60)

    def test_problemas_distintos_tienen_ventanas_distintas(self):
        _, a = self._correr(["el servicio ollama está caído"])
        _, b = self._correr(["el dashboard está caído"])
        self.assertNotEqual(a.call_args.kwargs["kind"], b.call_args.kwargs["kind"])


if __name__ == "__main__":
    unittest.main()
