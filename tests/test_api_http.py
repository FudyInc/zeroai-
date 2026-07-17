"""End-to-end HTTP tests — the one layer test_core.py deliberately skips.

test_core.py calls Python functions/classes directly (Zero.run_pipeline, CRM.upsert,
...) — it never goes through a real HTTP request. That leaves a real gap: a request
could break at the FastAPI/Pydantic/auth-middleware/CORS layer while every function
underneath keeps working, and the 297 logic tests would stay green.

This file starts the real `api.py` server as a subprocess (uvicorn) and hits it with
real HTTP requests, using only stdlib (`subprocess` + `urllib`) — no `httpx`/TestClient,
so it adds zero new dependencies beyond what `api.py` already requires to run at all
(fastapi + uvicorn). Deliberately kept separate from test_core.py: that file's whole
point is running with no dependencies beyond stdlib, and this one can't make that
promise (it needs a working `uvicorn`, same as actually running the server would).

If fastapi/uvicorn aren't installed, this file skips itself instead of failing the
whole suite: `python3 -m unittest discover -s tests -t .` includes it automatically
if the imports are present, and just reports "skipped" cleanly if not.

Run alone:  python3 -m unittest tests.test_api_http -v
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

try:
    import uvicorn  # noqa: F401
    _UVICORN_AVAILABLE = True
except ImportError:
    _UVICORN_AVAILABLE = False


def _free_port() -> int:
    """Ask the OS for an unused local port instead of hardcoding one — avoids
    clashing with a dev server (:8800) or another test run."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_up(proc: subprocess.Popen, base: str, timeout: float = 30.0) -> None:
    """Poll /api/health until the subprocess server answers, or raise. Shared by
    every test class in this file that spins up its own api.py subprocess."""
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"uvicorn murió antes de arrancar (exit {proc.returncode})")
        try:
            with urllib.request.urlopen(f"{base}/api/health", timeout=1) as r:
                if r.status == 200:
                    return
        except Exception as e:   # noqa: BLE001 — reintenta hasta el timeout
            last_err = e
        time.sleep(0.3)
    raise RuntimeError(f"el servidor no respondió a tiempo en {base}: {last_err}")


def _spawn_uvicorn(argv: list[str], cwd: str, env: dict) -> subprocess.Popen:
    return subprocess.Popen(
        argv, cwd=cwd, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def _start_and_wait(argv: list[str], cwd: str, env: dict, base: str) -> subprocess.Popen:
    """Arranca el subproceso uvicorn y espera a que conteste /api/health, con UN
    reintento completo (matar y relanzar) si el primer arranque no llega a tiempo.

    Encontrado corriendo esta suite completa varias veces seguidas (2026-07-09):
    en aislado, ApiHttpTest/ApiAuthHttpTest siempre arrancan en ~1-2s; pero dentro
    de `unittest discover` completo (36 archivos, algunos con sus propios
    subprocesos) el arranque de ESTE proceso puntual a veces se pasaba de 30s —
    contención de CPU/proceso del entorno, no un problema de api.py. Subir el
    timeout a mano no alcanzaba de forma confiable; un reintento sí, porque un
    segundo arranque casi nunca compite con el mismo pico de carga que tumbó al
    primero."""
    proc = _spawn_uvicorn(argv, cwd, env)
    try:
        _wait_until_up(proc, base)
        return proc
    except Exception:
        proc.kill()
        proc.wait(timeout=5)
    proc = _spawn_uvicorn(argv, cwd, env)
    try:
        _wait_until_up(proc, base)
    except Exception:
        proc.kill()
        raise
    return proc


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_supabase_jwt(secret: str, *, email: str = "test@zeroai.cl",
                       role: str | None = "admin", exp_delta: int = 3600) -> str:
    """Arma un JWT con la misma forma/firma que produce Supabase Auth (HS256,
    base64url, app_metadata.role) — sin pyjwt, para probar zero/auth.py y el
    auth_guard de api.py sin depender de una cuenta real de Supabase."""
    header = {"alg": "HS256", "typ": "JWT"}
    app_metadata = {"role": role} if role is not None else {}
    payload = {"email": email, "exp": int(time.time()) + exp_delta, "app_metadata": app_metadata}
    header_b64 = _b64url(json.dumps(header).encode())
    payload_b64 = _b64url(json.dumps(payload).encode())
    sig = hmac.new(secret.encode("utf-8"), f"{header_b64}.{payload_b64}".encode("ascii"),
                   hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url(sig)}"


@unittest.skipUnless(_UVICORN_AVAILABLE, "uvicorn no instalado — este test es opcional, no núcleo")
class ApiHttpTest(unittest.TestCase):
    """Levanta api.py real y prueba de punta a punta: petición -> FastAPI ->
    middleware de auth -> handler -> respuesta JSON. Solo lectura — no manda
    ningún mensaje ni corre el pipeline, así que no ensucia crm.json/state.json
    reales (mismo tipo de chequeo que se hizo a mano varias veces hoy)."""

    WHATSAPP_APP_SECRET = "test-secret-para-el-webhook"

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        repo_root = Path(__file__).resolve().parent.parent
        env = dict(os.environ)
        # Vacío, no ausente: zero/_env.py::load_env usa os.environ.setdefault, así
        # que si la key falta del todo y existe un .env real en el repo (como en
        # producción) con AUTH_PASSWORD configurada, el subproceso la vuelve a
        # levantar de ahí y este test class deja de estar realmente "sin auth" —
        # encontrado corriendo esta suite en el Ubuntu de producción, donde esto
        # causaba 401 en vez de 200/404 en tres tests. Un valor vacío sí queda
        # "presente" para setdefault, y auth_enabled() lo trata como deshabilitado
        # (bool('') es False) — sin auth de verdad, sin importar qué haya en el
        # .env del repo.
        env["AUTH_PASSWORD"] = ""  # legado, zero/auth.py ya no lo lee — inofensivo, se deja
        # Mismo problema que describe el comentario de arriba, ahora para el modelo
        # por-persona: si alguna vez existe un users.json REAL en la raíz del repo
        # (una vez Diego dé de alta cuentas de verdad), este subproceso no debe
        # heredarlo — apunta a un archivo que a propósito no existe, así
        # auth_enabled() da False sin importar qué haya en el repo real.
        env["AUTH_USERS_PATH"] = os.path.join(tempfile.mkdtemp(), "users.json")
        env["WHATSAPP_APP_SECRET"] = cls.WHATSAPP_APP_SECRET
        # Mismo problema que AUTH_PASSWORD arriba: en el Ubuntu real, el .env
        # del repo trae LOCAL_MODEL configurado — sin fijarlo vacío acá, este
        # test se comporta distinto según en qué máquina corra (mock en el Mac,
        # "live" en producción) en vez de un mock determinista y predecible.
        env["LOCAL_MODEL"] = ""
        env["ANTHROPIC_API_KEY"] = ""
        cls.proc = _start_and_wait(
            [sys.executable, "-m", "uvicorn", "api:app", "--port", str(cls.port),
             "--log-level", "warning"],
            str(repo_root), env, cls.base,
        )

    @classmethod
    def tearDownClass(cls):
        proc = getattr(cls, "proc", None)
        if proc is None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    def _get(self, path: str):
        with urllib.request.urlopen(f"{self.base}{path}", timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_health(self):
        status, body = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

    def test_vendors_shape_over_real_http(self):
        """Mismo contrato que GET /api/vendors — pero probado sobre HTTP real,
        no solo llamando a vendor_summary/clients_count_for en Python."""
        status, body = self._get("/api/vendors")
        self.assertEqual(status, 200)
        self.assertIn("vendors", body)
        self.assertGreaterEqual(len(body["vendors"]), 2)
        for v in body["vendors"]:
            self.assertEqual(
                set(v),
                {"id", "name", "photo", "tone", "phone", "whatsapp_phone_id", "clients_count"},
            )

    def test_clients_endpoint_over_real_http(self):
        """Nunca debe dar 500 — ni con CRM local ni con Supabase caído/mal
        configurado. Supabase carga perezoso (por diseño), así que un fallo real
        solo aparece en el primer query, no al construir el cliente — de ahí que
        este chequeo tenga que ser sobre HTTP real, no sobre la función en Python.
        Regresión directa de un bug encontrado el 2026-07-04: SupabaseError sin
        capturar tiraba un 500 crudo en vez de un 503 claro."""
        try:
            status, body = self._get("/api/clients")
            self.assertEqual(status, 200)
            self.assertIn("clients", body)
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 503, "un fallo de Supabase debe degradar a 503, nunca a 500")
            detail = json.loads(e.read().decode("utf-8"))
            self.assertIn("no disponible", detail["detail"])

    def test_leads_search_short_query_is_400(self):
        """La validación de largo mínimo vive en api.py (HTTPException), no en
        CRM.search() — por eso este chequeo tiene que ser sobre HTTP real, no
        sobre la función en Python (igual razón que test_clients_endpoint arriba)."""
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._get("/api/leads/search?q=a")
        self.assertEqual(cm.exception.code, 400)

    def test_leads_search_shape_over_real_http(self):
        """Nunca debe dar 500 — con CRM local o con Supabase (cuando está
        configurado, esto pega de verdad, solo lectura, cero riesgo de
        ensuciar datos). No se afirma contenido real: los datos de producción
        cambian; solo se confirma el contrato de la respuesta. Mismo patrón que
        test_clients_endpoint_over_real_http: un Supabase caído/pausado degrada
        a 503 claro, nunca a un 500 crudo."""
        try:
            status, body = self._get("/api/leads/search?q=zzz-no-deberia-matchear-nada-real")
            self.assertEqual(status, 200)
            self.assertEqual(set(body), {"results", "q", "limit"})
            self.assertEqual(body["results"], [])
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 503, "un fallo de Supabase debe degradar a 503, nunca a 500")
            detail = json.loads(e.read().decode("utf-8"))
            self.assertIn("no disponible", detail["detail"])

    def test_auth_status_endpoint(self):
        status, body = self._get("/api/auth/status")
        self.assertEqual(status, 200)
        self.assertIn("enabled", body)
        self.assertIn("authenticated", body)

    def test_config_exposes_explicit_engine_mode(self):
        """Antes había que inferir si el motor corría real o mock combinando
        los campos `anthropic`/`local_model` a mano — ahora /api/config lo dice
        directo, calculado con la misma función que decide el backend en cada
        request real (_agents_best), no solo mirando qué keys están seteadas."""
        status, body = self._get("/api/config")
        self.assertEqual(status, 200)
        self.assertIn("engine_mode", body)
        self.assertIn("engine", body)
        # Sin LOCAL_MODEL/ANTHROPIC_API_KEY (ver setUpClass) → mock, sin motor.
        self.assertEqual(body["engine_mode"], "mock")
        self.assertIsNone(body["engine"])

    def test_unknown_route_is_404_not_500(self):
        """Si esto alguna vez devuelve 500 en vez de 404, algo se rompió en el
        manejo de errores de FastAPI/la app — señal de alarma real."""
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/esto-no-existe")
        self.assertEqual(ctx.exception.code, 404)

    def _post_webhook(self, body: bytes, signature: str | None):
        headers = {"Content-Type": "application/json"}
        if signature is not None:
            headers["X-Hub-Signature-256"] = signature
        req = urllib.request.Request(
            f"{self.base}/api/webhooks/whatsapp", data=body, method="POST", headers=headers,
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_webhook_rejects_unsigned_request(self):
        """Sobre HTTP real: sin firma, o con una firma que no cuadra, el webhook
        rechaza con 403 — nunca procesa el payload. Prueba la conexión real
        api.py -> verify_meta_signature, no solo la función aislada."""
        body = b'{"entry": [{"changes": [{"value": {"messages": []}}]}]}'
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post_webhook(body, signature=None)
        self.assertEqual(ctx.exception.code, 403)

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post_webhook(body, signature="sha256=firma-que-no-cuadra")
        self.assertEqual(ctx.exception.code, 403)

    def test_webhook_accepts_correctly_signed_request(self):
        import hashlib
        import hmac
        body = b'{"entry": [{"changes": [{"value": {"messages": []}}]}]}'
        sig = "sha256=" + hmac.new(
            self.WHATSAPP_APP_SECRET.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        status, resp = self._post_webhook(body, signature=sig)
        self.assertEqual(status, 200)
        self.assertEqual(resp["received"], 0)   # payload vacío, pero se procesó


@unittest.skipUnless(_UVICORN_AVAILABLE, "uvicorn no instalado — este test es opcional, no núcleo")
class ApiAuthHttpTest(unittest.TestCase):
    """Prueba el login por-persona de punta a punta, sobre HTTP real —
    zero/auth.py ya tiene tests unitarios de valid_token()/token_username(),
    pero eso no prueba que el middleware de api.py (auth_guard) realmente lo
    aplique en cada request. Corre en un subproceso PROPIO (con una cuenta
    real dada de alta en un users.json temporal) separado de ApiHttpTest de
    arriba, que corre a propósito sin cuentas para poder probar los demás
    endpoints libremente."""

    USERNAME = "diego"
    PASSWORD = "s3cret-para-el-test"

    @classmethod
    def setUpClass(cls):
        from zero import auth
        cls.port = _free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        repo_root = Path(__file__).resolve().parent.parent
        cls._tmpdir = tempfile.mkdtemp()
        cls.users_path = os.path.join(cls._tmpdir, "users.json")
        # auth.add_user() lee/escribe AUTH_USERS_PATH en vivo — se lo apunta
        # acá (este proceso) solo para crear el archivo; después se le pasa
        # el MISMO path al subproceso de abajo, para que lea la misma cuenta.
        prev = os.environ.get("AUTH_USERS_PATH")
        os.environ["AUTH_USERS_PATH"] = cls.users_path
        try:
            auth.add_user(cls.USERNAME, cls.PASSWORD)
        finally:
            if prev is None:
                os.environ.pop("AUTH_USERS_PATH", None)
            else:
                os.environ["AUTH_USERS_PATH"] = prev
        env = dict(os.environ)
        env["AUTH_USERS_PATH"] = cls.users_path
        # Vacío, no ausente: si falta del todo, zero/_env.py::load_env() (usa
        # os.environ.setdefault) lo vuelve a levantar del .env real del repo
        # — que en esta máquina apunta a un proyecto Supabase roto (mismo
        # gotcha ya documentado arriba para AUTH_PASSWORD/LOCAL_MODEL).
        env["SUPABASE_URL"] = ""
        env["SUPABASE_KEY"] = ""
        cls.proc = _start_and_wait(
            [sys.executable, "-m", "uvicorn", "api:app", "--port", str(cls.port),
             "--log-level", "warning"],
            str(repo_root), env, cls.base,
        )

    @classmethod
    def tearDownClass(cls):
        proc = getattr(cls, "proc", None)
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        shutil.rmtree(getattr(cls, "_tmpdir", "") or "", ignore_errors=True)

    def _get(self, path: str, token: str | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        req = urllib.request.Request(f"{self.base}{path}", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def _login(self, username: str, password: str) -> str:
        req = urllib.request.Request(
            f"{self.base}/api/login", method="POST",
            data=json.dumps({"username": username, "password": password}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8"))["token"]

    def test_protected_endpoint_without_token_is_401(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/vendors")
        self.assertEqual(ctx.exception.code, 401)

    def test_protected_endpoint_with_garbage_token_is_401(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/vendors", token="esto-no-es-un-token-valido")
        self.assertEqual(ctx.exception.code, 401)

    def test_login_with_wrong_password_is_401(self):
        req = urllib.request.Request(
            f"{self.base}/api/login", method="POST",
            data=json.dumps({"username": self.USERNAME, "password": "password-incorrecta"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 401)

    def test_login_with_unknown_username_is_401(self):
        req = urllib.request.Request(
            f"{self.base}/api/login", method="POST",
            data=json.dumps({"username": "nadie-dado-de-alta", "password": self.PASSWORD}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 401)

    def test_login_then_protected_endpoint_with_valid_token_works(self):
        token = self._login(self.USERNAME, self.PASSWORD)
        status, body = self._get("/api/vendors", token=token)
        self.assertEqual(status, 200)
        self.assertIn("vendors", body)

    def test_auth_status_reports_username_when_authenticated(self):
        token = self._login(self.USERNAME, self.PASSWORD)
        status, body = self._get("/api/auth/status", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(body["username"], self.USERNAME)

    def test_expired_token_is_rejected_over_real_http(self):
        """El corazón de 'expiración de sesión probada': un token vencido —
        firmado con el MISMO hash de password real que el subproceso ya tiene
        guardado en users.json, así que la firma es válida — debe ser
        rechazado igual, porque ya pasó su tiempo de vida. Se firma con
        zero.auth directamente (no hay forma de esperar 7 días en un test)
        apuntando al mismo AUTH_USERS_PATH que usa el subproceso, para
        producir un token con firma legítima pero `exp` en el pasado."""
        prev = os.environ.get("AUTH_USERS_PATH")
        os.environ["AUTH_USERS_PATH"] = self.users_path
        try:
            from zero import auth
            expired = auth.make_token(self.USERNAME, ttl=-10)
        finally:
            if prev is None:
                os.environ.pop("AUTH_USERS_PATH", None)
            else:
                os.environ["AUTH_USERS_PATH"] = prev
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/vendors", token=expired)
        self.assertEqual(ctx.exception.code, 401)

    def test_open_endpoints_never_require_a_token(self):
        for path in ("/api/health", "/api/auth/status", "/api/public/plans"):
            status, _ = self._get(path)
            self.assertEqual(status, 200, path)

    def test_public_plans_accessible_without_token_and_shape(self):
        """La landing pública consume esto sin login — tiene que responder
        incluso con una cuenta real configurada (este test class corre con
        una de verdad, a diferencia de ApiHttpTest de arriba). Nunca debe
        filtrar MRR ni datos de clientes reales — solo
        segment/price_clp/leads_per_mo, por tier."""
        status, body = self._get("/api/public/plans")
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"plans"})
        plans = body["plans"]
        self.assertEqual(set(plans), {"STARTER", "GROWTH", "SCALE", "ENTERPRISE"})
        for tier, info in plans.items():
            self.assertEqual(set(info), {"segment", "price_clp", "leads_per_mo"}, tier)
        # ENTERPRISE es a medida: se expone tal cual (None), la landing decide
        # cómo mostrarlo (ej. "Hablar con nosotros").
        self.assertIsNone(plans["ENTERPRISE"]["price_clp"])
        self.assertIsNone(plans["ENTERPRISE"]["leads_per_mo"])
        # Nunca debe verse nada de "mrr" ni pinta de dato de cliente real.
        self.assertNotIn("mrr_clp", body)


@unittest.skipUnless(_UVICORN_AVAILABLE, "uvicorn no instalado — este test es opcional, no núcleo")
class ApiSupabaseAuthHttpTest(unittest.TestCase):
    """Login vía Supabase Auth (Google) + roles, sobre HTTP real — el
    auth_guard de api.py tiene que aplicar el rol en cada request, no basta
    con que zero/auth.py lo calcule bien aislado (ver SupabaseJWTAuthTest en
    test_core.py para esos). Subproceso PROPIO con SUPABASE_JWT_SECRET
    configurado y SIN cuentas locales (AUTH_USERS_PATH apunta a un archivo
    que a propósito no existe) — así el único camino de auth activo es el
    JWT; el fallback local (que da "admin" gratis) no debe contaminar las
    pruebas de restricción por rol."""

    JWT_SECRET = "otro-jwt-secret-de-prueba-para-http"

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        repo_root = Path(__file__).resolve().parent.parent
        env = dict(os.environ)
        env["SUPABASE_JWT_SECRET"] = cls.JWT_SECRET
        env["AUTH_USERS_PATH"] = os.path.join(tempfile.mkdtemp(), "users.json")
        # Vacío, no ausente: si falta del todo, zero/_env.py::load_env() (usa
        # os.environ.setdefault) lo vuelve a levantar del .env real del repo
        # — que en esta máquina apunta a un proyecto Supabase roto (mismo
        # gotcha ya documentado arriba para AUTH_PASSWORD/LOCAL_MODEL).
        env["SUPABASE_URL"] = ""
        env["SUPABASE_KEY"] = ""
        cls.proc = _start_and_wait(
            [sys.executable, "-m", "uvicorn", "api:app", "--port", str(cls.port),
             "--log-level", "warning"],
            str(repo_root), env, cls.base,
        )

    @classmethod
    def tearDownClass(cls):
        proc = getattr(cls, "proc", None)
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)

    def _get(self, path: str, token: str | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        req = urllib.request.Request(f"{self.base}{path}", headers=headers)
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def _jwt(self, **kw) -> str:
        return _make_supabase_jwt(self.JWT_SECRET, **kw)

    def test_admin_jwt_passes_any_route(self):
        # /api/vendors no está en la lista de rutas permitidas para "cro" —
        # solo un admin debería poder verla.
        status, body = self._get("/api/vendors", token=self._jwt(role="admin"))
        self.assertEqual(status, 200)
        self.assertIn("vendors", body)

    def test_cro_jwt_passes_allowed_route(self):
        status, body = self._get("/api/clients", token=self._jwt(role="cro", email="lucas@zeroai.cl"))
        self.assertEqual(status, 200)
        self.assertIn("clients", body)

    def test_cro_jwt_gets_403_outside_allowed_routes(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/vendors", token=self._jwt(role="cro"))
        self.assertEqual(ctx.exception.code, 403)

    def test_cro_jwt_gets_403_on_config(self):
        # el caso "dudoso" reportado a Diego: /api/config queda SOLO admin,
        # aunque Vender.jsx lea una parte de ahí — ver REPORT.
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/config", token=self._jwt(role="cro"))
        self.assertEqual(ctx.exception.code, 403)

    def test_expired_jwt_is_401(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/vendors", token=self._jwt(role="admin", exp_delta=-10))
        self.assertEqual(ctx.exception.code, 401)

    def test_tampered_jwt_is_401(self):
        tok = self._jwt(role="admin")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/vendors", token=tok[:-4] + "xxxx")
        self.assertEqual(ctx.exception.code, 401)

    def test_jwt_without_role_is_403(self):
        # fail closed: autenticado (firma OK) pero sin app_metadata.role → 403,
        # nunca "ve todo por defecto".
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/clients", token=self._jwt(role=None))
        self.assertEqual(ctx.exception.code, 403)

    def test_auth_status_reports_role(self):
        status, body = self._get("/api/auth/status",
                                 token=self._jwt(role="cro", email="lucas@zeroai.cl"))
        self.assertEqual(status, 200)
        self.assertEqual(body["role"], "cro")
        self.assertEqual(body["username"], "lucas@zeroai.cl")


if __name__ == "__main__":
    unittest.main()
