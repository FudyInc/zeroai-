"""Pruebas del arnés de la etapa 0 (`scripts/evaluar_linea_base.py`).

Se prueban las partes puras: leer el contexto con que Ollama tiene cargado el
modelo, y resumir una corrida. Son las dos que, si se equivocan, hacen que el
informe mienta — y el informe es todo el entregable de esta etapa.

El arnés en sí no se prueba acá: necesita modelo y GPU. Lo que sí se garantiza
es que no pueda enviar nada: reemplaza `_deliver`, simula el puente de WhatsApp
Web y bloquea toda salida de red que no vaya al motor local —socket y SMTP
incluidos, no solo `urlopen`—.
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


def _expectativas(test, casos):
    import json, os, tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"casos": casos}, f)
    test.addCleanup(os.unlink, f.name)
    return f.name


class Expectativas(unittest.TestCase):
    CASO = {"id": "c-569123456-001", "mensaje": "que modelos hay?",
            "historial": [{"role": "agent", "text": "¿Medidas?"}]}

    def test_se_pegan_por_huella_y_no_por_id(self):
        ruta = _expectativas(self, {arnes.huella(self.CASO): {"entiende": "pregunta"}})
        otro = {**self.CASO, "mensaje": "hola"}
        casos = arnes.con_expectativas([self.CASO, otro], ruta)
        self.assertEqual(casos[0]["esperado"]["entiende"], "pregunta")
        self.assertNotIn("esperado", casos[1])

    def test_la_huella_cambia_si_cambia_lo_que_se_le_dijo(self):
        # Si la ventana de memoria corre el historial, la anotación no se
        # pega a otro mensaje: queda huérfana y se avisa.
        movido = {**self.CASO, "historial": [{"role": "agent", "text": "¿Color?"}]}
        self.assertNotEqual(arnes.huella(self.CASO), arnes.huella(movido))

    def test_la_huella_no_lleva_el_telefono(self):
        self.assertNotIn("123456", arnes.huella(self.CASO))

    def test_una_anotacion_huerfana_se_avisa(self):
        import contextlib, io
        ruta = _expectativas(self, {"000000000000": {"entiende": "saludo"}})
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            arnes.con_expectativas([self.CASO], ruta)
        self.assertIn("1 anotaciones sin caso", error.getvalue())

    def test_un_patron_invalido_falla_al_cargar(self):
        ruta = _expectativas(self, {"x": {"chequeos": {"debe": ["(?i)abre("]}}})
        with self.assertRaises(ValueError):
            arnes.con_expectativas([self.CASO], ruta)

    def test_el_archivo_versionado_compila_entero(self):
        ruta = REPO / "docs" / "evaluacion" / "expectativas-whatsapp.json"
        import json
        anotados = json.loads(ruta.read_text(encoding="utf-8"))["casos"]
        self.assertGreater(len(anotados), 0)
        import re
        for clave, esperado in anotados.items():
            self.assertRegex(clave, r"^[0-9a-f]{12}$")
            for patron in esperado["chequeos"].get("debe", []) + esperado["chequeos"].get("no_debe", []):
                re.compile(patron)


class Resumen(unittest.TestCase):
    def test_cuenta_limpios_errores_y_handoff(self):
        filas = [_fila(1000, 1.0), _fila(2000, 2.0, limpio=False, familia="cifras_inventadas"),
                 _fila(0, 3.0, error="boom"), _fila(1500, 4.0, handoff=True)]
        r = arnes.resumir(filas, 4096, 0)
        self.assertEqual(r["casos"], 4)
        self.assertEqual(r["errores"], 1)
        self.assertEqual(r["handoff"], 1)
        self.assertEqual(r["hallazgos_por_familia"], {"cifras_inventadas": 1})

    def test_cuenta_los_anotados_y_los_entendidos(self):
        bien = {**_fila(100, 1.0), "entiende": "saludo"}
        mal = {**_fila(100, 1.0, limpio=False, familia="no_entendio"), "entiende": "pregunta"}
        r = arnes.resumir([bien, mal, _fila(100, 1.0)], 4096, 0)
        self.assertEqual((r["anotados"], r["entendidos"]), (2, 1))

    def test_un_turno_caido_no_cuenta_como_no_entendido(self):
        caida = {**_fila(0, 1.0, limpio=False, error="boom", familia="no_entendio"),
                 "entiende": "saludo"}
        r = arnes.resumir([caida], 4096, 0)
        self.assertEqual(r["hallazgos_por_familia"], {})
        self.assertEqual((r["anotados"], r["entendidos"]), (0, 0))

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


class SinSalidaAlMundo(unittest.TestCase):
    """El 2026-10-30 el arnés publicó borradores de prueba en el grupo de
    revisión real: el borrador sale por el puente, no por `_deliver`."""

    def test_la_red_solo_deja_pasar_al_motor(self):
        llamadas = []
        red = arnes.RedSoloMotor("http://localhost:11434/v1",
                                 original=lambda req, *a, **k: llamadas.append(req) or "ok")
        self.assertEqual(red("http://localhost:11434/v1/chat/completions"), "ok")
        for url in ("http://127.0.0.1:8810/send-group",          # el puente: mismo host, otro puerto
                    "https://graph.facebook.com/v20.0/x/messages",
                    "https://abc.supabase.co/rest/v1/clients"):
            with self.assertRaises(arnes.urllib.error.URLError):
                red(arnes.urllib.request.Request(url, data=b"{}"))
        self.assertEqual(len(llamadas), 1)
        self.assertEqual(len(red.bloqueados), 3)

    def test_el_puente_simulado_anota_y_no_envia(self):
        puente = arnes.PuenteSimulado("+56 9 6453 7891")
        self.assertEqual(puente("/status"), {"state": "ready", "account": "56964537891"})
        respuesta = puente("/send-group", {"group_id": "g", "text": "borrador"})
        self.assertEqual(respuesta["ack"], 1)
        self.assertEqual(puente.enviados, [{"path": "/send-group",
                                            "body": {"group_id": "g", "text": "borrador"}}])

    def test_aislar_cierra_toda_salida_salvo_el_motor(self):
        """Se prueba el efecto, no el texto: abre un "motor" de verdad en un puerto
        local y comprueba qué conecta y qué no, por cada puerta conocida."""
        import os, smtplib, socket, tempfile
        from zero import channels, whatsapp_web

        motor = socket.socket()
        motor.bind(("127.0.0.1", 0))
        motor.listen(1)
        puerto = motor.getsockname()[1]
        self.addCleanup(motor.close)
        previos = (whatsapp_web.bridge_request, socket.socket.connect, smtplib.SMTP)
        tmp = Path(tempfile.mkdtemp())
        os.environ["OUTBOX_LIVE"] = "1"              # como lo trae el .env de producción
        self.addCleanup(os.environ.pop, "OUTBOX_LIVE", None)

        salidas, restaurar = arnes.aislar(tmp, f"http://127.0.0.1:{puerto}/v1", "56900000001")
        try:
            permitido = socket.create_connection(("127.0.0.1", puerto), timeout=2)
            permitido.close()
            with self.assertRaises(OSError):         # el puente real: mismo host, otro puerto
                socket.create_connection(("127.0.0.1", 8810), timeout=2)
            with self.assertRaises(arnes.urllib.error.URLError):
                arnes.urllib.request.urlopen("https://graph.facebook.com/v20.0/x")
            with self.assertRaises(smtplib.SMTPException):   # el aviso al dueño
                smtplib.SMTP("smtp.gmail.com", 587)
            self.assertEqual(channels.make_outbox().real, {})   # sin remitentes reales
            whatsapp_web.bridge_request("/send-group", {"group_id": "g", "text": "borrador"})
            self.assertEqual(salidas["puente"][0]["path"], "/send-group")
            self.assertTrue(os.environ["ALERTAS_PATH"].startswith(str(tmp)))
            self.assertTrue(os.environ["AGENT_TELEMETRY_PATH"].startswith(str(tmp)))
            self.assertEqual(len(salidas["red"]), 3)
        finally:
            restaurar()
        self.assertEqual((whatsapp_web.bridge_request, socket.socket.connect, smtplib.SMTP),
                         previos)
        self.assertEqual(os.environ["OUTBOX_LIVE"], "1")
        self.assertNotIn("ALERTAS_PATH", os.environ)


class LoQueLeyoElCliente(unittest.TestCase):
    def test_suma_imagen_y_encuesta_enviadas_por_el_puente(self):
        puente = [
            {"path": "/send-catalog-image", "body": {"to": "56900000003", "caption": "Te comparto la gama"}},
            {"path": "/send-poll", "body": {"to": "56900000003", "poll_key": "color"}},
        ]
        texto = arnes.lo_que_leyo_el_cliente({"reply": ""}, [], puente, "56900000003")
        self.assertIn("Te comparto la gama", texto)
        self.assertIn("¿Qué color prefieres?", texto)
        self.assertIn("Anaranjado", texto)

    def test_suma_lo_entregado_por_deliver_sin_duplicar(self):
        deliver = [{"to": "56900000003", "body": "Tu presupuesto está pendiente de revisión"}]
        texto = arnes.lo_que_leyo_el_cliente(
            {"reply": "Tu presupuesto está pendiente de revisión"}, deliver, [], "56900000003")
        self.assertEqual(texto, "Tu presupuesto está pendiente de revisión")

    def test_el_grupo_de_revision_no_cuenta_como_respuesta(self):
        puente = [{"path": "/send-group", "body": {"group_id": "g", "text": "PRESUPUESTO interno"}}]
        deliver = [{"to": "56900000099", "body": "a otro cliente"}]
        self.assertEqual(arnes.lo_que_leyo_el_cliente({}, deliver, puente, "56900000003"), "")

    def test_encuesta_de_despacho(self):
        puente = [{"path": "/send-delivery-poll", "body": {"to": "56900000003"}}]
        self.assertIn("Retiro en fábrica",
                      arnes.lo_que_leyo_el_cliente({}, [], puente, "56900000003"))


if __name__ == "__main__":
    unittest.main()
