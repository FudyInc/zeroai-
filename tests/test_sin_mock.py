"""Las puertas por donde el dashboard podía inventar datos, cerradas.

Cada test de acá corresponde a un camino que ANTES devolvía o guardaba datos
falsos indistinguibles de los reales. No son tests de una función: son el
contrato de "el dashboard no miente".

Al escribirse, la regla era "el mock es legítimo, lo que se prohíbe es que se haga
pasar por real". El 2026-09-08 Diego cambió esa regla: ZERO dejó de ser mock-first
y opera con motor real. El mock ya no corre en producción — sin motor, 503.

Lo de abajo sigue valiendo entero: son las puertas por las que un dato falso podía
llegar al CRM o a la pantalla. Lo nuevo está en `SinMotorNoHayRespuestaTest`.
"""
import os
import re
import unittest
from unittest import mock

from fastapi import HTTPException

import api
from zero.finance import summary


class ExigirMotorRealTest(unittest.TestCase):
    """PROSPECTOR en mock devuelve la fixture `_COMPANIES` y el pipeline la
    escribe al CRM. `function_actions.run_job` ya se negaba a correr así; los
    botones del dashboard no, y esa era la puerta abierta."""

    def _limpio(self):
        return mock.patch.dict(os.environ, {"ZERO_PIPELINE_MOCK_OK": ""}, clear=False)

    def test_mock_no_corre(self):
        with self._limpio():
            with self.assertRaises(HTTPException) as ctx:
                api._exigir_motor_real("mock")
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("inventadas", ctx.exception.detail)

    def test_motor_real_corre(self):
        with self._limpio():
            self.assertIsNone(api._exigir_motor_real("live"))

    def test_la_escotilla_es_solo_para_pruebas(self):
        """Existe para que la suite ejercite el pipeline sin red, y solo con el
        valor exacto "1" — un env declarado vacío NO abre la puerta."""
        with mock.patch.dict(os.environ, {"ZERO_PIPELINE_MOCK_OK": "1"}, clear=False):
            self.assertIsNone(api._exigir_motor_real("mock"))
        with mock.patch.dict(os.environ, {"ZERO_PIPELINE_MOCK_OK": " "}, clear=False):
            with self.assertRaises(HTTPException):
                api._exigir_motor_real("mock")


class CampanasSinMetaTest(unittest.TestCase):
    """Sin cuenta de Meta la pestaña mostraba gasto, leads y CPL inventados con
    un badge chico que decía "datos mock". Ahora muestra vacío y el porqué."""

    def test_sin_credenciales_devuelve_vacio(self):
        with mock.patch.dict(os.environ, {"META_ADS_TOKEN": "", "META_AD_ACCOUNT_ID": ""},
                             clear=False):
            items, source, error = api._safe_campaigns("Petlabs", {})
        self.assertEqual(items, [])
        self.assertEqual(source, "sin_datos")
        self.assertIsNone(error)

    def test_nunca_devuelve_source_mock(self):
        """El frontend decide qué badge pintar con este valor: si vuelve a decir
        "mock", vuelve a haber cifras falsas en pantalla."""
        with mock.patch.dict(os.environ, {"META_ADS_TOKEN": "", "META_AD_ACCOUNT_ID": ""},
                             clear=False):
            _, source, _ = api._safe_campaigns("Petlabs", {"regions": ["RM"]})
        self.assertNotEqual(source, "mock")


class SyncLeadsSinMetaTest(unittest.TestCase):
    """El peor de todos: el mock de Meta inventa 3–6 personas con nombre, empresa,
    correo y teléfono, etiquetadas `source: "meta_ads"`. Una vez en el CRM son
    indistinguibles de gente real. El botón "Importar leads de ads" las guardaba."""

    def test_se_niega_y_no_toca_el_crm(self):
        with mock.patch.dict(os.environ, {"META_ADS_TOKEN": "", "META_AD_ACCOUNT_ID": ""},
                             clear=False):
            with mock.patch.object(api, "make_crm") as crm_falso:
                with self.assertRaises(HTTPException) as ctx:
                    api.sync_ad_leads("Petlabs")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Meta Ads no está conectado", ctx.exception.detail)
        crm_falso.assert_not_called()   # ni siquiera se abrió el CRM


class FinanzasSinArchivoTest(unittest.TestCase):
    """Sin finance.json el resumen traía vapi 40k / elevenlabs 10k / dominio 2k."""

    def test_no_inventa_costos(self):
        s = summary(None, mrr_clp=500_000)
        self.assertEqual(s["costs"], [])
        self.assertEqual(s["costs_clp"], 0)
        self.assertEqual(s["source"], "sin_datos")
        self.assertNotEqual(s["source"], "mock")


class SinMotorNoHayRespuestaTest(unittest.TestCase):
    """Sin motor real no hay respuesta de plantilla: hay 503.

    Antes, `_agents_best` y `_agents_autonomous` terminaban cayendo al mock, y
    `_agent_op` reintentaba en mock cuando el modelo real fallaba o devolvía vacío —
    "para que el agente SIEMPRE responda". Eso convertía una falla del motor en una
    respuesta que se veía igual que una buena, y ese disimulo es exactamente lo que
    hizo que ocho días de ciclo muerto pasaran inadvertidos.
    """

    # Cada motor que `_agents_best` sepa construir tiene que estar acá, o el test deja
    # de probar lo que dice. Pasó de verdad el 2026-09-08: al guardar una OPENAI_API_KEY
    # en el .env, estos tests se pusieron rojos —no porque el código fallara, sino
    # porque la lista se había quedado corta y la máquina ya no estaba "rota".
    _MOTORES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LOCAL_MODEL")

    def _apagado(self, escotilla=""):
        """Apaga TODOS los motores; `escotilla` es el valor de ZERO_PIPELINE_MOCK_OK."""
        apagado = {v: "" for v in self._MOTORES}
        apagado["ZERO_PIPELINE_MOCK_OK"] = escotilla
        return mock.patch.dict(os.environ, apagado, clear=False)

    def _sin_motor(self):
        """Ni Anthropic, ni OpenAI, ni Ollama, ni escotilla. Una máquina rota."""
        return self._apagado()

    def test_la_lista_de_motores_cubre_todo_lo_que_lee_el_codigo(self):
        """Candado contra el mismo olvido: si mañana se agrega un motor nuevo a
        `_agents_best` y nadie lo agrega acá, esto avisa en vez de volverse verde
        por la razón equivocada."""
        import inspect
        fuente = inspect.getsource(api._agents_best) + inspect.getsource(api._agents_autonomous)
        leidas = {v for v in re.findall(r'os\.environ\.get\("([A-Z_]+)"', fuente)
                  if v.endswith("_API_KEY") or v == "LOCAL_MODEL"}
        self.assertTrue(leidas <= set(self._MOTORES),
                        f"motores que el código lee pero el test no apaga: {leidas - set(self._MOTORES)}")

    def test_agents_best_levanta_503_en_vez_de_devolver_mock(self):
        with self._sin_motor():
            with self.assertRaises(HTTPException) as ctx:
                api._agents_best()
        self.assertEqual(ctx.exception.status_code, 503)

    def test_agents_autonomous_tambien(self):
        """El camino autónomo es el que corre de noche sin nadie mirando: es donde
        más caro sale que una falla se disfrace de respuesta."""
        with self._sin_motor():
            with self.assertRaises(HTTPException):
                api._agents_autonomous()

    def test_agent_op_no_reintenta_en_mock(self):
        """Si el motor real falla en runtime, el error sale. No se tapa."""
        with self._sin_motor(), \
             mock.patch.object(api, "_agents_best", return_value=(object(), "live")):
            with self.assertRaises(RuntimeError):
                api._agent_op(lambda z: (_ for _ in ()).throw(RuntimeError("Ollama caído")))

    def test_la_escotilla_es_solo_de_la_suite(self):
        """Existe para probar plomería HTTP sin motor. Solo el valor exacto "1" abre —
        un env declarado pero vacío NO, que es el modo de fallo que ya mordió antes."""
        with self._apagado(escotilla="1"):
            _, modo = api._agents_best()
            self.assertEqual(modo, "mock")
        for valor in ("", " ", "true", "0"):
            with self.subTest(valor=valor):
                with self._apagado(escotilla=valor):
                    with self.assertRaises(HTTPException):
                        api._agents_best()

    def test_el_error_dice_como_arreglarlo(self):
        """Un 503 que no dice qué configurar deja al operador adivinando."""
        with self._sin_motor():
            with self.assertRaises(HTTPException) as ctx:
                api._agents_best()
        detalle = ctx.exception.detail
        self.assertIn("LOCAL_MODEL", detalle)
        self.assertIn("ANTHROPIC_API_KEY", detalle)


class UnAgenteRealNoSeVuelveMockSolo(unittest.TestCase):
    """La puerta más profunda, y la que era el comportamiento POR DEFECTO.

    `BaseAgent.__init__` hacía `self.mock = mock or backend is None`, así que pedir
    explícitamente un agente real sin backend devolvía un mock igual, sin decir nada:

        build_agents(mock=False)["PROSPECTOR"].mock  → True

    Nadie la alcanzaba en producción —todas las llamadas pasan backend o piden mock a
    propósito—, pero es la que se cuela sola el día que alguien agregue un sitio y
    olvide el backend. Se cerró el 2026-09-08 junto con las de api.py.
    """

    def test_pedir_real_sin_backend_es_un_error(self):
        from zero.agents import build_agents
        with self.assertRaises(ValueError) as ctx:
            build_agents(mock=False)
        self.assertIn("backend", str(ctx.exception))

    def test_el_error_dice_las_dos_salidas(self):
        """Un error que no dice qué hacer manda a la gente a poner mock=True a ciegas."""
        from zero.agents import build_agents
        with self.assertRaises(ValueError) as ctx:
            build_agents()
        msg = str(ctx.exception)
        self.assertIn("Pasa un backend", msg)
        self.assertIn("mock=True", msg)

    def test_pedir_mock_a_proposito_sigue_funcionando(self):
        """El mock explícito es legítimo: lo usa la suite entera."""
        from zero.agents import build_agents
        self.assertTrue(build_agents(mock=True)["PROSPECTOR"].mock)

    def test_con_backend_no_es_mock(self):
        from zero.agents import build_agents
        agentes = build_agents(backend=object(), mock=False)
        self.assertFalse(agentes["PROSPECTOR"].mock)


if __name__ == "__main__":
    unittest.main()
