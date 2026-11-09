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


class LeerFicha(unittest.TestCase):
    def test_lee_desde_la_raiz_sin_cambiar_el_codigo_que_se_evalua(self):
        import os
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as raiz:
            # Un paquete `zero` falso en la raíz: si la raíz entrara al path,
            # una importación nueva lo tomaría y fallaría.
            os.makedirs(os.path.join(raiz, "zero"))
            with open(os.path.join(raiz, "zero", "__init__.py"), "w") as f:
                f.write("raise ImportError('se importó el código de la raíz')\n")
            antes_path, antes_cwd = list(sys.path), os.getcwd()
            ficha, precios, perfil = arnes.leer_ficha(raiz, "nadie")
            self.assertEqual(sys.path, antes_path)
            self.assertEqual(os.getcwd(), antes_cwd)
        self.assertIsInstance(perfil, dict)
        import zero.orchestrator
        self.assertTrue(Path(zero.orchestrator.__file__).resolve().is_relative_to(REPO))

    def test_carga_el_env_de_la_raiz(self):
        # Sin el `.env` de la raíz no hay credenciales de Supabase y la ficha
        # llega vacía. Se usa una clave inocua: nunca credenciales reales.
        import os
        import tempfile
        clave = "ZERO_PRUEBA_ENV_DE_LA_RAIZ"
        os.environ.pop(clave, None)
        try:
            with tempfile.TemporaryDirectory() as raiz:
                with open(os.path.join(raiz, ".env"), "w") as f:
                    f.write(f"{clave}=desde-la-raiz\n")
                arnes.leer_ficha(raiz, "nadie")
            self.assertEqual(os.environ.get(clave), "desde-la-raiz")
        finally:
            os.environ.pop(clave, None)


class SinFichaNoSeCorre(unittest.TestCase):
    def test_ficha_vacia_aborta_antes_de_medir(self):
        import json
        import tempfile
        original = arnes.leer_ficha
        arnes.leer_ficha = lambda raiz, cliente: ("", {}, {})
        try:
            with tempfile.TemporaryDirectory() as tmp:
                conjunto = Path(tmp) / "set.json"
                conjunto.write_text(json.dumps({"casos": [
                    {"client_id": "losetaschile", "mensaje": "hola", "historial": []}]}))
                salida = Path(tmp) / "crudo.jsonl"
                codigo = arnes.main(["--set", str(conjunto), "--salida", str(salida)])
                self.assertEqual(codigo, 1)
                self.assertFalse(salida.exists())
        finally:
            arnes.leer_ficha = original


class ContarTruncados(unittest.TestCase):
    def test_truncated_cero_no_es_un_corte(self):
        log = ("slot release: stop processing: n_tokens = 2248, truncated = 0\n"
               "slot release: stop processing: n_tokens = 2268, truncated = 0\n")
        self.assertEqual(arnes.contar_truncados(log), 0)

    def test_cuenta_los_cortes_reales(self):
        log = ('level=WARN msg="truncating input prompt" limit=2050 prompt=4696\n'
               "slot release: stop processing: n_tokens = 2050, truncated = 1\n"
               "slot release: stop processing: n_tokens = 900, truncated = 0\n")
        self.assertEqual(arnes.contar_truncados(log), 2)




class MotorNubeTest(unittest.TestCase):
    """--motor nube: mide la nube con las mismas barreras y sin contar el límite
    por minuto como falla del modelo."""

    def _modulo(self):
        import importlib.util
        from pathlib import Path
        ruta = Path(__file__).resolve().parent.parent / "scripts" / "evaluar_linea_base.py"
        spec = importlib.util.spec_from_file_location("evaluar_linea_base_nube", ruta)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_nube_sin_key_no_corre(self):
        import os
        from unittest import mock
        mod = self._modulo()
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": ""}, clear=False):
            with self.assertRaises(SystemExit):
                mod.motor_a_medir("nube")

    def test_nube_usa_la_politica_aunque_este_apagada(self):
        import os
        from unittest import mock
        from zero.config import WHATSAPP_ENGINE
        mod = self._modulo()
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk_falsa"}, clear=False):
            modelo, url, key, timeout = mod.motor_a_medir("nube")
        self.assertEqual(modelo, WHATSAPP_ENGINE["cloud"]["model"])
        self.assertEqual(url, WHATSAPP_ENGINE["cloud"]["base_url"])
        self.assertEqual(key, "gsk_falsa")

    def test_429_espera_y_reintenta(self):
        import io
        import json
        import urllib.error
        from unittest import mock
        mod = self._modulo()

        class _Interno:
            base_url, api_key, timeout = "https://nube.test/v1", "k", 5

            def _build_payload(self, s, u, m):
                return {"model": "m", "messages": []}

        respuestas = [
            urllib.error.HTTPError("u", 429, "lento", {"retry-after": "3"}, io.BytesIO(b"")),
            io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok"}}],
                                   "usage": {"prompt_tokens": 10}}).encode()),
        ]

        class _Resp:
            def __init__(self, b): self.b = b
            def read(self): return self.b.read()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def _urlopen(req, timeout=None):
            r = respuestas.pop(0)
            if isinstance(r, Exception):
                raise r
            self.assertEqual(req.get_header("User-agent"), mod.USER_AGENT)
            return _Resp(r)

        esperas = []
        medido = mod.BackendMedido(_Interno(), dormir=esperas.append)
        with mock.patch("urllib.request.urlopen", _urlopen):
            self.assertEqual(medido.complete("s", "u", "m"), "ok")
        self.assertEqual(medido.reintentos_429, 1)
        self.assertEqual(esperas, [4.0])

    def test_otro_error_http_no_se_reintenta(self):
        import io
        import urllib.error
        from unittest import mock
        mod = self._modulo()

        class _Interno:
            base_url, api_key, timeout = "https://nube.test/v1", "k", 5

            def _build_payload(self, s, u, m):
                return {"model": "m"}

        def _urlopen(req, timeout=None):
            raise urllib.error.HTTPError("u", 403, "no", {}, io.BytesIO(b""))

        medido = mod.BackendMedido(_Interno(), dormir=lambda s: self.fail("no debía esperar"))
        with mock.patch("urllib.request.urlopen", _urlopen):
            with self.assertRaises(urllib.error.HTTPError):
                medido.complete("s", "u", "m")


    def test_retry_after_largo_corta_en_vez_de_esperar(self):
        import io
        import urllib.error
        from unittest import mock
        mod = self._modulo()

        class _Interno:
            base_url, api_key, timeout = "https://nube.test/v1", "k", 5

            def _build_payload(self, s, u, m):
                return {"model": "m"}

        def _urlopen(req, timeout=None):
            raise urllib.error.HTTPError("u", 429, "diario", {"retry-after": "3600"},
                                         io.BytesIO(b""))

        medido = mod.BackendMedido(_Interno(), dormir=lambda s: self.fail("no debía esperar"))
        with mock.patch("urllib.request.urlopen", _urlopen):
            with self.assertRaisesRegex(RuntimeError, "retry-after 3600"):
                medido.complete("s", "u", "m")

    def test_socket_acepta_ip_rotada_del_mismo_host(self):
        from unittest import mock
        mod = self._modulo()
        ips = [[(2, 1, 6, "", ("1.1.1.1", 443))], [(2, 1, 6, "", ("2.2.2.2", 443))]]
        with mock.patch("socket.getaddrinfo", side_effect=lambda *a, **k: ips.pop(0)):
            barrera = mod.SocketSoloMotor("https://api.groq.com/openai/v1")
            self.assertTrue(barrera.permite(("1.1.1.1", 443)))
            self.assertTrue(barrera.permite(("2.2.2.2", 443)))   # rotó: se vuelve a resolver
        with mock.patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("2.2.2.2", 443))]):
            self.assertFalse(barrera.permite(("9.9.9.9", 443)))  # otra IP: fuera
            self.assertFalse(barrera.permite(("2.2.2.2", 25)))   # otro puerto: fuera

class UserAgentTest(unittest.TestCase):
    """Groq responde 403 al user-agent por defecto de urllib: el backend manda el suyo."""

    def test_local_backend_envia_user_agent_propio(self):
        import json
        from unittest import mock
        from zero.backends import LocalBackend, USER_AGENT
        vistos = []

        class _Resp:
            def read(self):
                return json.dumps({"choices": [{"message": {"content": "{}"}}]}).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def _urlopen(req, timeout=None):
            vistos.append(req.get_header("User-agent"))
            return _Resp()

        with mock.patch("urllib.request.urlopen", _urlopen):
            LocalBackend(model="m", base_url="https://nube.test/v1", api_key="k").complete("s", "u", "m")
        self.assertEqual(vistos, [USER_AGENT])
        self.assertNotIn("Python-urllib", USER_AGENT)


if __name__ == "__main__":
    unittest.main()
