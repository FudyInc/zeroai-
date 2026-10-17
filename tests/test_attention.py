"""Módulo de atención: lo que el agente no pudo resolver y lo que el equipo le enseña.

Reglas que protegen estas pruebas:
- todo lo que el agente no pudo resolver llega a la lista, con el chat para
  responder (pregunta que no entendió, o pedido que tiene que cotizar una persona);
- el agente solo aprende lo que aprueba una persona: respuestas y sinónimos;
- una respuesta aprendida se usa solo para la misma pregunta o una casi igual.
"""
import json
import os
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from zero.agents import build_agents
from zero.attention import (learned_alias, learned_answer, teach_alias, teach_answer)
from zero.crm import CRM
from zero.memory import SessionMemory, _gap_key
from zero.orchestrator import Zero
from zero.pool_border import _MEASUREMENT_QUESTION


def _memory_with_gap(question="¿Hacen boleta o factura?"):
    memory = SessionMemory(None)
    memory.register_client("losetaschile", "STARTER")
    memory.add_knowledge_gap("losetaschile", question, "El agente no entendió la consulta",
                             chat_id="56933333333@c.us", contacto="Diego", lead_key="k1")
    return memory, _gap_key(question)


class EnseñarRespuestas(unittest.TestCase):
    def test_la_respuesta_aprobada_se_usa_para_la_misma_pregunta(self):
        memory, clave = _memory_with_gap()
        self.assertIsNone(teach_answer(memory, "losetaschile", clave, "Sí, emitimos ambas."))
        self.assertEqual(learned_answer(memory, "losetaschile", "hacen boleta o factura"),
                         "Sí, emitimos ambas.")
        self.assertIn("Sí, emitimos ambas.", memory.get_client_knowledge("losetaschile"))

    def test_no_se_usa_para_una_pregunta_distinta(self):
        memory, clave = _memory_with_gap()
        teach_answer(memory, "losetaschile", clave, "Sí, emitimos ambas.")
        self.assertIsNone(learned_answer(memory, "losetaschile", "¿Hacen despacho a Rancagua?"))

    def test_sin_aprobar_no_hay_aprendizaje(self):
        memory, _ = _memory_with_gap()
        self.assertIsNone(learned_answer(memory, "losetaschile", "¿Hacen boleta o factura?"))

    def test_el_agente_responde_lo_aprendido_sin_modelo(self):
        memory, clave = _memory_with_gap()
        teach_answer(memory, "losetaschile", clave, "Sí, emitimos ambas.")
        zero = Zero(build_agents(mock=True), memory=memory)
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result("losetaschile", "¿hacen boleta o factura?",
                                          lead={"key": "k2"}, channel="whatsapp", history=[])
        dispatch.assert_not_called()
        self.assertEqual(result["reply"], "Sí, emitimos ambas.")


    def test_cifras_distintas_no_reciben_la_respuesta(self):
        memory, clave = _memory_with_gap("¿Cuánto cuesta el pastelón de 40x40 gris?")
        teach_answer(memory, "losetaschile", clave, "Cuesta $1.600 la unidad.")
        for otra in ("¿Cuánto cuesta el pastelón de 40x50 gris?",
                     "¿Cuánto cuesta el pastelón de 30x30 gris?"):
            with self.subTest(otra=otra):
                self.assertIsNone(learned_answer(memory, "losetaschile", otra))
        self.assertEqual(learned_answer(memory, "losetaschile",
                                        "cuanto cuesta el pastelon de 40x40 gris"),
                         "Cuesta $1.600 la unidad.")

    def test_un_numero_suelto_nunca_activa_lo_aprendido(self):
        memory, clave = _memory_with_gap("2")
        memory.add_knowledge_gap("losetaschile", "2")
        teach_answer(memory, "losetaschile", _gap_key("2"), "Respuesta para el 2")
        self.assertIsNone(learned_answer(memory, "losetaschile", "2"))

    def test_un_pedido_se_atiende_pero_no_se_aprende(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        memory.add_knowledge_gap("losetaschile", "Borde ballena 50×40", "Borde ballena: cotizar",
                                 chat_id="56933333333@c.us", tipo="pedido")
        clave = _gap_key("Borde ballena 50×40")
        ficha = memory.get_client_knowledge("losetaschile")
        self.assertIsNone(teach_answer(memory, "losetaschile", clave, "Son $250.000 en total."))
        self.assertEqual(memory.get_client_knowledge("losetaschile"), ficha)
        self.assertIsNone(learned_answer(memory, "losetaschile", "Borde ballena 50×40"))
        self.assertEqual(memory.list_knowledge_gaps("losetaschile"), [])


class EnseñarSinonimos(unittest.TestCase):
    def test_la_frase_ensenada_cuenta_como_la_opcion(self):
        memory, clave = _memory_with_gap("los de la orilla")
        self.assertIsNone(teach_alias(memory, "losetaschile", clave, "Bordes de piscina"))
        self.assertEqual(learned_alias(memory, "losetaschile", "Los de la orilla"),
                         "Bordes de piscina")
        zero = Zero(build_agents(mock=True), memory=memory)
        with mock.patch.object(zero, "dispatch") as dispatch:
            result = zero.converse_result("losetaschile", "los de la orilla",
                                          lead={"key": "k2"}, channel="whatsapp", history=[])
        dispatch.assert_not_called()
        self.assertEqual(result["reply"], _MEASUREMENT_QUESTION)

    def test_solo_opciones_del_flujo(self):
        memory, clave = _memory_with_gap("los de la orilla")
        self.assertIsNotNone(teach_alias(memory, "losetaschile", clave, "Cualquier cosa"))


class RegistroDesdeConversaciones(unittest.TestCase):
    def _zero(self):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56911111111", "response_mode": "automatic"})
        crm = CRM(None)
        crm.upsert("losetaschile", {"phone": "56933333333", "name": "Diego", "source": "t"})
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web", "id": "t"})
        return zero, memory

    def test_pregunta_sin_respuesta_queda_con_su_chat(self):
        zero, memory = self._zero()
        draft = SimpleNamespace(result={"reply": "", "intent": "handoff"}, status="ok")
        with mock.patch.object(zero, "dispatch", return_value=draft):
            zero.handle_inbound("56933333333", "¿Tienen garantía?", to_phone_id="56911111111",
                                whatsapp_chat_id="56933333333@c.us")
        [caso] = memory.list_knowledge_gaps("losetaschile")
        self.assertEqual(caso["tipo"], "pregunta")
        self.assertEqual(caso["chat_id"], "56933333333@c.us")
        self.assertEqual(caso["contacto"], "Diego")
        self.assertTrue(caso["lead_key"])

    def test_pedido_que_cotiza_una_persona_tambien_llega(self):
        zero, memory = self._zero()
        with mock.patch("zero.whatsapp_web.send_catalog_document",
                        return_value={"id": "d", "ack": 0}), \
                mock.patch("zero.whatsapp_web.send_catalog_image",
                           return_value={"id": "i", "ack": 0}), \
                mock.patch.object(zero, "dispatch"):
            for text in ("Hola", "2", "20", "1", "6", "3"):
                zero.handle_inbound("56933333333", text, to_phone_id="56911111111",
                                    whatsapp_chat_id="56933333333@c.us")
        casos = memory.list_knowledge_gaps("losetaschile")
        self.assertEqual([c["tipo"] for c in casos], ["pedido"])
        self.assertIn("Pastelones", casos[0]["reason"])

    def test_descartado_no_vuelve_aunque_se_repita(self):
        memory, clave = _memory_with_gap("ok")
        memory.dismiss_knowledge_gap("losetaschile", clave)
        memory.add_knowledge_gap("losetaschile", "ok")
        self.assertEqual(memory.list_knowledge_gaps("losetaschile"), [])

    def test_todos_los_que_esperan_quedan_anotados(self):
        memory, clave = _memory_with_gap()
        memory.add_knowledge_gap("losetaschile", "¿hacen boleta o factura?",
                                 chat_id="56944444444@c.us", lead_key="k2")
        caso = memory.list_knowledge_gaps("losetaschile")[0]
        self.assertEqual([e["chat_id"] for e in caso["esperando"]],
                         ["56933333333@c.us", "56944444444@c.us"])


class RutasDelDashboard(unittest.TestCase):
    """Las rutas reales, con uvicorn, sin auth y sin enviar nada (send=false)."""

    @classmethod
    def setUpClass(cls):
        from tests.test_api_http import _free_port, _start_and_wait
        cls.port = _free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        tmp = tempfile.mkdtemp()
        env = dict(os.environ, STATE_PATH=os.path.join(tmp, "state.json"),
                   CRM_PATH=os.path.join(tmp, "crm.json"), SUPABASE_URL="", SUPABASE_KEY="",
                   AUTH_PASSWORD="", SUPABASE_JWT_SECRET="", LOCAL_MODEL="",
                   ANTHROPIC_API_KEY="", OPENAI_API_KEY="", ZERO_PIPELINE_MOCK_OK="1",
                   AUTH_USERS_PATH=os.path.join(tempfile.mkdtemp(), "users.json"))
        memory = SessionMemory(env["STATE_PATH"])
        memory.register_client("losetaschile", "STARTER")
        for q in ("¿Hacen boleta o factura?", "los de la orilla", "ok"):
            memory.add_knowledge_gap("losetaschile", q, "El agente no entendió la consulta")
        memory.save()
        cls.state_path = env["STATE_PATH"]
        cls.proc = _start_and_wait(
            [sys.executable, "-m", "uvicorn", "api:app", "--port", str(cls.port),
             "--log-level", "warning"],
            str(Path(__file__).resolve().parent.parent), env, cls.base)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=5)

    def _call(self, path, body=None):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
            method="POST" if body is not None else "GET")
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.load(res)

    def test_listar_responder_sinonimo_y_descartar(self):
        lista = self._call("/api/whatsapp/attention?client=losetaschile")
        self.assertEqual(lista["open"], 3)
        self.assertTrue(any("Bordes de piscina" in g["opciones"] for g in lista["options"]))
        claves = {i["pregunta"]: i["clave"] for i in lista["items"]}
        out = self._call("/api/whatsapp/attention/answer?client=losetaschile",
                         {"clave": claves["¿Hacen boleta o factura?"],
                          "respuesta": "Sí, emitimos ambas.", "send": False})
        self.assertEqual((out["ok"], out["sent"], out["learned"]), (True, False, True))
        self._call("/api/whatsapp/attention/alias?client=losetaschile",
                   {"clave": claves["los de la orilla"], "opcion": "Bordes de piscina"})
        self._call("/api/whatsapp/attention/dismiss?client=losetaschile",
                   {"clave": claves["ok"]})
        self.assertEqual(self._call("/api/whatsapp/attention?client=losetaschile")["open"], 0)
        todas = self._call("/api/whatsapp/attention?client=losetaschile&include_resolved=true")
        estados = sorted(i["estado"] for i in todas["items"])
        self.assertEqual(estados, ["descartada", "resuelta", "resuelta"])
        guardado = SessionMemory(self.state_path)
        self.assertEqual(learned_answer(guardado, "losetaschile", "hacen boleta o factura"),
                         "Sí, emitimos ambas.")


if __name__ == "__main__":
    unittest.main()
