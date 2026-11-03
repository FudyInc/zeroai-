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


class PruebaDiariaDelAgente(unittest.TestCase):
    """La última prueba COMPLETA de zero-golden se lee del journal; si es vieja, se relanza.

    Mira el resultado, no la intención: el timer puede haber "disparado" en un arranque
    efímero de WSL que la mató con 'signal'. Eso no cuenta como corrida."""

    AHORA = 1_800_000_000.0

    def setUp(self):
        self.salud = _cargar()

    def _correr(self, ultima, estado="inactive", arranque=None, start_rc=0, journal_rc=0):
        llamadas = []

        def run(cmd, **kw):
            llamadas.append(cmd)
            if cmd[0] == "journalctl":
                out = "" if ultima is None else '{"__REALTIME_TIMESTAMP": "%d"}\n' % int(ultima * 1e6)
                return mock.Mock(returncode=journal_rc, stdout=out, stderr="sin journal")
            if "show" in cmd:
                ts = "" if arranque is None else f"@{arranque:.0f}"
                return mock.Mock(returncode=0, stdout=f"ActiveState={estado}\nInactiveExitTimestamp={ts}\n")
            return mock.Mock(returncode=start_rc, stdout="", stderr="Unit not found")

        with mock.patch.object(self.salud.subprocess, "run", side_effect=run), \
             mock.patch.object(self.salud.time, "time", return_value=self.AHORA):
            fallas = self.salud._prueba_diaria()
        self.starts = [c for c in llamadas if "start" in c]
        return fallas

    def _urgentes(self, fallas):
        return [f for f in fallas if not f.startswith(self.salud.NO_URGENTE)]

    def test_corrida_reciente_no_hace_nada(self):
        self.assertEqual(self._correr(self.AHORA - 3 * 3600), [])
        self.assertEqual(self.starts, [])

    def test_registro_viejo_se_detecta_y_se_relanza_sin_avisar_si_es_un_atraso(self):
        fallas = self._correr(self.AHORA - 30 * 3600)
        self.assertEqual(self.starts, [["systemctl", "--user", "start", "--no-block", "zero-golden.service"]])
        self.assertEqual(self._urgentes(fallas), [])
        self.assertIn("relanzada", fallas[0])

    def test_dias_sin_corrida_completa_es_urgente_con_texto_estable(self):
        f1 = self._correr(self.AHORA - 6 * 86400)
        f2 = self._correr(self.AHORA - 6 * 86400, arranque=self.AHORA - 1800)   # 30 min después, ya relanzada
        self.assertEqual(len(self._urgentes(f1)), 1)
        self.assertEqual(self._urgentes(f1), self._urgentes(f2))   # mismo aviso → mismo antirrebote
        self.assertIn("sin corrida completa desde", self._urgentes(f1)[0])

    def test_nunca_completo_es_urgente(self):
        fallas = self._correr(None)
        self.assertIn("nunca completó", self._urgentes(fallas)[0])
        self.assertEqual(len(self.starts), 1)

    def test_no_relanza_si_esta_corriendo_o_se_relanzo_hace_poco(self):
        self._correr(self.AHORA - 30 * 3600, estado="activating")
        self.assertEqual(self.starts, [])
        self._correr(self.AHORA - 30 * 3600, arranque=self.AHORA - 600)
        self.assertEqual(self.starts, [])
        self._correr(self.AHORA - 30 * 3600, arranque=self.AHORA - 3 * 3600)
        self.assertEqual(len(self.starts), 1)

    def test_journal_ilegible_o_relanzar_falla_son_fallas_urgentes(self):
        fallas = self._correr(None, journal_rc=1)
        self.assertIn("journal", self._urgentes(fallas)[0])
        fallas = self._correr(self.AHORA - 30 * 3600, start_rc=5)
        self.assertIn("no se pudo relanzar", self._urgentes(fallas)[0])

    def test_revisar_incluye_la_prueba_diaria(self):
        self.assertIn("_prueba_diaria()", _RUTA.read_text())
