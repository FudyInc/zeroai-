"""El avance de una corrida, mientras corre (zero/runs.py + el hilo de progreso).

Hasta hoy el dashboard solo podía mostrar el resultado final: `POST /api/pipeline`
abre la request, corre el pipeline entero y responde al terminar. Durante los minutos
que de verdad tarda, no había nada que consultar — ni en telemetry.py, que registra
por agente y no por empresa.

Lo que se prueba acá es el registro y que el orquestador lo alimente de verdad
corriendo el pipeline en mock. Sin red, sin CRM real: SessionMemory y CRM en memoria.

Run: python3 -m unittest tests.test_runs -v
"""
from __future__ import annotations

import unittest
from unittest import mock

from zero import runs
from zero.agents import build_agents
from zero.crm import CRM
from zero.memory import SessionMemory
from zero.orchestrator import Zero


class RegistroDeCorridas(unittest.TestCase):

    def setUp(self):
        runs.olvidar_todo()
        self.addCleanup(runs.olvidar_todo)

    def test_una_corrida_nace_corriendo(self):
        r = runs.crear("acme", "piscinas", "GROWTH")
        p = runs.progreso(r)
        self.assertEqual(p["estado"], runs.CORRIENDO)
        self.assertEqual(p["fase"], "descubriendo")
        self.assertEqual(p["leads"], [])

    def test_una_empresa_avanza_de_etapa_sin_duplicarse(self):
        r = runs.crear("acme", "piscinas")
        runs.anotar(r, "PoolEdge SpA", runs.DESCUBIERTA)
        runs.anotar(r, "PoolEdge SpA", runs.CALIFICADA, score=82)
        p = runs.progreso(r)
        self.assertEqual(len(p["leads"]), 1)
        self.assertEqual(p["leads"][0]["etapa"], runs.CALIFICADA)
        self.assertEqual(p["leads"][0]["score"], 82)

    def test_los_conteos_son_los_que_pinta_el_encabezado(self):
        r = runs.crear("acme", "piscinas")
        for empresa, etapa in (("A", runs.LISTA), ("B", runs.APROBADA),
                               ("C", runs.DESCARTADA), ("D", runs.DESCUBIERTA)):
            runs.anotar(r, empresa, etapa)
        p = runs.progreso(r)
        self.assertEqual((p["encontradas"], p["calificadas"], p["descartadas"], p["listas"]),
                         (4, 2, 1, 1))

    def test_el_orden_no_baila_entre_refrescos(self):
        """Una lista que se reordena sola en cada consulta es ilegible mientras corre."""
        r = runs.crear("acme", "piscinas")
        runs.anotar(r, "Atrasada", runs.DESCUBIERTA)
        runs.anotar(r, "Adelantada", runs.LISTA)
        etapas = [f["etapa"] for f in runs.progreso(r)["leads"]]
        self.assertEqual(etapas, [runs.LISTA, runs.DESCUBIERTA])
        self.assertEqual(etapas, [f["etapa"] for f in runs.progreso(r)["leads"]])

    def test_terminar_cierra_la_corrida(self):
        r = runs.crear("acme", "piscinas")
        runs.terminar(r, resumen={"qualified": 3})
        p = runs.progreso(r)
        self.assertEqual((p["estado"], p["fase"]), (runs.TERMINADA, "listo"))
        self.assertEqual(p["resumen"]["qualified"], 3)
        self.assertIsNotNone(p["terminada"])

    def test_un_pipeline_que_revienta_deja_la_corrida_en_error(self):
        """Si no, el dashboard gira un spinner que no termina nunca."""
        r = runs.crear("acme", "piscinas")
        runs.terminar(r, error="discovery se cayó")
        p = runs.progreso(r)
        self.assertEqual(p["estado"], runs.ERROR)
        self.assertEqual(p["error"], "discovery se cayó")

    def test_anotar_sobre_una_corrida_desconocida_no_revienta(self):
        runs.anotar("r_no-existe", "X", runs.LISTA)
        runs.fase("r_no-existe", "listo")
        runs.terminar("r_no-existe")
        self.assertIsNone(runs.progreso("r_no-existe"))

    def test_el_anillo_olvida_las_viejas_pero_no_la_que_corre(self):
        with mock.patch("zero.runs.MAX_CORRIDAS_RECORDADAS", 3):
            viva = runs.crear("acme", "la que sigue corriendo")
            for i in range(6):
                r = runs.crear("acme", f"vieja {i}")
                runs.terminar(r)
            self.assertIsNotNone(runs.progreso(viva), "se olvidó una corrida en curso")
            self.assertLessEqual(len(runs.ultimas(50)), 4)


class ElPipelineReportaSuAvance(unittest.TestCase):
    """El orquestador alimenta el registro de verdad, corriendo en mock."""

    def setUp(self):
        runs.olvidar_todo()
        self.addCleanup(runs.olvidar_todo)
        self.zero = Zero(build_agents(mock=True), memory=SessionMemory(), crm=CRM())

    def _correr(self):
        eventos = []
        self.zero.run_pipeline("acme", "GROWTH", "piscinas en Santiago", count=5,
                               auto_send=False, on_progress=lambda **d: eventos.append(d))
        return eventos

    def test_reporta_fases_y_empresas(self):
        eventos = self._correr()
        fases = [e["fase"] for e in eventos if "fase" in e]
        self.assertEqual(fases[0], "descubriendo")
        self.assertEqual(fases[-1], "listo")
        self.assertIn("validando", fases)
        empresas = [e for e in eventos if "empresa" in e]
        self.assertTrue(empresas, "ninguna empresa reportó avance")
        self.assertTrue(any(e["etapa"] == "descubierta" for e in empresas))
        self.assertTrue(any(e["etapa"] in ("aprobada", "descartada") for e in empresas))

    def test_el_puntaje_viaja_con_la_empresa(self):
        """Es lo que la celda muestra al lado del nombre."""
        calificadas = [e for e in self._correr()
                       if e.get("etapa") == "calificada" and e.get("score") is not None]
        self.assertTrue(calificadas)

    def test_una_descartada_dice_por_que(self):
        motivos = [e.get("motivo") for e in self._correr() if e.get("etapa") == "descartada"]
        if motivos:                      # el mock puede aprobarlas todas según el ICP
            self.assertTrue(all(m for m in motivos), "una descartada sin motivo no se puede leer")

    def test_un_observador_roto_no_tumba_la_corrida(self):
        """Avisar es secundario: si el observador falla se pierde una animación, no
        el trabajo."""
        def revienta(**_):
            raise RuntimeError("el dashboard se cayó")
        out = self.zero.run_pipeline("acme", "GROWTH", "piscinas", count=3,
                                     auto_send=False, on_progress=revienta)
        self.assertIn("summary", out)

    def test_sin_observador_todo_sigue_igual(self):
        """Nadie que no pase on_progress nota diferencia."""
        out = self.zero.run_pipeline("acme", "GROWTH", "piscinas", count=3, auto_send=False)
        self.assertIn("qualified_leads", out)


if __name__ == "__main__":
    unittest.main()
