"""Login local de emergencia (users.json) cuando Supabase está caído (402).

Cubre el modo de fallo real: Supabase responde 402 a todo, no hay JWT de Supabase
utilizable, y aun así el dashboard debe poder entrar con usuario/contraseña local.
Los servidores corren en subprocesos propios (mismo patrón que test_api_http.py);
el "Supabase caído" es un stub HTTP local que contesta 402 a cualquier cosa.

Correr solo:  python3 -m unittest tests.test_login_local -v
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from tests.test_api_http import _UVICORN_AVAILABLE, _free_port, _start_and_wait
from zero import auth
from zero.config import LOCAL_LOGIN_ROLES


class _Supabase402(BaseHTTPRequestHandler):
    def _respond(self):
        self.send_response(402)
        self.end_headers()

    do_GET = do_POST = do_PUT = _respond

    def log_message(self, *args):
        pass


class _UsersEnv:
    """Apunta AUTH_USERS_PATH a un archivo temporal durante un test."""

    def __init__(self, path: str):
        self.path = path

    def __enter__(self):
        self.prev = os.environ.get("AUTH_USERS_PATH")
        os.environ["AUTH_USERS_PATH"] = self.path
        return self

    def __exit__(self, *exc):
        if self.prev is None:
            os.environ.pop("AUTH_USERS_PATH", None)
        else:
            os.environ["AUTH_USERS_PATH"] = self.prev


class LocalUsersFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "users.json")
        self.env = _UsersEnv(self.path)
        self.env.__enter__()
        self.prev_secret = os.environ.pop("SUPABASE_JWT_SECRET", None)

    def tearDown(self):
        self.env.__exit__()
        if self.prev_secret is not None:
            os.environ["SUPABASE_JWT_SECRET"] = self.prev_secret

    def test_file_written_with_mode_600_and_hashed(self):
        auth.add_user("diego", "contrasena-larga-1", role="admin")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        raw = Path(self.path).read_text("utf-8")
        self.assertNotIn("contrasena-larga-1", raw)
        rec = json.loads(raw)["diego"]
        self.assertEqual(rec["role"], "admin")
        self.assertGreaterEqual(rec["iterations"], 200_000)

    def test_update_keeps_mode_600(self):
        auth.add_user("diego", "contrasena-larga-1")
        os.chmod(self.path, 0o644)
        auth.add_user("lucas", "otra-contrasena-2", role="cro")
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_wrong_and_right_password(self):
        auth.add_user("diego", "contrasena-larga-1")
        self.assertTrue(auth.verify_password("diego", "contrasena-larga-1"))
        self.assertFalse(auth.verify_password("diego", "mala"))
        self.assertFalse(auth.verify_password("nadie", "contrasena-larga-1"))

    def test_role_and_clients_reach_identity(self):
        auth.add_user("op", "contrasena-larga-1", role="operador", clients=["acme"])
        ident = auth.token_identity(auth.make_token("op"))
        self.assertEqual((ident["role"], ident["clients"], ident["source"]),
                         ("operador", ["acme"], "local"))

    def test_legacy_record_without_role_is_admin(self):
        auth.add_user("viejo", "contrasena-larga-1")
        data = json.loads(Path(self.path).read_text("utf-8"))
        del data["viejo"]["role"]
        Path(self.path).write_text(json.dumps(data), "utf-8")
        self.assertEqual(auth.token_identity(auth.make_token("viejo"))["role"], "admin")

    def test_missing_file_without_jwt_secret_is_open_by_design(self):
        self.assertFalse(auth.auth_enabled())
        self.assertFalse(auth.verify_password("diego", "x"))

    def test_missing_file_with_jwt_secret_is_closed(self):
        os.environ["SUPABASE_JWT_SECRET"] = "x"
        try:
            self.assertTrue(auth.auth_enabled())
        finally:
            os.environ.pop("SUPABASE_JWT_SECRET", None)

    def test_corrupt_file_is_closed_and_never_overwritten(self):
        Path(self.path).write_text("{no es json", "utf-8")
        self.assertTrue(auth.auth_enabled())
        self.assertFalse(auth.verify_password("diego", "x"))
        with self.assertRaises(ValueError):
            auth.add_user("diego", "contrasena-larga-1")
        self.assertEqual(Path(self.path).read_text("utf-8"), "{no es json")

    def test_existing_empty_file_keeps_auth_on_and_remove_user_cannot_open_app(self):
        Path(self.path).write_text("{}", "utf-8")
        self.assertTrue(auth.auth_enabled())
        os.unlink(self.path)
        auth.add_user("diego", "contrasena-larga-1")
        self.assertTrue(auth.remove_user("diego"))
        self.assertTrue(auth.auth_enabled())

    def test_add_user_enforces_min_password_length(self):
        for bad in ("", "corta"):
            with self.assertRaises(ValueError):
                auth.add_user("diego", bad)
        self.assertFalse(os.path.exists(self.path))

    def test_unknown_user_costs_a_pbkdf2_too(self):
        from unittest import mock
        with mock.patch.object(auth.hashlib, "pbkdf2_hmac", wraps=auth.hashlib.pbkdf2_hmac) as m:
            self.assertFalse(auth.verify_password("nadie", "x"))
        self.assertEqual(m.call_count, 1)

    def test_non_ascii_hash_or_signature_is_invalid_not_500(self):
        auth.add_user("diego", "contrasena-larga-1")
        data = json.loads(Path(self.path).read_text("utf-8"))
        data["diego"]["hash"] = "ñandú"
        Path(self.path).write_text(json.dumps(data), "utf-8")
        self.assertFalse(auth.verify_password("diego", "contrasena-larga-1"))
        self.assertIsNone(auth.token_username("diego.9999999999.ñññ"))

    def test_script_roles_match_api_roles(self):
        try:
            import api
        except ImportError:
            self.skipTest("fastapi no instalado")
        self.assertEqual(set(LOCAL_LOGIN_ROLES), {"admin", *api._ROLE_ALLOWED})


class LoginTableFullTest(unittest.TestCase):
    """Con la tabla de intentos llena, el usuario real debe seguir limitado."""

    def setUp(self):
        try:
            import api
        except ImportError:
            self.skipTest("fastapi no instalado")
        from unittest import mock
        self.api = api
        api._login_fails.clear()
        p = mock.patch.object(api, "LOGIN_MAX_TRACKED_KEYS", 50)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(api._login_fails.clear)

    def _fill(self, prefijo):
        for i in range(200):   # 4x el tope
            self.api._login_register_fail(f"u:falso{i}", f"ip:9.9.{i}.1") if prefijo == "both" \
                else self.api._login_register_fail("u:falso", f"ip:8.8.{i}.1")
            self.assertLessEqual(len(self.api._login_fails), 50)

    def test_user_still_limited_after_flooding_with_fake_keys(self):
        from zero.config import LOGIN_MAX_FAILS_PER_USER
        self._fill("both")
        for _ in range(LOGIN_MAX_FAILS_PER_USER):
            self.api._login_register_fail("u:diego", "ip:7.7.7.7")
        self.assertTrue(self.api._login_blocked("u:diego", "ip:1.1.1.1"))

    def test_ip_key_never_evicts_a_user_key(self):
        from zero.config import LOGIN_MAX_FAILS_PER_USER
        for _ in range(LOGIN_MAX_FAILS_PER_USER):
            self.api._login_register_fail("u:diego", "ip:7.7.7.7")
        self._fill("ips")
        self.assertTrue(self.api._login_blocked("u:diego", "ip:1.1.1.1"))

    def test_overlong_username_is_rejected_without_growing_table(self):
        from fastapi import HTTPException
        from starlette.requests import Request
        req = Request({"type": "http", "headers": [], "client": ("1.2.3.4", 1)})
        body = self.api.Login(username="a" * 5000, password="x")
        with self.assertRaises(HTTPException) as ctx:
            self.api.login(body, req)
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertEqual(self.api._login_fails, {})


@unittest.skipUnless(_UVICORN_AVAILABLE, "uvicorn no instalado — este test es opcional, no núcleo")
class LocalLoginSupabaseDownTest(unittest.TestCase):
    USERNAME = "diego"
    PASSWORD = "contrasena-larga-1"

    @classmethod
    def _start(cls, users_path: str):
        port = _free_port()
        base = f"http://127.0.0.1:{port}"
        env = dict(os.environ)
        env.update({
            "AUTH_USERS_PATH": users_path,
            "SUPABASE_URL": f"http://127.0.0.1:{cls.stub.server_port}",   # responde 402
            "SUPABASE_KEY": "k",
            "SUPABASE_JWT_SECRET": "secreto-de-prueba",   # como en producción
            "LOCAL_MODEL": "", "ANTHROPIC_API_KEY": "", "OPENAI_API_KEY": "",
            "ZERO_PIPELINE_MOCK_OK": "1",
        })
        repo_root = Path(__file__).resolve().parent.parent
        proc = _start_and_wait(
            [sys.executable, "-m", "uvicorn", "api:app", "--port", str(port), "--log-level", "warning"],
            str(repo_root), env, base)
        return base, proc

    @classmethod
    def setUpClass(cls):
        cls.stub = HTTPServer(("127.0.0.1", 0), _Supabase402)
        threading.Thread(target=cls.stub.serve_forever, daemon=True).start()
        tmp = tempfile.mkdtemp()
        cls.users_path = os.path.join(tmp, "users.json")
        with _UsersEnv(cls.users_path):
            auth.add_user(cls.USERNAME, cls.PASSWORD, role="admin")
            auth.add_user("lucas", cls.PASSWORD, role="cro")
            auth.add_user("analista", cls.PASSWORD, role="cro")
        cls.base, cls.proc = cls._start(cls.users_path)
        cls.base_nofile, cls.proc_nofile = cls._start(os.path.join(tmp, "no-existe.json"))

    @classmethod
    def tearDownClass(cls):
        for p in (cls.proc, cls.proc_nofile):
            p.terminate()
            p.wait(timeout=5)
        cls.stub.shutdown()

    def _call(self, base, path, token=None, body=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode())

    def _status(self, base, path, token=None, body=None):
        try:
            return self._call(base, path, token, body)[0]
        except urllib.error.HTTPError as e:
            return e.code

    def _login(self, user, pw):
        return self._call(self.base, "/api/login", body={"username": user, "password": pw})[1]["token"]

    def test_login_ok_and_protected_routes_work_with_local_token(self):
        token = self._login(self.USERNAME, self.PASSWORD)
        self.assertEqual(self._status(self.base, "/api/vendors", token), 200)
        # /api/clients lee de Supabase (caído): pasa la auth y falla en datos
        # (503), nunca 401/403 — el login local no arregla la capa de datos.
        self.assertNotIn(self._status(self.base, "/api/clients", token), (401, 403))
        _, st = self._call(self.base, "/api/auth/status", token)
        self.assertEqual((st["authenticated"], st["username"], st["role"]), (True, "diego", "admin"))

    def test_no_token_is_401(self):
        self.assertEqual(self._status(self.base, "/api/clients"), 401)

    def test_wrong_password_is_401(self):
        self.assertEqual(self._status(self.base, "/api/login", body={"username": self.USERNAME, "password": "mala"}), 401)

    def test_unknown_user_is_401(self):
        self.assertEqual(self._status(self.base, "/api/login", body={"username": "nadie", "password": self.PASSWORD}), 401)

    def test_forged_token_is_401(self):
        self.assertEqual(self._status(self.base, "/api/clients", "diego.9999999999.abc"), 401)

    def test_role_is_enforced_for_local_users(self):
        token = self._login("analista", self.PASSWORD)   # cro: sin acceso a rutas admin
        self.assertEqual(self._status(self.base, "/api/vendors", token), 403)
        self.assertNotIn(self._status(self.base, "/api/clients", token), (401, 403))

    def _login_raw(self, user, pw, xff):
        req = urllib.request.Request(
            self.base + "/api/login", method="POST",
            data=json.dumps({"username": user, "password": pw}).encode(),
            headers={"Content-Type": "application/json", "X-Forwarded-For": xff})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_per_user_lockout_does_not_block_other_users(self):
        from zero.config import LOGIN_MAX_FAILS_PER_USER
        for i in range(LOGIN_MAX_FAILS_PER_USER):
            self.assertEqual(self._login_raw("lucas", "mala", f"10.0.0.{i}"), 401)
        # bloqueado aunque la contraseña sea buena y la IP sea otra...
        self.assertEqual(self._login_raw("lucas", self.PASSWORD, "10.9.9.9"), 429)
        # ...pero otro usuario sigue entrando: no hay tope global.
        self.assertEqual(self._login_raw(self.USERNAME, self.PASSWORD, "10.8.8.8"), 200)

    def test_per_ip_lockout_is_secondary_and_scoped_to_that_ip(self):
        from zero.config import LOGIN_MAX_FAILS_PER_IP
        for i in range(LOGIN_MAX_FAILS_PER_IP):
            self.assertEqual(self._login_raw(f"inventado{i}", "x", "172.16.0.1"), 401)
        self.assertEqual(self._login_raw(self.USERNAME, self.PASSWORD, "172.16.0.1"), 429)
        self.assertEqual(self._login_raw(self.USERNAME, self.PASSWORD, "172.16.0.2"), 200)

    def test_missing_users_file_with_jwt_secret_rejects_login_and_routes(self):
        self.assertEqual(self._status(self.base_nofile, "/api/login",
                                      body={"username": self.USERNAME, "password": self.PASSWORD}), 401)
        self.assertEqual(self._status(self.base_nofile, "/api/clients"), 401)


if __name__ == "__main__":
    unittest.main()
