"""Red de seguridad de Conductor (zero/conductor.py) — el panel que lanza
terminales reales de Claude Code desde el dashboard.

Ninguno de estos tests lanza un proceso `claude` de verdad: eso cuesta tokens,
necesita el login del CLI y haría la suite dependiente de la red. Lo que sí se
prueba es todo lo que rodea a ese proceso — catálogos, el guard de sesión
única, el registro/reparto de eventos y el envío de un turno — con un proceso
falso en la frontera (mismo criterio mock-first del resto del repo: el mock es
fiel al contrato, no una versión distinta).

Stdlib puro. Correr solo:  python3 -m unittest tests.test_conductor -v
"""
from __future__ import annotations

import asyncio
import os
import unittest

from zero import conductor


# --- proceso falso en la frontera del subprocess -----------------------------

class _FakeStdin:
    def __init__(self, fail: bool = False):
        self.written: list[bytes] = []
        self.fail = fail

    def write(self, data: bytes) -> None:
        if self.fail:
            raise BrokenPipeError("el proceso ya no está ahí")
        self.written.append(data)

    async def drain(self) -> None:
        return None


class _FakeProc:
    """La parte de asyncio.subprocess.Process que Session realmente toca."""

    def __init__(self, fail: bool = False):
        self.pid = 4242
        self.returncode = None
        self.stdin = _FakeStdin(fail)
        self.stdout = None
        self.stderr = None


def _session(session_id: str, *, model: str | None = "sonnet", fail: bool = False) -> conductor.Session:
    return conductor.Session(session_id, "consultas", "/tmp/worktree-falso", "main",
                             _FakeProc(fail), None, model=model)


class RolesCatalogTest(unittest.TestCase):
    """El catálogo es el contrato que consume el frontend."""

    def setUp(self):
        self.roles = conductor.roles_catalog()

    def test_ids_are_unique(self):
        ids = [r["id"] for r in self.roles]
        self.assertEqual(len(ids), len(set(ids)))

    def test_no_role_carries_an_emoji(self):
        """Los emoji se sacaron a propósito: se dibujan con la fuente del
        sistema operativo, así que el mismo panel se veía distinto en cada
        máquina. La identidad de cada rol la pone un icono en el frontend."""
        for r in self.roles:
            self.assertNotIn("emoji", r, r["id"])

    def test_default_model_is_selectable_or_cli_default(self):
        valid = {m["id"] for m in conductor.models_catalog()}
        for r in self.roles:
            self.assertIn(r["default_model"], valid | {None}, r["id"])

    def test_every_role_declares_permission_mode_and_write_zone(self):
        for r in self.roles:
            self.assertTrue(r["permission_mode"], r["id"])
            self.assertTrue(r["write_zone_hint"], r["id"])

    def test_consultas_stays_read_only(self):
        """CONSULTAS es el único rol seguro para preguntar sin arriesgar
        ediciones — si deja de estar en modo plan, deja de serlo."""
        consultas = next(r for r in self.roles if r["id"] == "consultas")
        self.assertEqual(consultas["permission_mode"], "plan")


class ModelsCatalogTest(unittest.TestCase):
    def test_shape(self):
        models = conductor.models_catalog()
        self.assertTrue(models)
        for m in models:
            self.assertTrue(m["id"] and m["label"] and m["hint"])

    def test_catalog_is_a_copy(self):
        """El caller no debe poder mutar la lista del módulo sin querer."""
        conductor.models_catalog().clear()
        self.assertTrue(conductor.models_catalog())


class SessionGuardTest(unittest.TestCase):
    """Una sesión por (rol, worktree) — el modelo NO entra en la clave, así el
    mismo rol no puede abrir tres terminales en paralelo cambiando de modelo."""

    def setUp(self):
        self.guard = conductor.SessionGuard()

    def test_second_start_for_same_key_is_blocked(self):
        self.assertTrue(self.guard.try_start(("worker", "/repo"), "s1"))
        self.assertFalse(self.guard.try_start(("worker", "/repo"), "s2"))
        self.assertEqual(self.guard.existing(("worker", "/repo")), "s1")

    def test_other_role_same_worktree_is_allowed(self):
        self.assertTrue(self.guard.try_start(("worker", "/repo"), "s1"))
        self.assertTrue(self.guard.try_start(("debug", "/repo"), "s2"))

    def test_finish_frees_the_slot(self):
        self.guard.try_start(("worker", "/repo"), "s1")
        self.guard.finish(("worker", "/repo"))
        self.assertIsNone(self.guard.existing(("worker", "/repo")))
        self.assertTrue(self.guard.try_start(("worker", "/repo"), "s3"))


class RecordEventTest(unittest.TestCase):
    def setUp(self):
        self.session = _session("rec-1")

    def test_stored_event_reaches_buffer_and_subscribers(self):
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        self.session.subscribers.add(q)
        conductor._record_event(self.session, {"type": "assistant"})
        self.assertEqual(len(self.session.messages), 1)
        self.assertEqual(q.qsize(), 1)

    def test_unstored_event_is_broadcast_but_not_buffered(self):
        """Los deltas token a token se reparten en vivo pero no se guardan: son
        miles por turno y llenarían los 500 slots del buffer de replay en un
        par de frases, tirando afuera el historial de verdad."""
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        self.session.subscribers.add(q)
        conductor._record_event(self.session, {"type": "stream_event"}, store=False)
        self.assertEqual(len(self.session.messages), 0)
        self.assertEqual(q.qsize(), 1)

    def test_result_event_clears_turn_in_flight(self):
        self.session.turn_in_flight = True
        conductor._record_event(self.session, {"type": "result", "subtype": "success"})
        self.assertFalse(self.session.turn_in_flight)

    def test_init_event_captures_claude_session_id(self):
        conductor._record_event(self.session, {
            "type": "system", "subtype": "init", "session_id": "abc-123"})
        self.assertEqual(self.session.claude_session_id, "abc-123")

    def test_full_subscriber_queue_is_dropped_not_raised(self):
        """Un cliente que dejó de leer no puede tumbar la sesión de los demás."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        q.put_nowait({"type": "relleno"})
        self.session.subscribers.add(q)
        conductor._record_event(self.session, {"type": "assistant"})
        self.assertNotIn(q, self.session.subscribers)


class SendTurnTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.ids: list[str] = []

    def tearDown(self):
        for sid in self.ids:
            conductor._SESSIONS.pop(sid, None)

    def _register(self, sid: str, **kw) -> conductor.Session:
        s = _session(sid, **kw)
        conductor._SESSIONS[sid] = s
        self.ids.append(sid)
        return s

    async def test_user_turn_is_recorded_in_the_transcript(self):
        """El CLI no devuelve el turno del humano por stdout — si no lo
        registramos acá, lo que escribe el usuario no existe en ninguna parte
        y el historial queda como un monólogo del asistente."""
        s = self._register("turn-1")
        await conductor.send_turn("turn-1", "hola terminal")
        users = [e for e in s.messages if e.get("type") == "user"]
        self.assertEqual(len(users), 1)
        blocks = users[0]["message"]["content"]
        self.assertEqual(blocks[0]["type"], "text")
        self.assertEqual(blocks[0]["text"], "hola terminal")

    async def test_user_turn_shape_matches_assistant_blocks(self):
        """Misma forma que un evento `assistant` (content = lista de bloques)
        para que el frontend recorra ambos con el mismo código."""
        s = self._register("turn-2")
        await conductor.send_turn("turn-2", "x")
        content = [e for e in s.messages if e["type"] == "user"][0]["message"]["content"]
        self.assertIsInstance(content, list)

    async def test_turn_is_written_to_the_process_stdin(self):
        s = self._register("turn-3")
        await conductor.send_turn("turn-3", "ping")
        self.assertTrue(s.process.stdin.written)
        self.assertIn(b"ping", s.process.stdin.written[0])

    async def test_second_turn_while_one_is_in_flight_is_rejected(self):
        s = self._register("turn-4")
        s.turn_in_flight = True
        with self.assertRaises(RuntimeError):
            await conductor.send_turn("turn-4", "otro")

    async def test_turn_on_a_dead_session_is_rejected(self):
        s = self._register("turn-5")
        s.status = "crashed"
        with self.assertRaises(RuntimeError):
            await conductor.send_turn("turn-5", "hola")

    async def test_broken_pipe_clears_turn_in_flight(self):
        """Carrera real: el proceso muere entre el chequeo de status y la
        escritura. Sin el rescate, turn_in_flight quedaba en True para siempre
        y esa sesión no volvía a aceptar un turno nunca más."""
        s = self._register("turn-6", fail=True)
        with self.assertRaises(RuntimeError):
            await conductor.send_turn("turn-6", "hola")
        self.assertFalse(s.turn_in_flight)

    async def test_unknown_session_raises_keyerror(self):
        with self.assertRaises(KeyError):
            await conductor.send_turn("no-existe", "hola")


class StartSessionValidationTest(unittest.IsolatedAsyncioTestCase):
    """Validación previa a lanzar nada — no llega a crear un subproceso."""

    async def test_unknown_role_raises_keyerror(self):
        with self.assertRaises(KeyError):
            await conductor.start_session("rol-inventado")

    async def test_unknown_model_raises_valueerror(self):
        with self.assertRaises(ValueError):
            await conductor.start_session("consultas", model="gpt-inventado")

    async def test_unknown_model_does_not_leak_a_guard_slot(self):
        """Un modelo inválido no puede dejar el rol bloqueado para siempre."""
        with self.assertRaises(ValueError):
            await conductor.start_session("consultas", model="no-existe")
        self.assertIsNone(conductor._GUARD.existing(("consultas", str(conductor.REPO_ROOT))))


class SessionSummaryTest(unittest.TestCase):
    def test_summary_exposes_model_and_no_emoji(self):
        s = _session("sum-1", model="haiku")
        summary = s.summary()
        self.assertEqual(summary["model"], "haiku")
        self.assertNotIn("role_emoji", summary)
        self.assertEqual(summary["status"], "running")

    def test_delete_running_session_is_refused(self):
        s = _session("sum-2")
        conductor._SESSIONS[s.id] = s
        try:
            with self.assertRaises(RuntimeError):
                conductor.delete_session(s.id)
        finally:
            conductor._SESSIONS.pop(s.id, None)

    def test_delete_unknown_session_returns_false(self):
        self.assertFalse(conductor.delete_session("no-existe"))


class LocalEngineCatalogTest(unittest.TestCase):
    """El modelo local se ofrece solo si esta máquina lo tiene configurado y
    levantado — y cuando se ofrece, va marcado como SIN herramientas."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("LOCAL_MODEL", "LOCAL_MODEL_URL")}
        conductor._LOCAL_PROBE.update({"at": 0.0, "ok": False})

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        conductor._LOCAL_PROBE.update({"at": 0.0, "ok": False})

    def test_without_local_model_configured_it_is_not_offered(self):
        os.environ.pop("LOCAL_MODEL", None)
        ids = {m["id"] for m in conductor.models_catalog()}
        self.assertNotIn(conductor.LOCAL_MODEL_ID, ids)

    def test_claude_models_are_always_offered(self):
        os.environ.pop("LOCAL_MODEL", None)
        ids = {m["id"] for m in conductor.models_catalog()}
        self.assertEqual(ids, {"opus", "sonnet", "haiku"})

    def test_unreachable_endpoint_is_not_offered(self):
        """Configurado pero caído: la opción no aparece, en vez de aparecer y
        fallar recién cuando el usuario aprieta Iniciar."""
        os.environ["LOCAL_MODEL"] = "modelo-de-prueba"
        os.environ["LOCAL_MODEL_URL"] = "http://127.0.0.1:9/v1"   # puerto descarte
        ids = {m["id"] for m in conductor.models_catalog()}
        self.assertNotIn(conductor.LOCAL_MODEL_ID, ids)

    def test_every_claude_model_declares_tools(self):
        for m in conductor.models_catalog():
            self.assertIn("engine", m)
            self.assertIn("tools", m)
            if m["engine"] == "claude":
                self.assertTrue(m["tools"], m["id"])


class LocalSystemPromptTest(unittest.TestCase):
    def test_prompt_states_there_are_no_tools(self):
        """Sin este aviso el modelo responde como si hubiera abierto los
        archivos que su prompt de rol menciona — alucinación con forma de
        trabajo hecho."""
        role = conductor.ROLES["worker"]
        prompt = conductor._local_system_prompt(role)
        self.assertIn(role.system_prompt, prompt)
        low = prompt.lower()
        self.assertIn("no tienes herramientas", low)
        self.assertIn("pegue", low)

    def test_works_without_a_role(self):
        self.assertTrue(conductor._local_system_prompt(None))


class LocalStreamParsingTest(unittest.TestCase):
    """El parseo del SSE contra la forma real que devuelve Ollama (capturada
    del endpoint en vivo), sin tocar la red."""

    def _parse(self, body: str):
        chunks = []

        class _FakeResp:
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *a): return False
            def __iter__(self_inner): return iter(body.encode("utf-8").splitlines(True))

        real = conductor.urllib.request.urlopen
        conductor.urllib.request.urlopen = lambda *a, **k: _FakeResp()
        try:
            conductor._stream_local_chat("http://x/v1/chat/completions", {}, chunks.append)
        finally:
            conductor.urllib.request.urlopen = real
        return chunks

    def test_collects_content_deltas_in_order(self):
        body = (
            'data: {"choices":[{"delta":{"content":"Hola"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":" mundo"}}]}\n\n'
            'data: [DONE]\n\n'
        )
        self.assertEqual(self._parse(body), ["Hola", " mundo"])

    def test_ignores_empty_and_malformed_lines(self):
        body = (
            '\n'
            'data: no-es-json\n'
            'data: {"choices":[{"delta":{}}]}\n'
            'data: {"choices":[{"delta":{"content":"ok"}}]}\n'
            'data: [DONE]\n'
        )
        self.assertEqual(self._parse(body), ["ok"])

    def test_stops_at_done_marker(self):
        body = (
            'data: {"choices":[{"delta":{"content":"a"}}]}\n'
            'data: [DONE]\n'
            'data: {"choices":[{"delta":{"content":"no-deberia-llegar"}}]}\n'
        )
        self.assertEqual(self._parse(body), ["a"])


class LocalSessionTest(unittest.IsolatedAsyncioTestCase):
    """La sesión local emite el MISMO contrato de eventos que el motor
    `claude` — es lo que permite que el WebSocket y toda la UI del chat no
    sepan cuál de los dos está detrás."""

    def _session(self, sid="loc-1"):
        s = conductor.LocalSession(sid, "consultas", "/tmp/wt", "main", None,
                                   model=conductor.LOCAL_MODEL_ID,
                                   endpoint="http://x/v1/chat/completions",
                                   model_name="modelo-falso")
        conductor._SESSIONS[sid] = s
        self.addCleanup(lambda: conductor._SESSIONS.pop(sid, None))
        return s

    def _fake_stream(self, pieces, fail=None):
        def _impl(endpoint, payload, on_delta, timeout=300.0):
            if fail:
                raise RuntimeError(fail)
            for p in pieces:
                on_delta(p)
        return _impl

    async def test_turn_emits_deltas_then_assistant_then_result(self):
        s = self._session()
        real = conductor._stream_local_chat
        conductor._stream_local_chat = self._fake_stream(["ho", "la"])
        try:
            await conductor.send_turn(s.id, "saluda")
            await s.turn_task
        finally:
            conductor._stream_local_chat = real

        types = [e["type"] for e in s.messages]
        self.assertEqual(types, ["user", "assistant", "result"])   # deltas no se guardan
        texto = s.messages[1]["message"]["content"][0]["text"]
        self.assertEqual(texto, "hola")
        self.assertFalse(s.turn_in_flight)

    async def test_local_session_reports_no_tools(self):
        s = self._session("loc-2")
        summary = s.summary()
        self.assertEqual(summary["engine"], "local")
        self.assertFalse(summary["tools"])
        self.assertIsNone(summary["pid"])

    async def test_history_grows_with_each_turn(self):
        s = self._session("loc-3")
        real = conductor._stream_local_chat
        conductor._stream_local_chat = self._fake_stream(["ok"])
        try:
            await conductor.send_turn(s.id, "uno")
            await s.turn_task
        finally:
            conductor._stream_local_chat = real
        self.assertEqual(s.history, [{"role": "user", "content": "uno"},
                                     {"role": "assistant", "content": "ok"}])

    async def test_backend_failure_becomes_a_result_error_not_a_crash(self):
        """Un Ollama caído a mitad de turno se reporta en el chat y libera la
        sesión — no deja el turno colgado para siempre."""
        s = self._session("loc-4")
        real = conductor._stream_local_chat
        conductor._stream_local_chat = self._fake_stream([], fail="conexión rechazada")
        try:
            await conductor.send_turn(s.id, "hola")
            await s.turn_task
        finally:
            conductor._stream_local_chat = real
        last = s.messages[-1]
        self.assertEqual(last["type"], "result")
        self.assertEqual(last["subtype"], "error")
        self.assertFalse(s.turn_in_flight)

    async def test_failure_after_taking_the_guard_frees_the_role(self):
        """Regresión (encontrada en vivo): al crear la sesión local se lanzaba
        un AttributeError DESPUÉS de tomar el guard, así que el rol quedaba
        bloqueado para siempre y todo intento posterior recibía un 409 'ya hay
        una sesión corriendo' sin que existiera ninguna."""
        key = ("consultas", str(conductor.REPO_ROOT))
        real_reach, real_cls = conductor._local_reachable, conductor.LocalSession
        conductor._local_reachable = lambda force=False: True
        conductor.LocalSession = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        os.environ.setdefault("LOCAL_MODEL", "modelo-de-prueba")
        try:
            with self.assertRaises(RuntimeError):
                await conductor.start_session("consultas", model=conductor.LOCAL_MODEL_ID)
        finally:
            conductor._local_reachable, conductor.LocalSession = real_reach, real_cls
        self.assertIsNone(conductor._GUARD.existing(key))

    async def test_stop_closes_a_local_session_without_a_process(self):
        s = self._session("loc-5")
        stopped = await conductor.stop_session(s.id)
        self.assertEqual(stopped.status, "killed")
        self.assertIsNotNone(stopped.ended_at)
        self.assertEqual(s.messages[-1]["type"], "status")


class ShutdownTest(unittest.TestCase):
    """Regresión de producción (2026-08-04): con una pestaña del panel abierta,
    `systemctl restart` se colgaba ~90s hasta el SIGKILL de systemd — el
    handler del WebSocket esperaba en queue.get() para siempre y uvicorn no
    completa su apagado elegante mientras haya una conexión viva. El backend
    quedaba caído todo ese rato, webhooks de Twilio incluidos."""

    def setUp(self):
        self.session = _session("shut-1")
        conductor._SESSIONS[self.session.id] = self.session
        self.addCleanup(lambda: conductor._SESSIONS.pop(self.session.id, None))

    def test_subscribers_get_the_shutdown_sentinel(self):
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        self.session.subscribers.add(q)
        conductor.shutdown()
        self.assertIs(q.get_nowait(), conductor.SHUTDOWN)

    def test_subscribers_are_cleared(self):
        q: asyncio.Queue = asyncio.Queue(maxsize=10)
        self.session.subscribers.add(q)
        conductor.shutdown()
        self.assertEqual(self.session.subscribers, set())

    def test_live_processes_are_terminated(self):
        terminated = []
        self.session.process.terminate = lambda: terminated.append(True)
        conductor.shutdown()
        self.assertTrue(terminated)

    def test_shutdown_never_raises_on_a_full_queue(self):
        """Un cliente que dejó de leer no puede impedir que el backend cierre."""
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        q.put_nowait({"type": "relleno"})
        self.session.subscribers.add(q)
        conductor.shutdown()   # no debe lanzar

    def test_shutdown_with_a_local_session_does_not_raise(self):
        """LocalSession no tiene `process` — el apagado no puede asumir que sí."""
        s = conductor.LocalSession("shut-2", "consultas", "/tmp", "main", None)
        conductor._SESSIONS[s.id] = s
        self.addCleanup(lambda: conductor._SESSIONS.pop(s.id, None))
        conductor.shutdown()


class AvailabilityTest(unittest.TestCase):
    """is_available/list_worktrees son el gate de la página entera: si lanzan
    en vez de degradar, se cae la vista completa en un servidor sin `claude`."""

    def test_is_available_returns_a_tuple_and_never_raises(self):
        ok, reason = conductor.is_available()
        self.assertIsInstance(ok, bool)
        if not ok:
            self.assertTrue(reason)

    def test_list_worktrees_returns_a_list(self):
        self.assertIsInstance(conductor.list_worktrees(), list)


if __name__ == "__main__":
    unittest.main()
