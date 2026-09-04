"""Tests de zero/calls.py — llamadas salientes vía Vapi (curl).

calls.py es una frontera con el mundo (subprocess curl). Aquí se mockea
subprocess.run y las env VAPI_*: se prueba la validación de credenciales,
el parsing de la respuesta (payload\\nstatus) y el manejo de errores HTTP,
sin tocar la red.
"""
import json
import os
import unittest
from unittest import mock

from zero import calls


def _proc(stdout="", stderr=""):
    return mock.Mock(stdout=stdout, stderr=stderr)


def _with_key(**extra):
    env = {"VAPI_API_KEY": "k", **extra}
    return mock.patch.dict(os.environ, env, clear=False)


def _capture_body(captured):
    """side_effect para subprocess.run: guarda el JSON que se HABRÍA enviado.

    Los tests nunca hacen una llamada real — Vapi cobra por minuto.
    """
    def fake_run(args, **kw):
        captured.update(json.loads(args[args.index("--data-binary") + 1]))
        return _proc(stdout='{"id":"c"}\n200')
    return fake_run


class TestCurl(unittest.TestCase):
    def test_sin_key_lanza(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as cm:
                calls._curl("GET", "assistant")
            self.assertIn("VAPI_API_KEY", str(cm.exception))

    def test_ok_parsea_json(self):
        with _with_key(), mock.patch("zero.calls.shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("zero.calls.subprocess.run",
                        return_value=_proc(stdout='{"id":"a1"}\n200')):
            self.assertEqual(calls._curl("GET", "assistant"), {"id": "a1"})

    def test_status_error_lanza_con_mensaje(self):
        with _with_key(), mock.patch("zero.calls.shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("zero.calls.subprocess.run",
                        return_value=_proc(stdout='{"message":"no autorizado"}\n403')):
            with self.assertRaises(RuntimeError) as cm:
                calls._curl("GET", "assistant")
            self.assertIn("403", str(cm.exception))
            self.assertIn("no autorizado", str(cm.exception))

    def test_payload_no_json_degrada_a_raw(self):
        with _with_key(), mock.patch("zero.calls.shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("zero.calls.subprocess.run",
                        return_value=_proc(stdout='texto plano\n200')):
            self.assertEqual(calls._curl("GET", "x"), {"raw": "texto plano"})

    def test_timeout_lanza(self):
        import subprocess as _sp
        with _with_key(), mock.patch("zero.calls.shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("zero.calls.subprocess.run",
                        side_effect=_sp.TimeoutExpired("curl", 40)):
            with self.assertRaises(RuntimeError) as cm:
                calls._curl("GET", "x")
            self.assertIn("tiempo", str(cm.exception))

    def test_sin_curl_lanza(self):
        with _with_key(), mock.patch("zero.calls.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as cm:
                calls._curl("GET", "assistant")
            self.assertIn("curl", str(cm.exception))


class TestListers(unittest.TestCase):
    def test_list_assistants_mapea(self):
        with mock.patch("zero.calls._curl",
                        return_value=[{"id": "1", "name": "Fernanda"}, {"id": "2"}]):
            out = calls.list_assistants()
            self.assertEqual(out[0], {"id": "1", "name": "Fernanda"})
            self.assertEqual(out[1]["name"], "(sin nombre)")

    def test_list_phone_numbers_mapea(self):
        with mock.patch("zero.calls._curl",
                        return_value=[{"id": "p1", "number": "+56 9"}, {"id": "p2"}]):
            out = calls.list_phone_numbers()
            self.assertEqual(out[0]["number"], "+56 9")
            self.assertEqual(out[1]["number"], "p2")  # cae al id

    def test_list_assistants_respuesta_envuelta_no_revienta(self):
        # Si Vapi alguna vez devuelve un dict (envoltorio, error 200 con otra
        # forma) en vez de una lista bare, no debe lanzar AttributeError.
        with mock.patch("zero.calls._curl", return_value={"data": []}):
            self.assertEqual(calls.list_assistants(), [])

    def test_list_phone_numbers_respuesta_envuelta_no_revienta(self):
        with mock.patch("zero.calls._curl", return_value={"data": []}):
            self.assertEqual(calls.list_phone_numbers(), [])

    def test_list_assistants_ignora_items_no_dict(self):
        with mock.patch("zero.calls._curl", return_value=["oops", {"id": "1"}]):
            out = calls.list_assistants()
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["id"], "1")


class TestPlaceCall(unittest.TestCase):
    def test_faltan_campos_lanza(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as cm:
                calls.place_call("+56911111111")
            self.assertIn("Falta", str(cm.exception))

    def test_numero_vacio_lanza(self):
        with _with_key(VAPI_ASSISTANT_ID="asst", VAPI_PHONE_NUMBER_ID="ph"):
            with self.assertRaises(RuntimeError) as cm:
                calls.place_call("   ")
            self.assertIn("número a llamar", str(cm.exception))

    def test_sin_curl_lanza(self):
        with _with_key(VAPI_ASSISTANT_ID="asst", VAPI_PHONE_NUMBER_ID="ph"), \
             mock.patch("zero.calls.shutil.which", return_value=None):
            with self.assertRaises(RuntimeError) as cm:
                calls.place_call("+56911111111")
            self.assertIn("curl", str(cm.exception))

    def test_ok_devuelve_dict(self):
        with _with_key(VAPI_ASSISTANT_ID="asst", VAPI_PHONE_NUMBER_ID="ph"), \
             mock.patch("zero.calls.shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("zero.calls.subprocess.run",
                        return_value=_proc(stdout='{"id":"call1"}\n201')):
            out = calls.place_call("+56911111111", name="Ana")
            self.assertEqual(out["id"], "call1")

    def test_incluye_name_en_customer(self):
        captured = {}
        with _with_key(VAPI_ASSISTANT_ID="asst", VAPI_PHONE_NUMBER_ID="ph"), \
             mock.patch("zero.calls.shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("zero.calls.subprocess.run", side_effect=_capture_body(captured)):
            calls.place_call("+56911111111", name="Ana")
            self.assertEqual(captured["customer"]["name"], "Ana")
            self.assertEqual(captured["assistantId"], "asst")

    def test_error_status_lanza(self):
        with _with_key(VAPI_ASSISTANT_ID="asst", VAPI_PHONE_NUMBER_ID="ph"), \
             mock.patch("zero.calls.shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("zero.calls.subprocess.run",
                        return_value=_proc(stdout='{"message":"saldo"}\n402')):
            with self.assertRaises(RuntimeError) as cm:
                calls.place_call("+56911111111")
            self.assertIn("402", str(cm.exception))


class TestLeadVariables(unittest.TestCase):
    """El contexto del lead que viaja al prompt del asistente (variableValues)."""

    LEAD = {"company": "Acme SpA", "activity": "fintech", "stage": "qualified",
            "source": "web"}

    def _body(self, **kwargs):
        captured = {}
        with _with_key(VAPI_ASSISTANT_ID="asst", VAPI_PHONE_NUMBER_ID="ph"), \
             mock.patch("zero.calls.shutil.which", return_value="/usr/bin/curl"), \
             mock.patch("zero.calls.subprocess.run", side_effect=_capture_body(captured)):
            calls.place_call("+56911111111", **kwargs)
        return captured

    def test_lead_completo_manda_las_cuatro_variables(self):
        body = self._body(lead=self.LEAD)
        variables = body["assistantOverrides"]["variableValues"]
        self.assertEqual(variables, {"empresa": "Acme SpA", "rubro": "fintech",
                                     "etapa": "qualified", "origen": "web"})
        self.assertTrue(all(v for v in variables.values()))

    def test_sin_lead_el_body_es_el_de_siempre(self):
        # Las llamadas manuales del dashboard no traen lead: el cuerpo no debe
        # cambiar en nada respecto de antes de esta feature.
        body = self._body(name="Ana")
        self.assertNotIn("assistantOverrides", body)
        self.assertEqual(set(body), {"assistantId", "phoneNumberId", "customer"})

    def test_campo_none_no_viaja_ni_como_texto_None(self):
        # Una variable con "None" adentro se la lee el asistente en voz alta.
        body = self._body(lead={**self.LEAD, "activity": None})
        variables = body["assistantOverrides"]["variableValues"]
        self.assertNotIn("rubro", variables)
        self.assertNotIn("None", json.dumps(body))

    def test_campo_vacio_o_en_blanco_no_viaja(self):
        body = self._body(lead={**self.LEAD, "source": "", "stage": "   "})
        variables = body["assistantOverrides"]["variableValues"]
        self.assertEqual(set(variables), {"empresa", "rubro"})

    def test_lead_sin_ningun_campo_util_no_agrega_la_clave(self):
        body = self._body(lead={"email": "a@b.cl", "phone": "+569"})
        self.assertNotIn("assistantOverrides", body)

    def test_no_filtra_datos_internos_del_lead(self):
        # Lo que entra a variableValues termina en el prompt de un tercero.
        body = self._body(lead={**self.LEAD, "email": "ana@acme.cl",
                                "phone": "+56922222222", "notes": "regatea mucho"})
        enviado = json.dumps(body)
        for privado in ("ana@acme.cl", "+56922222222", "regatea mucho"):
            self.assertNotIn(privado, enviado)


if __name__ == "__main__":
    unittest.main()
