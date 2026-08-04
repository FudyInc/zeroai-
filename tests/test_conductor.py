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
