"""El motor de WhatsApp: modelo local, enjaulado, con respaldo que avisa.

Decisión de Diego (2026-08-21): el modelo local corre SOLO en el agente de
WhatsApp. Estos tests existen para que esa jaula no dependa de que alguien la
recuerde — si un cambio futuro manda WhatsApp a la API paga, o extiende el local
al resto del sistema, acá se cae.

Stdlib unittest, sin deps, sin red. Desde la raíz del proyecto:

    python3 -m unittest discover -s tests -t .
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from zero import alerts
from zero.backends import FallbackBackend, LocalBackend
from zero.config import ALERT_THROTTLE_MINUTES, WHATSAPP_ENGINE


class _Boom:
    """Un backend que siempre falla — el Ollama caído."""

    def __init__(self, msg: str = "local backend unreachable"):
        self.msg = msg
        self.calls = 0

    def complete(self, system, user, model, max_tokens=4096):
        self.calls += 1
        raise RuntimeError(self.msg)


class _Echo:
    """Un backend que siempre contesta — el suplente."""

    def __init__(self, reply: str = "respuesta del suplente"):
        self.reply = reply
        self.calls = 0

    def complete(self, system, user, model, max_tokens=4096):
        self.calls += 1
        return self.reply


class _RecordingOutbox:
    def __init__(self, status: str = "sent"):
        self.status = status
        self.sent = []

    def send(self, msg, wa_creds=None):
        self.sent.append(msg)
        return {"channel": "whatsapp", "to": msg.get("to"), "status": self.status}


class WhatsAppEnginePolicyTest(unittest.TestCase):
    """La política dice lo que tiene que decir."""

    def test_engine_points_at_a_local_endpoint(self):
        # localhost: si esto apunta a un host remoto, dejó de ser "modelo local".
        self.assertIn("localhost", WHATSAPP_ENGINE["base_url"])
        self.assertTrue(WHATSAPP_ENGINE["model"])

    def test_paid_fallback_is_disabled(self):
        # La política actual es cero gasto también si falla Ollama.
        self.assertFalse(WHATSAPP_ENGINE["fallback_to_paid"])

    def test_local_whatsapp_prompt_and_context_fit_model_input(self):
        import api
        from zero.contracts import AgentResponse
        from zero.memory import SessionMemory
        from zero.orchestrator import Zero

        agents, mode = api._agents_whatsapp()
        self.assertEqual(mode, "local")
        memory = SessionMemory(None)
        memory.clients["zeroai"] = {"knowledge": "servicio " * 500}
        zero = Zero(agents, memory=memory)
        previous = [{"role": "lead", "text": "pregunta " * 200} for _ in range(12)]
        answer = AgentResponse("test", "CONCIERGE", "done", {"reply": "Hola"})
        with mock.patch.object(zero, "dispatch", return_value=answer) as dispatch:
            zero.converse_result("zeroai", "hola", lead={"key": "x", "name": "Ana",
                            "history": "no mandar al modelo" * 300}, history=previous)
        task = dispatch.call_args.args[1]
        self.assertEqual(task.data["lead"], {"name": "Ana"})
        self.assertEqual(len(task.data["history"]), 4)
        self.assertLessEqual(len(task.data["knowledge"]), 1600)
        self.assertLess(len(agents["CONCIERGE"].system_prompt()) + len(task.to_json()), 6500)

    def test_each_business_uses_its_own_reply_policy(self):
        from zero.contracts import AgentResponse
        from zero.memory import SessionMemory
        from zero.orchestrator import Zero

        memory = SessionMemory(None)
        memory.set_client_agent_profile("empresa_a", {
            "tone": "formal", "instructions": "Pide la comuna antes de ofrecer despacho."})
        memory.set_client_agent_profile("empresa_b", {
            "tone": "cercano", "instructions": "Ofrece retiro en tienda."})
        zero = Zero({}, memory=memory)
        answer = AgentResponse("test", "CONCIERGE", "done", {"reply": "Hola"})
        with mock.patch.object(zero, "dispatch", return_value=answer) as dispatch:
            zero.converse_result("empresa_a", "hola", history=[], vendor={"name": "Ana", "tone": "global"})
            task_a = dispatch.call_args.args[1]
            zero.converse_result("empresa_b", "hola", history=[], vendor={"name": "Ana", "tone": "global"})
            task_b = dispatch.call_args.args[1]
        self.assertEqual(task_a.data["vendor"]["tone"], "formal")
        self.assertEqual(task_b.data["vendor"]["tone"], "cercano")
        self.assertIn("Pide la comuna", task_a.instructions)
        self.assertNotIn("Pide la comuna", task_b.instructions)
        self.assertIn("retiro en tienda", task_b.instructions)

    def test_inbound_number_scopes_contact_to_its_business(self):
        from zero.crm import CRM
        from zero.memory import SessionMemory
        from zero.orchestrator import Zero

        memory, crm = SessionMemory(None), CRM(None)
        memory.set_client_agent_profile("empresa_a", {"whatsapp_number": "56911111111"})
        memory.set_client_agent_profile("empresa_b", {"whatsapp_number": "56922222222"})
        a = crm.upsert("empresa_a", {"phone": "56999999999", "channel": "whatsapp"})
        b = crm.upsert("empresa_b", {"phone": "56999999999", "channel": "whatsapp"})
        zero = Zero({}, memory=memory, crm=crm)
        with mock.patch.object(zero, "converse_result", return_value={"reply": "Hola", "intent": "general"}), \
             mock.patch.object(zero, "_deliver", return_value={"status": "sent", "via": "test"}):
            reply = zero.handle_inbound("56999999999", "hola", to_phone_id="56922222222")
        self.assertTrue(reply["matched"])
        self.assertEqual(crm.get("empresa_a", a["key"])["stage"], "new")
        self.assertEqual(crm.get("empresa_b", b["key"])["stage"], "replied")
        self.assertIsNone(zero._resolve_inbound_client("56933333333"))

    def test_same_whatsapp_number_cannot_be_assigned_to_two_businesses(self):
        import api
        from fastapi import HTTPException
        from zero.memory import SessionMemory

        memory = SessionMemory(None)
        memory.set_client_agent_profile("empresa_a", {"whatsapp_number": "56911111111"})
        with mock.patch.object(api, "make_memory", return_value=memory):
            with self.assertRaises(HTTPException) as context:
                api.set_agent_profile("empresa_b", api.AgentProfileBody(whatsapp_number="56911111111"))
        self.assertEqual(context.exception.status_code, 409)

    def test_inbound_remembers_only_customer_facts_for_next_turn(self):
        from zero.crm import CRM
        from zero.memory import SessionMemory
        from zero.orchestrator import Zero

        memory, crm = SessionMemory(None), CRM(None)
        memory.set_client_agent_profile("empresa_a", {"whatsapp_number": "56911111111"})
        zero = Zero({}, memory=memory, crm=crm)
        answer = {"reply": "Perfecto, ¿qué modelo buscas?", "intent": "general",
                  "facts": [{"kind": "location", "evidence": "Maipú"},
                            {"kind": "budget", "evidence": "$500.000"}]}
        with mock.patch.object(zero, "converse_result", return_value=answer), \
             mock.patch.object(zero, "_deliver", return_value={"status": "sent", "via": "test"}):
            zero.handle_inbound("56999999999", "Estoy en Maipú", to_phone_id="56911111111")
        facts = memory.get_lead_facts("empresa_a", "56999999999")
        self.assertEqual(facts, [{"kind": "location", "evidence": "Maipú"}])

    def test_new_business_does_not_auto_quote_until_enabled(self):
        from zero.contracts import AgentResponse
        from zero.memory import SessionMemory
        from zero.orchestrator import Zero

        memory = SessionMemory(None)
        memory.set_client_agent_profile("losetaschile", {"quote_mode": "manual", "offer_flow": False})
        memory.set_client_pricing("losetaschile", {"currency": "CLP", "iva_rate": 0.19,
            "items": [{"id": "borde-recto", "name": "Borde recto", "unit_price": 1000}]})
        zero = Zero({}, memory=memory)
        answer = AgentResponse("test", "CONCIERGE", "done", {"reply": "Necesito las medidas"})
        with mock.patch.object(zero, "dispatch", return_value=answer):
            result = zero.converse_result("losetaschile", "precio de 30 borde recto", history=[])
        self.assertNotIn("quote", result)
        self.assertEqual(result["reply"], "Necesito las medidas")

    def test_manual_business_records_inbound_without_sending(self):
        from zero.crm import CRM
        from zero.memory import SessionMemory
        from zero.orchestrator import Zero

        memory, crm = SessionMemory(None), CRM(None)
        memory.set_client_agent_profile("losetaschile", {
            "whatsapp_number": "56964537891", "response_mode": "manual"})
        zero = Zero({}, memory=memory, crm=crm)
        with mock.patch.object(zero, "converse_result") as agent, \
             mock.patch.object(zero, "_deliver") as deliver:
            result = zero.handle_inbound("56999999999", "quiero bordes",
                                         to_phone_id="56964537891")
        self.assertTrue(result["manual_review"])
        self.assertFalse(agent.called)
        self.assertFalse(deliver.called)
        self.assertEqual(memory.get_conversation("losetaschile", "56999999999")[-1]["text"],
                         "quiero bordes")

    def test_alert_throttle_is_sane(self):
        # 0 permitiría un aviso por mensaje: el modo de falla que la ventana evita.
        self.assertGreater(ALERT_THROTTLE_MINUTES, 0)


class FallbackBackendTest(unittest.TestCase):
    """El suplente entra cuando debe, y no antes."""

    def test_primary_answers_when_healthy(self):
        primary, secondary = _Echo("local"), _Echo("pagado")
        b = FallbackBackend(primary, secondary=secondary)
        self.assertEqual(b.complete("s", "u", "m"), "local")
        self.assertEqual(secondary.calls, 0)      # nunca se tocó lo pagado
        self.assertEqual(b.fallbacks, 0)

    def test_secondary_answers_when_primary_fails(self):
        boom, secondary = _Boom(), _Echo("pagado")
        b = FallbackBackend(boom, secondary=secondary)
        self.assertEqual(b.complete("s", "u", "m"), "pagado")
        self.assertEqual(b.fallbacks, 1)

    def test_raises_when_there_is_no_secondary(self):
        # Sin suplente el error tiene que verse, no tragarse en silencio.
        b = FallbackBackend(_Boom(), secondary=None)
        with self.assertRaises(RuntimeError):
            b.complete("s", "u", "m")

    def test_fallback_notifies(self):
        seen = []
        b = FallbackBackend(_Boom(), secondary=_Echo(), on_fallback=seen.append)
        b.complete("s", "u", "m")
        self.assertEqual(len(seen), 1)
        self.assertIsInstance(seen[0], Exception)

    def test_a_broken_alert_never_breaks_the_reply(self):
        # Avisar es secundario: si el aviso explota, el lead igual recibe respuesta.
        def explota(_err):
            raise ValueError("el aviso falló")

        b = FallbackBackend(_Boom(), secondary=_Echo("pagado"), on_fallback=explota)
        self.assertEqual(b.complete("s", "u", "m"), "pagado")


class OwnerAlertTest(unittest.TestCase):
    """El aviso al celular: llega una vez, y nunca rompe nada."""

    def setUp(self):
        alerts.reset_throttle()
        self.addCleanup(alerts.reset_throttle)

    # Estas variables se fijan explícitamente en cada test porque `zero/_env.py`
    # carga el .env real al importar: sin fijarlas, el resultado dependería de la
    # máquina donde corre la suite (y CI, sin .env, daría algo distinto al portátil).
    SIN_CANALES = {"OWNER_WHATSAPP_TO": "", "OWNER_EMAIL_TO": "",
                   "SMTP_FROM": "", "SMTP_USER": ""}

    def test_skipped_without_a_number(self):
        with mock.patch.dict(os.environ, self.SIN_CANALES, clear=False):
            res = alerts.notify_owner("hola", outbox=_RecordingOutbox())
        self.assertEqual(res["status"], "skipped")

    def test_email_cuando_no_hay_whatsapp(self):
        """Sin número configurado el aviso NO se pierde: sale por correo."""
        box = _RecordingOutbox()
        with mock.patch.dict(os.environ, {**self.SIN_CANALES,
                                          "OWNER_EMAIL_TO": "duenio@zeroai.cl"}, clear=False):
            res = alerts.notify_owner("motor caído", outbox=box)
        self.assertEqual(res["status"], "sent")
        self.assertEqual(res["via"], "email")
        self.assertEqual(box.sent[0]["channel"], "email")
        self.assertTrue(box.sent[0].get("subject"), "un correo sin asunto se va a spam")

    def test_sale_por_los_dos_canales_aunque_whatsapp_diga_que_si(self):
        """El aviso NO espera a que WhatsApp falle para usar el correo.

        Una aceptación inicial puede fallar después de forma asíncrona; por eso
        el correo de respaldo se envía de todas formas."""
        box = _RecordingOutbox()
        with mock.patch.dict(os.environ, {**self.SIN_CANALES,
                                          "OWNER_WHATSAPP_TO": "+56900000000",
                                          "OWNER_EMAIL_TO": "duenio@zeroai.cl"}, clear=False):
            res = alerts.notify_owner("motor caído", outbox=box)
        self.assertEqual(res["status"], "sent")
        self.assertEqual([m["channel"] for m in box.sent], ["whatsapp", "email"])
        self.assertIn("whatsapp", res["via"])
        self.assertIn("email", res["via"])

    def test_si_fallan_los_dos_canales_es_error_y_no_quema_la_ventana(self):
        class TodoRoto:
            def __init__(self): self.sent = []
            def send(self, msg, wa_creds=None):
                self.sent.append(msg)
                return {"status": "error", "error": "caído"}

        box = TodoRoto()
        with mock.patch.dict(os.environ, {**self.SIN_CANALES,
                                          "OWNER_WHATSAPP_TO": "+56900000000",
                                          "OWNER_EMAIL_TO": "duenio@zeroai.cl"}, clear=False):
            primero = alerts.notify_owner("uno", outbox=box, now=1000.0)
            segundo = alerts.notify_owner("dos", outbox=box, now=1001.0)
        self.assertEqual(primero["status"], "error")
        self.assertNotEqual(segundo["status"], "throttled")   # pudo reintentar

    def test_sends_to_the_owner(self):
        box = _RecordingOutbox()
        with mock.patch.dict(os.environ, {**self.SIN_CANALES,
                                          "OWNER_WHATSAPP_TO": "+56900000000"}, clear=False):
            res = alerts.notify_owner("motor caído", outbox=box)
        self.assertEqual(res["status"], "sent")
        self.assertEqual(len(box.sent), 1)
        self.assertEqual(box.sent[0]["to"], "+56900000000")
        self.assertEqual(box.sent[0]["channel"], "whatsapp")

    def test_throttled_within_the_window(self):
        box = _RecordingOutbox()
        with mock.patch.dict(os.environ, {**self.SIN_CANALES,
                                          "OWNER_WHATSAPP_TO": "+56900000000"}, clear=False):
            alerts.notify_owner("uno", outbox=box, now=1000.0)
            res = alerts.notify_owner("dos", outbox=box, now=1060.0)   # 60s después
        self.assertEqual(res["status"], "throttled")
        self.assertEqual(len(box.sent), 1)          # el segundo no salió

    def test_sends_again_after_the_window(self):
        box = _RecordingOutbox()
        later = 1000.0 + ALERT_THROTTLE_MINUTES * 60 + 1
        with mock.patch.dict(os.environ, {**self.SIN_CANALES,
                                          "OWNER_WHATSAPP_TO": "+56900000000"}, clear=False):
            alerts.notify_owner("uno", outbox=box, now=1000.0)
            res = alerts.notify_owner("dos", outbox=box, now=later)
        self.assertEqual(res["status"], "sent")
        self.assertEqual(len(box.sent), 2)

    def test_different_kinds_do_not_share_the_window(self):
        box = _RecordingOutbox()
        with mock.patch.dict(os.environ, {**self.SIN_CANALES,
                                          "OWNER_WHATSAPP_TO": "+56900000000"}, clear=False):
            alerts.notify_owner("uno", kind="a", outbox=box, now=1000.0)
            res = alerts.notify_owner("dos", kind="b", outbox=box, now=1001.0)
        self.assertEqual(res["status"], "sent")

    def test_a_failed_send_does_not_burn_the_window(self):
        # Si el envío falla, el próximo mensaje debe poder reintentar el aviso.
        box = _RecordingOutbox(status="error")
        with mock.patch.dict(os.environ, {**self.SIN_CANALES,
                                          "OWNER_WHATSAPP_TO": "+56900000000"}, clear=False):
            alerts.notify_owner("uno", outbox=box, now=1000.0)
            res = alerts.notify_owner("dos", outbox=box, now=1001.0)
        self.assertNotEqual(res["status"], "throttled")

    def test_never_raises(self):
        class Explota:
            def send(self, msg, wa_creds=None):
                raise RuntimeError("red caída")

        with mock.patch.dict(os.environ, {**self.SIN_CANALES,
                                          "OWNER_WHATSAPP_TO": "+56900000000"}, clear=False):
            res = alerts.notify_owner("hola", outbox=Explota())
        self.assertEqual(res["status"], "error")


class TheCageTest(unittest.TestCase):
    """Lo que hace que esto siga siendo una jaula y no una convención."""

    def test_whatsapp_builds_a_local_backend(self):
        import api
        agents, mode = api._agents_whatsapp()
        self.assertEqual(mode, "local")
        backend = agents["CONCIERGE"].backend
        self.assertIsInstance(backend, FallbackBackend)
        self.assertIsInstance(backend.primary, LocalBackend)

    def test_inbound_whatsapp_does_not_use_agents_best(self):
        """El camino de un WhatsApp entrante NO puede pasar por _agents_best.

        _agents_best prefiere la API paga; que WhatsApp lo llame es exactamente
        la regresión que este archivo existe para atrapar.

        Se miran las LLAMADAS reales vía AST y no el texto de la función: un
        comentario que nombre _agents_best no es una llamada a _agents_best.
        """
        import ast
        import inspect
        import textwrap

        import api

        tree = ast.parse(textwrap.dedent(inspect.getsource(api._process_inbound_messages)))
        called = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("_agents_whatsapp", called)
        self.assertNotIn("_agents_best", called)
        self.assertNotIn("_agents_autonomous", called)

    def test_the_rest_of_the_system_still_prefers_quality(self):
        """La jaula NO se extendió: con key de Anthropic, _agents_best sigue pagando."""
        import api
        from zero.backends import AnthropicBackend
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-falsa"}, clear=False):
            with mock.patch.object(AnthropicBackend, "__init__", return_value=None):
                _, mode = api._agents_best()
        self.assertEqual(mode, "live")


class EngineStatusTest(unittest.TestCase):
    """Lo que el panel muestra tiene que salir de la misma política que corre."""

    def test_status_matches_the_policy(self):
        import api
        with mock.patch.dict(os.environ, {"LOCAL_MODEL": "", "LOCAL_MODEL_URL": ""}, clear=False):
            st = api._whatsapp_engine_status()
        self.assertEqual(st["model"], WHATSAPP_ENGINE["model"])
        self.assertEqual(st["base_url"], WHATSAPP_ENGINE["base_url"])

    def test_status_honors_the_env_override(self):
        import api
        with mock.patch.dict(os.environ, {"LOCAL_MODEL": "otro:7b"}, clear=False):
            st = api._whatsapp_engine_status()
        self.assertEqual(st["model"], "otro:7b")

    def test_paid_fallback_stays_disabled_with_a_key(self):
        """Una key guardada no puede activar gastos por sí sola."""
        import api
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-secreta"}, clear=False):
            st = api._whatsapp_engine_status()
        self.assertFalse(st["fallback_to_paid"])
        self.assertFalse(st["fallback_ready"])

    def test_status_never_leaks_the_key(self):
        import api
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-secreta"}, clear=False):
            st = api._whatsapp_engine_status()
        self.assertNotIn("sk-ant-secreta", repr(st))


class IcpLeakTest(unittest.TestCase):
    """CONCIERGE no puede ver a quién SALIMOS A BUSCAR — solo qué vendemos.

    Los campos de segmentación (industry, buyer_roles, regions...) describen al
    lead que queremos encontrar, no al que ya está escribiendo. Filtrarlos a la
    respuesta produce "ayudamos a empresas de mudanzas como la tuya" dicho a
    cualquiera. Pedirlo por prompt no alcanzó con motor local: se corta en el
    mecanismo, y esto lo vigila.
    """

    def _zero_con_icp(self, icp):
        from unittest.mock import MagicMock
        from zero.orchestrator import Zero

        z = Zero.__new__(Zero)                     # sin __init__: no queremos backends
        z.memory = MagicMock()
        z.memory.get_client_icp.return_value = icp
        z.memory.get_client_knowledge.return_value = "ficha de la empresa"
        z.memory.get_client_pricing.return_value = {}
        z.memory.get_conversation.return_value = []
        z.crm = None
        z.vendor_for = lambda _c: {"name": "Fernanda", "tone": "cálido"}
        capturado = {}

        def _dispatch(_agent, payload, **_kw):
            capturado["data"] = payload.data
            return MagicMock(status="done", result={"reply": "ok", "intent": "info"})

        z.dispatch = _dispatch
        return z, capturado

    def test_concierge_only_sees_what_we_sell(self):
        icp = {"sells": "leads B2B", "industry": "empresas de mudanzas",
               "buyer_roles": ["dueño"], "regions": ["RM"],
               "context": "Buscamos empresas de mudanzas para ofrecerles el servicio"}
        z, capturado = self._zero_con_icp(icp)
        z.converse_result("zeroai", "hola", lead={"name": "Marcela"}, history=[])

        visto = capturado["data"]["icp"]
        self.assertEqual(visto, {"sells": "leads B2B"})
        for filtrado in ("industry", "buyer_roles", "regions", "context"):
            self.assertNotIn(filtrado, visto)
        # y que no se cuele por otra puerta del mismo task
        self.assertNotIn("mudanzas", str(capturado["data"]["icp"]))

    def test_an_empty_icp_stays_empty(self):
        z, capturado = self._zero_con_icp({})
        z.converse_result("zeroai", "hola", lead={}, history=[])
        self.assertEqual(capturado["data"]["icp"], {})


class EmailSubjectTest(unittest.TestCase):
    """Ningún correo puede salir sin asunto.

    El transporte cae a "Hola" cuando falta (zero/channels.py), y un correo B2B
    en frío titulado "Hola" desde una dirección desconocida se va a spam. Los
    prompts permiten `subject: null` y el modelo lo aprovecha, así que esto se
    asegura en el mecanismo — igual que la fuga del ICP.
    """

    def test_email_without_subject_gets_one(self):
        from zero.orchestrator import _asunto
        s = _asunto({"channel": "email", "subject": None}, "Mejores Mudanzas")
        self.assertTrue(s)
        self.assertIn("Mejores Mudanzas", s)

    def test_blank_subject_counts_as_missing(self):
        from zero.orchestrator import _asunto
        self.assertTrue(_asunto({"channel": "email", "subject": "   "}, "Acme"))

    def test_a_real_subject_is_respected(self):
        from zero.orchestrator import _asunto
        s = _asunto({"channel": "email", "subject": "Propuesta para Acme"}, "Acme")
        self.assertEqual(s, "Propuesta para Acme")

    def test_whatsapp_keeps_no_subject(self):
        # WhatsApp no tiene asunto: inventarle uno sería ruido, no una mejora.
        from zero.orchestrator import _asunto
        self.assertIsNone(_asunto({"channel": "whatsapp", "subject": None}, "Acme"))

    def test_fallback_survives_a_missing_company(self):
        from zero.config import email_subject_fallback
        for nombre in (None, "", "   "):
            self.assertTrue(email_subject_fallback(nombre).strip())

    def test_fallback_is_a_sane_subject_line(self):
        # Menos de 60 caracteres y sin saltos de línea: una cabecera de correo
        # con \n es inyección de cabeceras, y una larga se corta en el cliente.
        from zero.config import email_subject_fallback
        s = email_subject_fallback("Mudanzas Santiago")
        self.assertLess(len(s), 60)
        self.assertNotIn("\n", s)
        self.assertNotIn("\r", s)


if __name__ == "__main__":
    unittest.main()
