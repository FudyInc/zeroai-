"""El antirrebote de los avisos tiene que valer ENTRE procesos, no solo dentro de uno.

Fallo medido, y caro para Diego: el 2026-09-08 recibió **69 correos y 69 WhatsApp en 24
horas**, uno cada 5,6 minutos, en su cuenta personal.

    $ journalctl --user -u zero-sync-workspaces.service --since "24 hours ago" \\
        | grep -c "sent"
    69

La ventana de 30 minutos (`ALERT_THROTTLE_MINUTES`) existía y no se aplicó ni una sola
vez. El estado vivía en un dict de módulo, con este razonamiento escrito al lado: *"el
backend es un proceso largo (systemd, Restart=always), así que la ventana sobrevive lo que
tiene que sobrevivir"*.

Era cierto para el backend, y falso para los otros SEIS que llaman a `notify_owner`:
tanda.py, planificar.py, probar-agente.py, revisar-salud.py, dia.sh y
sincronizar-workspaces.sh son procesos que nacen, avisan y mueren. Cada uno arrancaba con
el dict vacío. Uno de ellos —el sync— corre por timer cada 5 minutos.

Uno de siete llamadores cumplía la premisa. Es la misma forma de los otros defectos de
instrumentación de estas semanas: correcto donde se escribió, silenciosamente falso en
todos los demás lugares desde donde se usa.

Run: python3 -m unittest tests.test_alerts_antirrebote -v
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zero import alerts


class _OutboxQueRegistra:
    """Outbox de prueba: cuenta envíos sin tocar Twilio ni SMTP."""

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)
        return {"status": "sent", "to": msg.get("to")}


class AntirreboteEntreProcesos(unittest.TestCase):

    CANALES = {"OWNER_WHATSAPP_TO": "", "OWNER_EMAIL_TO": "duenio@zeroai.cl",
               "SMTP_FROM": "", "SMTP_USER": ""}

    def setUp(self):
        self.archivo = Path(tempfile.mkdtemp()) / "alertas.json"
        self._env = mock.patch.dict(
            os.environ, {**self.CANALES, "ALERTAS_PATH": str(self.archivo)}, clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)
        alerts.reset_throttle()
        self.addCleanup(alerts.reset_throttle)

    def _proceso_nuevo(self, texto="algo pasa", kind="sync-workspaces"):
        """Simula un proceso recién nacido: memoria vacía, disco intacto.

        Es exactamente lo que hace el timer cada 5 minutos, y lo que el dict de módulo
        no podía representar.
        """
        alerts._last_sent.clear()
        box = _OutboxQueRegistra()
        return alerts.notify_owner(texto, kind=kind, outbox=box), box

    def test_el_segundo_proceso_no_vuelve_a_avisar(self):
        """EL TEST QUE IMPORTA. Sin él, el timer manda 288 avisos al día."""
        r1, box1 = self._proceso_nuevo()
        self.assertEqual(r1["status"], "sent")
        self.assertEqual(len(box1.sent), 1)

        r2, box2 = self._proceso_nuevo()
        self.assertEqual(r2["status"], "throttled",
                         "un proceso nuevo volvió a avisar: el antirrebote no cruza procesos")
        self.assertEqual(box2.sent, [], "se mandó un mensaje que debía frenarse")

    def test_doce_corridas_seguidas_mandan_un_solo_aviso(self):
        """Una hora de timer cada 5 minutos. Antes daban 12 correos y 12 WhatsApp."""
        enviados = 0
        for _ in range(12):
            r, _box = self._proceso_nuevo()
            enviados += r["status"] == "sent"
        self.assertEqual(enviados, 1, f"salieron {enviados} avisos donde debía salir 1")

    def test_pasada_la_ventana_vuelve_a_avisar(self):
        """El antirrebote calla, no amordaza: cumplida la ventana el aviso sale."""
        self._proceso_nuevo()
        alerts._last_sent.clear()
        futuro = json.loads(self.archivo.read_text())["sync-workspaces"] + 31 * 60
        r, box = (alerts.notify_owner("algo pasa", kind="sync-workspaces",
                                      outbox=_OutboxQueRegistra(), now=futuro), None)
        self.assertEqual(r["status"], "sent")

    def test_kinds_distintos_no_se_tapan(self):
        """Dos problemas distintos se avisan los dos, aunque caigan juntos — si no, un
        aviso rutinario se traga el de que la máquina está muerta."""
        r1, _ = self._proceso_nuevo(kind="sync-workspaces")
        r2, _ = self._proceso_nuevo(kind="tanda-abortada")
        self.assertEqual((r1["status"], r2["status"]), ("sent", "sent"))

    def test_la_ruta_no_depende_del_directorio_actual(self):
        """La misma trampa que `main.py --crm`, que escribía crm.json en el cwd y dejó la
        tanda bloqueada ocho días. Los seis llamadores corren desde directorios distintos:
        una ruta relativa daría un archivo por cwd, o sea ningún antirrebote compartido."""
        with mock.patch.dict(os.environ, {"ALERTAS_PATH": ""}, clear=False):
            ruta = alerts._ruta_estado()
        self.assertTrue(ruta.is_absolute(), f"ruta relativa al cwd: {ruta}")
        self.assertEqual(ruta.name, "alertas.json")

    def test_un_archivo_corrupto_deja_pasar_el_aviso(self):
        """Degradar hacia avisar de más, nunca hacia el silencio: perder el primer aviso
        de una caída real es peor que un aviso repetido."""
        self.archivo.write_text("{roto", encoding="utf-8")
        alerts._last_sent.clear()
        r, box = self._proceso_nuevo()
        self.assertEqual(r["status"], "sent")
        self.assertEqual(len(box.sent), 1)

    def test_no_poder_escribir_no_tumba_el_aviso(self):
        """Un antirrebote que no puede grabar no puede impedir que se avise."""
        with mock.patch.object(alerts, "_grabar_estado",
                               side_effect=OSError("disco lleno")):
            with self.assertRaises(OSError):
                alerts._grabar_estado("x", 0.0)      # el mock lanza; el real no
        alerts._last_sent.clear()
        with mock.patch.object(alerts, "_ruta_estado",
                               return_value=Path("/proc/no-se-puede-escribir/alertas.json")):
            r, box = self._proceso_nuevo()
        self.assertEqual(r["status"], "sent")
        self.assertEqual(len(box.sent), 1)


if __name__ == "__main__":
    unittest.main()
