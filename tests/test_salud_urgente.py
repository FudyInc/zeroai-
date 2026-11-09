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
    # load_env() trae la URL real de .env: ningún test debe hacer un ping de verdad.
    os.environ.pop("HEALTHCHECK_PING_URL", None)
    return modulo


class AvisosSoloUrgentes(unittest.TestCase):
    def setUp(self):
        self.salud = _cargar()

    def _correr(self, fallas):
        with mock.patch.object(self.salud, "revisar", return_value=fallas), \
                mock.patch.object(self.salud, "notify_owner",
                                  return_value={"status": "sent"}) as aviso, \
                mock.patch.object(self.salud, "_latido"), \
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



class PruebaDiariaDelAgente(unittest.TestCase):
    """La última prueba COMPLETA de zero-golden se lee del journal; si es vieja, se relanza.

    Mira el resultado, no la intención: el timer puede haber "disparado" en un arranque
    efímero de WSL que la mató con 'signal'. Eso no cuenta como corrida."""

    AHORA = 1_800_000_000.0

    def setUp(self):
        self.salud = _cargar()

    def _correr(self, ultima, estado="inactive", arranque=None, start_rc=0, journal_rc=0,
                salida="6/6 casos dentro de las reglas"):
        llamadas = []

        def run(cmd, **kw):
            llamadas.append(cmd)
            if cmd[0] == "journalctl":
                if any(a.startswith("_SYSTEMD_INVOCATION_ID=inv1") for a in cmd):
                    return mock.Mock(returncode=0, stdout=f"motor:   qwen\n{salida}\n", stderr="")
                out = "" if ultima is None else (
                    '{"__REALTIME_TIMESTAMP": "%d", "USER_INVOCATION_ID": "inv1"}\n' % int(ultima * 1e6))
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

    def test_corrida_con_el_motor_caido_no_cuenta_como_prueba(self):
        # exit 2: systemd la registra "Finished", pero no corrió ningún caso
        fallas = self._correr(self.AHORA - 3 * 3600, salida="⚠ saludo: el motor no respondió (timeout)")
        self.assertIn("nunca completó", self._urgentes(fallas)[0])
        self.assertEqual(len(self.starts), 1)

    def test_una_regla_rota_si_cuenta_como_prueba_completa(self):
        self.assertEqual(self._correr(self.AHORA - 3600, salida="1 regla(s) rota(s) en 6 casos"), [])

    def test_las_marcas_que_busca_son_las_que_imprime_probar_agente(self):
        # Si alguien cambia el texto de probar-agente.py, este test lo ata: sin él, la
        # salud dejaría de reconocer toda corrida y relanzaría la prueba cada 2 h.
        fuente = (_RUTA.parent / "probar-agente.py").read_text()
        for marca in self.salud._GOLDEN_PROBO:
            self.assertIn(marca, fuente)

    def test_revisar_incluye_la_prueba_diaria(self):
        s = self.salud
        with mock.patch.object(s, "_servicio", return_value=True), \
             mock.patch.object(s, "_http", return_value=True), \
             mock.patch.object(s, "_ollama_responde", return_value=True), \
             mock.patch.object(s, "_nube_responde", return_value=True), \
             mock.patch.object(s, "_corrio_en_mock", return_value=[]), \
             mock.patch.object(s, "_prueba_diaria", return_value=["CENTINELA"]):
            self.assertIn("CENTINELA", s.revisar())


class SaludConNubePrincipal(unittest.TestCase):
    """Con WhatsApp en la nube, la salud no puede cargar el modelo local: eso
    tumbaba el PC (2026-11-08). Tampoco exige que el servicio ollama esté arriba."""

    def setUp(self):
        self.salud = _cargar()

    def _revisar(self, nube: bool, nube_ok: bool = True):
        s = self.salud
        servicios = []
        with mock.patch.object(s, "_nube_principal", return_value=nube), \
             mock.patch.object(s, "_servicio",
                               side_effect=lambda n, **kw: servicios.append(n) or True), \
             mock.patch.object(s, "_http", return_value=True), \
             mock.patch.object(s, "_ollama_responde", return_value=True) as ollama, \
             mock.patch.object(s, "_nube_responde", return_value=nube_ok), \
             mock.patch.object(s, "_corrio_en_mock", return_value=[]), \
             mock.patch.object(s, "_prueba_diaria", return_value=[]), \
             mock.patch.dict(os.environ, {"WHATSAPP_PROVIDER": "meta"}, clear=False):
            fallas = s.revisar()
        return fallas, servicios, ollama

    def test_en_nube_no_toca_ollama(self):
        fallas, servicios, ollama = self._revisar(nube=True)
        ollama.assert_not_called()
        self.assertNotIn("ollama", servicios)
        self.assertFalse(any("motor local" in f for f in fallas))

    def test_en_nube_avisa_si_la_nube_no_responde(self):
        fallas, _, _ = self._revisar(nube=True, nube_ok=False)
        self.assertTrue(any("Groq" in f for f in fallas))

    def test_en_local_sigue_probando_ollama(self):
        _, servicios, ollama = self._revisar(nube=False)
        ollama.assert_called_once()
        self.assertIn("ollama", servicios)



class SaludPruebaElModeloDeWhatsapp(unittest.TestCase):
    """El chequeo no debe cargar en la GPU un modelo que WhatsApp no usa."""

    def setUp(self):
        self.salud = _cargar()

    def _modelo(self, entorno):
        with mock.patch.dict(os.environ, entorno, clear=False):
            for clave in ("WHATSAPP_MODEL", "LOCAL_MODEL"):
                if clave not in entorno:
                    os.environ.pop(clave, None)
            return self.salud._modelo_a_probar()

    def test_usa_el_modelo_de_whatsapp_antes_que_el_local(self):
        self.assertEqual(self._modelo({"WHATSAPP_MODEL": "qwen3:14b",
                                       "LOCAL_MODEL": "qwen2.5:14b-instruct-q4_K_M"}),
                         "qwen3:14b")

    def test_sin_modelo_de_whatsapp_usa_el_local_y_luego_config(self):
        from zero.config import WHATSAPP_ENGINE
        self.assertEqual(self._modelo({"LOCAL_MODEL": "otro:7b"}), "otro:7b")
        self.assertEqual(self._modelo({}), WHATSAPP_ENGINE["model"])

    def test_el_ping_lleva_ese_modelo(self):
        enviado = {}

        def falso_urlopen(req, timeout=None):
            import json as _json
            enviado.update(_json.loads(req.data))
            raise OSError("sin red en la suite")

        with mock.patch.dict(os.environ, {"WHATSAPP_MODEL": "qwen3:14b"}), \
                mock.patch.object(self.salud.urllib.request, "urlopen", falso_urlopen):
            self.assertFalse(self.salud._ollama_responde())
        self.assertEqual(enviado.get("model"), "qwen3:14b")

    def _respuesta(self, mensaje):
        import io
        import json as _json
        cuerpo = _json.dumps({"choices": [{"message": mensaje}]}).encode()
        return mock.patch.object(self.salud.urllib.request, "urlopen",
                                 lambda req, timeout=None: io.BytesIO(cuerpo))

    def test_un_modelo_que_piensa_cuenta_como_vivo(self):
        # qwen3 con max_tokens=5: todo se va a reasoning y content llega vacío (2026-11-04).
        with self._respuesta({"content": "", "reasoning": "Okay, the"}):
            self.assertTrue(self.salud._ollama_responde())

    def test_sin_nada_generado_no_esta_vivo(self):
        with self._respuesta({"content": ""}):
            self.assertFalse(self.salud._ollama_responde())


class LatidoAHealthchecks(unittest.TestCase):
    """Cada revisión avisa «sigo vivo» afuera; si el PC muere, el silencio es el aviso."""

    URL = "https://hc-ping.com/prueba-uuid"

    def setUp(self):
        self.salud = _cargar()
        self.pedidos = []

    def _urlopen(self, req, timeout=None):
        self.pedidos.append((req.full_url, req.data))
        return mock.MagicMock()

    def _correr(self, fallas, url=URL):
        entorno = {"HEALTHCHECK_PING_URL": url} if url else {}
        with mock.patch.dict(os.environ, entorno), \
                mock.patch.object(self.salud, "revisar", return_value=fallas), \
                mock.patch.object(self.salud, "notify_owner", return_value={"status": "sent"}), \
                mock.patch.object(self.salud.urllib.request, "urlopen", self._urlopen), \
                mock.patch("sys.argv", ["revisar-salud.py"]):
            if not url:
                os.environ.pop("HEALTHCHECK_PING_URL", None)
            return self.salud.main()

    def test_todo_en_orden_manda_el_latido(self):
        self.assertEqual(self._correr([]), 0)
        self.assertEqual([u for u, _ in self.pedidos], [self.URL])

    def test_lo_no_urgente_tambien_es_latido_normal(self):
        self._correr([self.salud.NO_URGENTE + "WhatsApp: 3 mensajes requieren revisión"])
        self.assertEqual([u for u, _ in self.pedidos], [self.URL])

    def test_una_caida_va_a_fail_con_el_motivo(self):
        self.assertEqual(self._correr(["el servicio ollama está caído"]), 1)
        url, cuerpo = self.pedidos[0]
        self.assertEqual(url, self.URL + "/fail")
        self.assertIn(b"ollama", cuerpo)

    def test_sin_url_no_hay_ping(self):
        self._correr([], url="")
        self.assertEqual(self.pedidos, [])

    def test_si_la_revision_se_cae_avisa_fail(self):
        with mock.patch.dict(os.environ, {"HEALTHCHECK_PING_URL": self.URL}), \
                mock.patch.object(self.salud, "revisar", side_effect=RuntimeError("x")), \
                mock.patch.object(self.salud.urllib.request, "urlopen", self._urlopen), \
                mock.patch("sys.argv", ["revisar-salud.py"]):
            with self.assertRaises(RuntimeError):
                self.salud.main()
        self.assertEqual(self.pedidos[0][0], self.URL + "/fail")

    def test_el_cuerpo_es_un_resumen_corto(self):
        self._correr(["x" * 500] + [f"falla {i}" for i in range(20)])
        cuerpo = self.pedidos[0][1].decode()
        self.assertLessEqual(len(cuerpo.splitlines()), 8)
        self.assertTrue(all(len(l) <= 160 for l in cuerpo.splitlines()))

    def test_sin_red_la_revision_no_se_rompe(self):
        def sin_red(req, timeout=None):
            raise OSError("sin red")
        with mock.patch.dict(os.environ, {"HEALTHCHECK_PING_URL": self.URL}), \
                mock.patch.object(self.salud.urllib.request, "urlopen", sin_red):
            self.salud._latido(False)          # no lanza


if __name__ == "__main__":
    unittest.main()
