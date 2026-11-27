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

    def test_script_roles_match_api_roles(self):
        try:
            import api
        except ImportError:
            self.skipTest("fastapi no instalado")
        self.assertEqual(set(LOCAL_LOGIN_ROLES), {"admin", *api._ROLE_ALLOWED})


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
        token = self._login("lucas", self.PASSWORD)   # cro: sin acceso a rutas admin
        self.assertEqual(self._status(self.base, "/api/vendors", token), 403)
        self.assertNotIn(self._status(self.base, "/api/clients", token), (401, 403))

    def test_missing_users_file_with_jwt_secret_rejects_login_and_routes(self):
        self.assertEqual(self._status(self.base_nofile, "/api/login",
                                      body={"username": self.USERNAME, "password": self.PASSWORD}), 401)
        self.assertEqual(self._status(self.base_nofile, "/api/clients"), 401)


if __name__ == "__main__":
    unittest.main()
