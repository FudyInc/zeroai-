"""Pruebas del arnés de la etapa 0 (`scripts/evaluar_linea_base.py`).

Se prueban las partes puras: leer el contexto con que Ollama tiene cargado el
modelo, y resumir una corrida. Son las dos que, si se equivocan, hacen que el
informe mienta — y el informe es todo el entregable de esta etapa.

El arnés en sí no se prueba acá: necesita modelo y GPU. Lo que sí se garantiza
es que no pueda enviar nada, porque reemplaza `_deliver` antes de correr.
"""
import importlib.util
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "evaluar_linea_base", REPO / "scripts" / "evaluar_linea_base.py")
arnes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(arnes)

SALIDA_REAL = (
    "NAME         ID              SIZE      PROCESSOR    CONTEXT    UNTIL              \n"
    "qwen3:14b    bdbd181c33f2    9.6 GB    100% GPU     4096       4 minutes from now \n"
)


class ContextoCargado(unittest.TestCase):
    def test_lee_la_columna_context(self):
        self.assertEqual(arnes.contexto_de_salida(SALIDA_REAL, "qwen3:14b"), 4096)

    def test_no_confunde_el_contexto_con_la_hora(self):
        # El bug que tuvo esta función: buscar el último número de la línea
        # devolvía el «4» de «4 minutes from now».
        self.assertNotEqual(arnes.contexto_de_salida(SALIDA_REAL, "qwen3:14b"), 4)

    def test_sin_el_modelo_cargado_devuelve_nada(self):
        self.assertIsNone(arnes.contexto_de_salida(SALIDA_REAL, "llama3:8b"))

    def test_una_salida_vacia_no_revienta(self):
        self.assertIsNone(arnes.contexto_de_salida("", "qwen3:14b"))

    def test_una_salida_sin_encabezado_no_revienta(self):
        self.assertIsNone(arnes.contexto_de_salida("qwen3:14b 4096", "qwen3:14b"))


def _fila(tokens, latencia, limpio=True, handoff=False, error="", familia=None):
    return {
        "latencia_s": latencia, "manual_review": handoff, "error": error,
        "uso": {"prompt_tokens": tokens},
        "rubrica": {"limpio": limpio,
                    "hallazgos": {familia: ["x"]} if familia else {}},
    }


class Resumen(unittest.TestCase):
    def test_cuenta_limpios_errores_y_handoff(self):
        filas = [_fila(1000, 1.0), _fila(2000, 2.0, limpio=False, familia="cifras_inventadas"),
                 _fila(0, 3.0, error="boom"), _fila(1500, 4.0, handoff=True)]
        r = arnes.resumir(filas, 4096, 0)
        self.assertEqual(r["casos"], 4)
        self.assertEqual(r["errores"], 1)
        self.assertEqual(r["handoff"], 1)
        self.assertEqual(r["hallazgos_por_familia"], {"cifras_inventadas": 1})

    def test_un_turno_con_error_no_cuenta_como_limpio(self):
        r = arnes.resumir([_fila(0, 1.0, error="boom")], 4096, 0)
        self.assertEqual(r["limpios"], 0)

    def test_cuenta_los_turnos_que_rozan_el_limite_de_contexto(self):
        # 3700 sobre 4096 es el 90%: ahí el truncado deja de ser hipotético.
        filas = [_fila(1000, 1.0), _fila(3700, 1.0), _fila(4000, 1.0)]
        self.assertEqual(arnes.resumir(filas, 4096, 0)["turnos_rozando_el_limite"], 2)

    def test_sin_contexto_conocido_no_inventa_el_conteo(self):
        filas = [_fila(4000, 1.0)]
        self.assertEqual(arnes.resumir(filas, None, 0)["turnos_rozando_el_limite"], 0)

    def test_los_percentiles_de_latencia(self):
        filas = [_fila(100, v) for v in (1.0, 2.0, 3.0, 4.0, 100.0)]
        r = arnes.resumir(filas, 4096, 0)
        self.assertEqual(r["latencia_p50"], 3.0)
        self.assertEqual(r["latencia_p95"], 100.0)

    def test_los_turnos_sin_tokens_no_hunden_el_minimo(self):
        # Un turno resuelto sin modelo (catálogo, saludo) no reporta tokens;
        # contarlo como 0 haría ver el prompt más chico de lo que es.
        filas = [_fila(None, 1.0), _fila(2200, 1.0)]
        self.assertEqual(arnes.resumir(filas, 4096, 0)["prompt_tokens_min"], 2200)

    def test_una_corrida_vacia_no_revienta(self):
        r = arnes.resumir([], 4096, 0)
        self.assertEqual(r["casos"], 0)
        self.assertIsNone(r["prompt_tokens_max"])


class NoEnvia(unittest.TestCase):
    def test_el_arnes_documenta_que_reemplaza_deliver(self):
        # Garantía estructural: si alguien quita esa línea, esta prueba cae.
        fuente = (REPO / "scripts" / "evaluar_linea_base.py").read_text(encoding="utf-8")
        self.assertIn("zero._deliver = _registrar", fuente)

    def test_el_arnes_no_construye_el_respaldo_pagado(self):
        # En producción, si Ollama cae contesta Claude por API. En una medición
        # eso sería gastar plata sin pedirlo, y además mediría otro modelo.
        # Se busca la construcción, no la palabra: el docstring la nombra para
        # explicar por qué no está.
        fuente = (REPO / "scripts" / "evaluar_linea_base.py").read_text(encoding="utf-8")
        self.assertNotIn("FallbackBackend(", fuente)
        self.assertNotIn("AnthropicBackend", fuente)
        self.assertNotIn("OpenAIBackend", fuente)


if __name__ == "__main__":
    unittest.main()
