"""Cuando la tanda aborta, avisa. Es el único monitoreo que hay.

Fallo medido, no supuesto: el ciclo autónomo estuvo OCHO DÍAS sin ejecutar una sola
tarea —abortado por un crm.json dentro de un workspace— y nadie se enteró.

    journalctl --user -u zero-dia.service --since <cualquiera de esos días> | grep -ci aviso
    → 0

La causa era de forma, no de lógica: el `return 2` de la puerta de aislamiento salía
ANTES del único notify_owner del archivo, que además vivía detrás de `--avisar`, un flag
que scripts/dia.sh no pasaba. Los dos extremos estaban bien escritos; nunca se tocaban.

Por eso el aviso del aborto NO depende de `--avisar`: sale por ser un aborto. Estos
tests fijan justamente eso, y que el simulacro siga sin gastar un mensaje.

Run: python3 -m unittest tests.test_tanda_aviso -v
"""
import importlib.util
import pathlib
import unittest
from unittest import mock

_ruta = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "tanda.py"
_spec = importlib.util.spec_from_file_location("tanda", _ruta)
tanda = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tanda)


class AvisoAlAbortar(unittest.TestCase):
    """El camino de aborto se prueba acá y solo acá: ensuciar un workspace de verdad
    con un .env falso deja una bomba puesta si alguien olvida borrarlo."""

    def _correr(self, argv, intrusos):
        """Corre main() con los intrusos que se le digan, sin tocar nada real.

        `revisar_aislamiento` se sustituye para no depender de qué haya hoy en los
        worktrees, y `notify_owner` se parchea en zero.alerts —no en tanda— porque
        tanda lo importa dentro de la función, en el momento de usarlo.
        """
        with mock.patch.object(tanda, "revisar_aislamiento", return_value=intrusos), \
             mock.patch.object(tanda, "load_env"), \
             mock.patch.object(tanda.tasks, "liberar_colgadas", return_value=[]), \
             mock.patch.object(tanda.tasks, "tomar", return_value=None), \
             mock.patch.object(tanda, "sincronizar") as sincronizar, \
             mock.patch("zero.alerts.notify_owner") as avisar, \
             mock.patch("sys.argv", ["tanda.py", *argv]):
            codigo = tanda.main()
        return codigo, avisar, sincronizar

    def test_el_aborto_en_corrida_real_avisa(self):
        codigo, avisar, _ = self._correr(["--ejecutar"], ["dashboard/crm.json"])
        self.assertEqual(codigo, 2)
        avisar.assert_called_once()
        texto = avisar.call_args.args[0]
        self.assertIn("dashboard/crm.json", texto)      # dice DÓNDE, no solo que falló

    def test_el_aviso_del_aborto_no_depende_de_avisar(self):
        """`--avisar` es lo que faltaba en dia.sh y produjo el silencio. Que el aborto
        vuelva a depender de un flag sería repetir el mismo fallo."""
        _, avisar, _ = self._correr(["--ejecutar"], ["core/.env"])
        avisar.assert_called_once()

    def test_el_aborto_usa_su_propio_kind(self):
        """notify_owner separa las ventanas de antirrebote por `kind`: con el mismo que
        el resumen de éxito, una tanda buena reciente se tragaría el aviso de que la
        máquina está muerta."""
        _, avisar, _ = self._correr(["--ejecutar"], ["core/.env"])
        self.assertEqual(avisar.call_args.kwargs.get("kind"), "tanda-abortada")

    def test_en_simulacro_no_se_manda_nada(self):
        """Probar a mano no puede gastar mensajes; el código de salida sí es 2 igual."""
        codigo, avisar, sincronizar = self._correr([], ["core/.env"])
        self.assertEqual(codigo, 2)
        avisar.assert_not_called()
        sincronizar.assert_not_called()

    def test_sin_intrusos_el_camino_normal_no_cambia(self):
        """Sin cola y sin intrusos: sale 0, no avisa por aborto, y no se inventa nada."""
        codigo, avisar, _ = self._correr([], [])
        self.assertEqual(codigo, 0)
        avisar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
