"""La telemetría mide sin estorbar, y no guarda lo que no debe guardar.

Tres cosas que tienen que seguir siendo ciertas:
  1. Medir nunca puede romper lo medido — si el registro falla, el agente igual responde.
  2. El anillo está acotado: un log que crece sin límite termina llenando el disco de
     la máquina que corre producción.
  3. No se guarda el texto de los mensajes. Por el dispatch pasan conversaciones de
     leads reales; un registro con datos personales es un problema legal, no una métrica.
"""
import json
import os
import tempfile
import unittest
from unittest import mock

from zero import telemetry
from zero.agents import build_agents
from zero.memory import SessionMemory
from zero.orchestrator import Zero, _nombre_motor


class TelemetriaBasica(unittest.TestCase):

    def setUp(self):
        telemetry.reset()
        self.addCleanup(telemetry.reset)

    def test_registra_y_devuelve_lo_ultimo_primero(self):
        telemetry.registrar("PROSPECTOR", status="done", ms=12.3, persistir=False)
        telemetry.registrar("QUALIFIER", status="done", ms=4.5, persistir=False)
        evs = telemetry.eventos()
        self.assertEqual([e["agent"] for e in evs], ["QUALIFIER", "PROSPECTOR"])

    def test_el_anillo_esta_acotado(self):
        for i in range(telemetry.MAX_EVENTOS + 40):
            telemetry.registrar("X", status="done", ms=i, persistir=False)
        self.assertEqual(len(telemetry.eventos(limit=10_000)), telemetry.MAX_EVENTOS)

    def test_resumen_usa_mediana_no_promedio(self):
        """Una corrida lenta (el modelo cargándose en VRAM: 22s medidos en vivo el
        2026-08-22) no puede desvirtuar la vista de lo normal."""
        for ms in (100, 110, 120, 22_000):
            telemetry.registrar("CONCIERGE", status="done", ms=ms, persistir=False)
        fila = telemetry.resumen()["agentes"][0]
        self.assertLess(fila["ms_mediana"], 1000)      # la mediana ignora el pico
        self.assertEqual(fila["ms_max"], 22_000)       # pero el pico sigue visible

    def test_cuenta_errores(self):
        telemetry.registrar("OUTREACH", status="error", ms=1, persistir=False)
        telemetry.registrar("OUTREACH", status="done", ms=1, persistir=False)
        self.assertEqual(telemetry.resumen()["agentes"][0]["errores"], 1)

    def test_un_fallo_al_persistir_no_levanta(self):
        """Disco lleno o permisos: la telemetría se pierde, el sistema sigue."""
        with mock.patch("pathlib.Path.write_text", side_effect=OSError("disco lleno")):
            ev = telemetry.registrar("X", status="done", ms=1)
        self.assertEqual(ev["agent"], "X")


class NoGuardaContenido(unittest.TestCase):
    """El registro tiene tamaños, nunca el texto."""

    def setUp(self):
        telemetry.reset()
        self.addCleanup(telemetry.reset)

    def test_el_evento_solo_lleva_tamanos(self):
        ev = telemetry.registrar("CONCIERGE", status="done", ms=5,
                                 in_chars=4166, out_chars=234, persistir=False)
        self.assertEqual(ev["in_chars"], 4166)
        self.assertNotIn("body", ev)
        self.assertNotIn("reply", ev)
        self.assertNotIn("text", ev)

    def test_el_pipeline_real_no_filtra_el_mensaje_del_lead(self):
        secreto = "mi rut es 12.345.678-9 y vivo en Los Alerces 4321"
        with tempfile.TemporaryDirectory() as tmp:
            ruta = os.path.join(tmp, "tele.json")
            with mock.patch.dict(os.environ, {"AGENT_TELEMETRY_PATH": ruta}, clear=False):
                z = Zero(build_agents(mock=True), memory=SessionMemory(None))
                z.converse_result("acme", secreto, lead={"name": "Juan"})
                crudo = open(ruta, encoding="utf-8").read()
        self.assertNotIn("12.345.678-9", crudo)
        self.assertNotIn("Alerces", crudo)
        self.assertIn("CONCIERGE", crudo)          # sí quedó registrada la corrida


class DispatchQuedaMedido(unittest.TestCase):

    def setUp(self):
        telemetry.reset()
        self.addCleanup(telemetry.reset)

    def test_cada_agente_del_pipeline_queda_registrado(self):
        with mock.patch.dict(os.environ, {"AGENT_TELEMETRY_PATH": os.devnull}, clear=False):
            z = Zero(build_agents(mock=True), memory=SessionMemory(None))
            z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=5)
        agentes = {e["agent"] for e in telemetry.eventos(limit=50)}
        self.assertIn("PROSPECTOR", agentes)
        self.assertIn("QUALIFIER", agentes)

    def test_registra_el_motor_que_respondio(self):
        with mock.patch.dict(os.environ, {"AGENT_TELEMETRY_PATH": os.devnull}, clear=False):
            z = Zero(build_agents(mock=True), memory=SessionMemory(None))
            z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=3)
        self.assertTrue(all(e["engine"] == "mock" for e in telemetry.eventos(limit=50)))

    def test_un_registro_roto_no_tumba_el_dispatch(self):
        """La regla que más importa: medir es secundario frente a responderle a un lead."""
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        with mock.patch("zero.telemetry.registrar", side_effect=RuntimeError("boom")):
            salida = z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=3)
        self.assertTrue(salida)   # el pipeline entregó igual


class NombreDelMotor(unittest.TestCase):

    def test_mock_se_reporta_como_mock(self):
        agente = build_agents(mock=True)["PROSPECTOR"]
        self.assertEqual(_nombre_motor(agente), "mock")

    def test_backend_local_reporta_su_modelo(self):
        from zero.backends import LocalBackend
        agente = build_agents(backend=LocalBackend(model="qwen2.5:14b"), mock=False)["CONCIERGE"]
        self.assertEqual(_nombre_motor(agente), "qwen2.5:14b")

    def test_un_backend_raro_no_revienta(self):
        class Raro:
            backend = object()
            mock = False
        self.assertIsInstance(_nombre_motor(Raro()), str)


if __name__ == "__main__":
    unittest.main()
