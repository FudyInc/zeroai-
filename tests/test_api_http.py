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
from datetime import datetime, timezone
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
                       role: str | None = "admin", exp_delta: int = 3600,
                       full_name: str | None = None) -> str:
    """Arma un JWT con la misma forma/firma que produce Supabase Auth (HS256,
    base64url, app_metadata.role, user_metadata.full_name) — sin pyjwt, para
    probar zero/auth.py y el auth_guard de api.py sin depender de una cuenta
    real de Supabase."""
    header = {"alg": "HS256", "typ": "JWT"}
    app_metadata = {"role": role} if role is not None else {}
    user_metadata = {"full_name": full_name} if full_name is not None else {}
    payload = {"email": email, "exp": int(time.time()) + exp_delta,
              "app_metadata": app_metadata, "user_metadata": user_metadata}
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
        # Mismo gotcha otra vez, ahora para el tercer mecanismo de auth_enabled():
        # en el Ubuntu de producción SUPABASE_JWT_SECRET SÍ está configurado de
        # verdad — sin vaciarlo acá, este subproceso "sin auth" deja de estarlo.
        env["SUPABASE_JWT_SECRET"] = ""
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

    def test_leads_clear_requires_confirm_to_match_client(self):
        """DELETE /api/leads exige repetir el nombre del cliente en `confirm` —
        segunda barrera contra un click/curl accidental, además del gate
        admin-only. Deliberadamente NO se prueba el borrado real acá: esta clase
        puede correr contra Supabase real si la máquina tiene SUPABASE_URL/KEY en
        su .env (ver otros tests de esta clase que degradan a 503) — la lógica
        de borrado en sí ya está cubierta sin red en CRMTest.test_clear_*."""
        req = urllib.request.Request(
            f"{self.base}/api/leads?client=acme&confirm=otro-nombre", method="DELETE")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 400)

    def test_send_outreach_on_unknown_lead_is_400_not_500(self):
        """POST /api/leads/{key}/send sobre una key que no existe (para nada
        cerca de un lead real) debe degradar a un 400 claro, nunca un 500 —
        misma cautela de la clase: solo lectura, cero riesgo de escribir en
        Supabase real si esta máquina tiene credenciales configuradas. Mismo
        patrón que test_clients_endpoint_over_real_http: si esta máquina tiene
        SUPABASE_URL/KEY reales pero Supabase no responde bien, el handler
        global de SupabaseError degrada a 503 en vez de un 500 crudo — eso
        también es un resultado válido acá, no un fallo de este test."""
        data = json.dumps({}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base}/api/leads/zzz-no-deberia-existir-nunca/send?client=acme",
            data=data, method="POST", headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertIn(ctx.exception.code, (400, 503))

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
        # — mismo gotcha ya documentado arriba para AUTH_PASSWORD/LOCAL_MODEL.
        # En el Mac de desarrollo SUPABASE_URL apunta a un proyecto roto; en
        # el Ubuntu de producción LOCAL_MODEL apunta a un Ollama real —
        # cualquiera de los dos deja este test class a merced de una red o un
        # modelo real (encontrado corriendo esta suite en producción por
        # primera vez: /api/forecast entero se puso a esperar a Ollama de
        # verdad y voló el timeout de 5s del test).
        env["SUPABASE_URL"] = ""
        env["SUPABASE_KEY"] = ""
        env["LOCAL_MODEL"] = ""
        env["ANTHROPIC_API_KEY"] = ""
        # Mismo gotcha para Twilio: si el .env real trae un token, el webhook
        # validaría firmas de verdad y el test de exención de auth dejaría de
        # ser determinista.
        env["TWILIO_AUTH_TOKEN"] = ""
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

    def test_twilio_webhook_is_exempt_from_login_auth(self):
        """El prefijo /api/webhooks/ del middleware cubre también el webhook
        nuevo de Twilio: sin Bearer token responde el gate de FIRMA (403 de
        verify_twilio_signature), nunca el de login (401) — Twilio no tiene
        cómo mandar nuestro token; se autentica con su firma."""
        req = urllib.request.Request(
            f"{self.base}/api/webhooks/twilio-whatsapp",
            data=b"From=whatsapp%3A%2B56911112222&Body=hola", method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(ctx.exception.code, 403)

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
        # — mismo gotcha ya documentado arriba para AUTH_PASSWORD/LOCAL_MODEL.
        # En el Mac de desarrollo SUPABASE_URL apunta a un proyecto roto; en
        # el Ubuntu de producción LOCAL_MODEL apunta a un Ollama real —
        # cualquiera de los dos deja este test class a merced de una red o un
        # modelo real (encontrado corriendo esta suite en producción por
        # primera vez: /api/forecast entero se puso a esperar a Ollama de
        # verdad y voló el timeout de 5s del test).
        env["SUPABASE_URL"] = ""
        env["SUPABASE_KEY"] = ""
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

    def test_team_panel_is_admin_only(self):
        """Panel de Equipo — sin entrada en _ROLE_ALLOWED, admin-only por
        default fail-closed (mismo patrón que /api/vendors)."""
        status, body = self._get("/api/team", token=self._jwt(role="admin"))
        self.assertEqual(status, 200)
        self.assertIn("users", body)
        self.assertIn("configured", body)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/team", token=self._jwt(role="cro"))
        self.assertEqual(ctx.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/team", token=self._jwt(role="cto"))
        self.assertEqual(ctx.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/team", token=self._jwt(role="cco"))
        self.assertEqual(ctx.exception.code, 403)

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

    def test_cto_jwt_passes_allowed_route(self):
        status, body = self._get("/api/forecast?client=acme",
                                 token=self._jwt(role="cto", email="alejandro@zeroai.cl"))
        self.assertEqual(status, 200)

    def test_cto_jwt_gets_403_outside_allowed_routes(self):
        # Campañas/Vender/Clientes son de "cro" — cto (Alejandro) queda
        # dedicado a Leads/Pipeline/Forecast, sin esto.
        for path in ("/api/accounts", "/api/campaigns?client=acme", "/api/emails"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._get(path, token=self._jwt(role="cto"))
            self.assertEqual(ctx.exception.code, 403, path)

    def test_cto_jwt_gets_403_on_finance(self):
        # /api/finance es EXCLUSIVO de cro — ni siquiera cto lo tiene.
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/finance", token=self._jwt(role="cto"))
        self.assertEqual(ctx.exception.code, 403)

    def test_cro_and_cto_share_dashboard_pipeline_and_forecast(self):
        # Vista operativa común de ambos roles — el home (KPIs), el board de
        # Pipeline y Forecast. cro además tiene su propio set exclusivo
        # (Clientes/Campañas/Vender/Finanzas) probado en los tests de arriba.
        for role in ("cro", "cto"):
            status, _ = self._get("/api/kpis?client=acme", token=self._jwt(role=role))
            self.assertEqual(status, 200, role)
            status, _ = self._get("/api/board?client=acme", token=self._jwt(role=role))
            self.assertEqual(status, 200, role)
            status, _ = self._get("/api/forecast?client=acme", token=self._jwt(role=role))
            self.assertEqual(status, 200, role)

    def test_cco_jwt_passes_allowed_route(self):
        status, body = self._get("/api/vendors", token=self._jwt(role="cco", email="maureen@zeroai.cl"))
        self.assertEqual(status, 200)
        self.assertIn("vendors", body)

    def test_cco_jwt_gets_403_outside_allowed_routes(self):
        # Forecast/Clientes/Finanzas/Configuración son terreno de plata/técnico,
        # no de contenido — cco (Maureen) no los tiene.
        for path in ("/api/forecast?client=acme", "/api/accounts", "/api/finance", "/api/config"):
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                self._get(path, token=self._jwt(role="cco"))
            self.assertEqual(ctx.exception.code, 403, path)

    def test_cco_jwt_can_review_and_send_outreach(self):
        # El caso de uso central del rol: ver el board/leads y poder mandar un
        # borrador aprobado (POST /api/leads/{key}/send cae bajo el mismo
        # prefijo que POST /api/leads).
        status, _ = self._get("/api/board?client=acme", token=self._jwt(role="cco"))
        self.assertEqual(status, 200)
        status, _ = self._get("/api/leads?client=acme", token=self._jwt(role="cco"))
        self.assertEqual(status, 200)

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

    def test_auth_status_reports_full_name(self):
        status, body = self._get("/api/auth/status", token=self._jwt(
            role="admin", email="diego@zeroai.cl", full_name="Diego Mardones"))
        self.assertEqual(status, 200)
        self.assertEqual(body["full_name"], "Diego Mardones")

    def test_auth_status_full_name_none_without_user_metadata(self):
        status, body = self._get("/api/auth/status", token=self._jwt(role="admin"))
        self.assertEqual(status, 200)
        self.assertIsNone(body["full_name"])


@unittest.skipUnless(_UVICORN_AVAILABLE, "uvicorn no instalado — este test es opcional, no núcleo")
class ProgrammedFunctionsHttpTest(unittest.TestCase):
    """Fase 2 (registro de funciones programadas) — CRUD + /run sobre HTTP
    real, admin-only. Subproceso PROPIO con STATE_PATH/CRM_PATH apuntando a un
    tempdir (nunca toca el state.json/crm.json real del repo — ver el override
    por env var que se agregó en api.py junto con esto) y auth JWT habilitada,
    mismo patrón que ApiSupabaseAuthHttpTest.

    No mockea Docker: en una máquina sin Docker (como la de desarrollo),
    run_sandboxed ya devuelve un error determinista ("Docker no disponible")
    en vez de lanzar — sirve igual para confirmar que /run arma el ctx, llama
    a run_sandboxed y persiste last_run de verdad. La ejecución real dentro de
    Docker ya está cubierta en tests/test_sandbox.py — no se duplica acá,
    según pide el prompt de fase 2."""

    JWT_SECRET = "jwt-secret-para-funciones"

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        repo_root = Path(__file__).resolve().parent.parent
        cls._tmpdir = tempfile.mkdtemp()
        env = dict(os.environ)
        env["SUPABASE_JWT_SECRET"] = cls.JWT_SECRET
        env["AUTH_USERS_PATH"] = os.path.join(tempfile.mkdtemp(), "users.json")
        env["STATE_PATH"] = os.path.join(cls._tmpdir, "state.json")
        env["CRM_PATH"] = os.path.join(cls._tmpdir, "crm.json")
        # Mismos gotchas ya documentados arriba (ApiSupabaseAuthHttpTest): sin
        # esto, el subproceso puede heredar Supabase/Ollama/Anthropic reales
        # del .env del repo y dejar de ser un entorno de test aislado.
        env["SUPABASE_URL"] = ""
        env["SUPABASE_KEY"] = ""
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

    def _send(self, path: str, body: dict, token: str | None = None, method: str = "POST"):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(f"{self.base}{path}", data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=20) as r:   # /run puede correr Docker real en CI
            return r.status, json.loads(r.read().decode("utf-8"))

    def _delete(self, path: str, token: str | None = None):
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        req = urllib.request.Request(f"{self.base}{path}", headers=headers, method="DELETE")
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def _jwt(self, **kw) -> str:
        return _make_supabase_jwt(self.JWT_SECRET, **kw)

    def test_non_admin_gets_403_on_every_functions_endpoint(self):
        cro = self._jwt(role="cro")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/api/functions", token=cro)
        self.assertEqual(ctx.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._send("/api/functions", {"name": "x", "code": "result=1",
                                          "lookup_scope": {"client_id": "acme"}}, token=cro)
        self.assertEqual(ctx.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._delete("/api/functions/algo", token=cro)
        self.assertEqual(ctx.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._send("/api/functions/algo/run", {}, token=cro)
        self.assertEqual(ctx.exception.code, 403)

    def test_admin_create_run_and_delete_lifecycle(self):
        admin = self._jwt(role="admin", email="diego@zeroai.cl")
        status, body = self._send("/api/functions", {
            "name": "Contar leads nuevos",
            "code": "result = len(ctx['leads'])",
            "lookup_scope": {"client_id": "acme", "stage": "new"},
        }, token=admin)
        self.assertEqual(status, 200)
        fn = body["function"]
        self.assertEqual(fn["name"], "Contar leads nuevos")
        self.assertEqual(fn["lookup_scope"], {"client_id": "acme", "stage": "new"})
        self.assertTrue(fn["enabled"])
        self.assertEqual(fn["created_by"], "diego@zeroai.cl")
        self.assertIsNone(fn["last_run"])
        fid = fn["id"]

        status, body = self._get("/api/functions", token=admin)
        self.assertEqual(status, 200)
        self.assertIn(fid, {f["id"] for f in body["functions"]})

        status, body = self._send(f"/api/functions/{fid}/run", {}, token=admin)
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"function", "run"})
        # `actions` (el reporte de acciones pedidas) solo aparece si la corrida
        # terminó sin error — sin Docker en esta máquina, no está.
        self.assertLessEqual({"result", "stdout", "error"}, set(body["run"]))
        last_run = body["function"]["last_run"]
        self.assertIsNotNone(last_run)
        self.assertEqual(set(last_run), {"at", "ok", "result_summary", "error", "actions"})

        # quedó guardado de verdad — no solo en la respuesta de /run
        status, body = self._get("/api/functions", token=admin)
        saved = next(f for f in body["functions"] if f["id"] == fid)
        self.assertIsNotNone(saved["last_run"])

        status, _ = self._delete(f"/api/functions/{fid}", token=admin)
        self.assertEqual(status, 200)
        status, body = self._get("/api/functions", token=admin)
        self.assertNotIn(fid, {f["id"] for f in body["functions"]})

    def test_run_unknown_function_is_404(self):
        admin = self._jwt(role="admin")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._send("/api/functions/no-existe-nunca/run", {}, token=admin)
        self.assertEqual(ctx.exception.code, 404)

    def test_disabled_function_cannot_be_run(self):
        admin = self._jwt(role="admin")
        _, body = self._send("/api/functions", {
            "name": "Deshabilitada", "code": "result = 1",
            "lookup_scope": {"client_id": "acme"}, "enabled": False,
        }, token=admin)
        fid = body["function"]["id"]
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._send(f"/api/functions/{fid}/run", {}, token=admin)
        self.assertEqual(ctx.exception.code, 409)

    def test_create_without_name_is_400(self):
        admin = self._jwt(role="admin")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._send("/api/functions", {"name": "   ", "code": "",
                                          "lookup_scope": {"client_id": "acme"}}, token=admin)
        self.assertEqual(ctx.exception.code, 400)

    def test_create_with_schedule_sets_next_run(self):
        admin = self._jwt(role="admin")
        _, body = self._send("/api/functions", {
            "name": "Nudge diario", "code": "result = len(ctx['leads'])",
            "lookup_scope": {"client_id": "acme"},
            "schedule": {"interval_minutes": 5},
        }, token=admin)
        fn = body["function"]
        self.assertEqual(fn["schedule"], {"interval_minutes": 5})
        self.assertIsNotNone(fn["next_run"])
        next_run = datetime.fromisoformat(fn["next_run"])
        self.assertGreater(next_run, datetime.now(timezone.utc))

    def test_create_without_schedule_has_no_next_run(self):
        """Comportamiento de siempre, sin cambios — una función sin `schedule`
        nunca se auto-dispara (queda 100% manual, igual que antes de este
        prompt)."""
        admin = self._jwt(role="admin")
        _, body = self._send("/api/functions", {
            "name": "Solo manual", "code": "result = 1",
            "lookup_scope": {"client_id": "acme"},
        }, token=admin)
        fn = body["function"]
        self.assertIsNone(fn["schedule"])
        self.assertIsNone(fn["next_run"])

    def test_invalid_schedule_interval_is_400(self):
        admin = self._jwt(role="admin")
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._send("/api/functions", {
                "name": "Intervalo inválido", "code": "result = 1",
                "lookup_scope": {"client_id": "acme"},
                "schedule": {"interval_minutes": 0},
            }, token=admin)
        self.assertEqual(ctx.exception.code, 400)

    def test_manual_run_pushes_next_run_forward_when_scheduled(self):
        """Correr "/run" a mano una función CON schedule igual empuja su
        next_run hacia adelante — así una prueba manual justo antes de que
        tocara el tick automático no dispara dos veces seguidas."""
        admin = self._jwt(role="admin")
        _, body = self._send("/api/functions", {
            "name": "Con horario", "code": "result = 1",
            "lookup_scope": {"client_id": "acme"},
            "schedule": {"interval_minutes": 5},
        }, token=admin)
        fid = body["function"]["id"]
        before = datetime.fromisoformat(body["function"]["next_run"])

        status, run_body = self._send(f"/api/functions/{fid}/run", {}, token=admin)
        self.assertEqual(status, 200)
        after = datetime.fromisoformat(run_body["function"]["next_run"])
        self.assertGreaterEqual(after, before)   # se recalculó desde ahora, no quedó atrás

    def test_registered_client_without_leads_appears_in_clients_and_accounts(self):
        """Antes: /api/clients y /api/accounts solo miraban el CRM — un cliente
        recién registrado (plan asignado, cero leads) no aparecía en ningún
        lado hasta correr un pipeline. Fricción reportada por Diego
        (2026-07-23) — ahora debe aparecer de inmediato en ambos."""
        admin = self._jwt(role="admin")
        client_id = "clientenuevosinleads"
        status, _ = self._send(f"/api/accounts/{client_id}/plan", {"tier": "GROWTH"}, token=admin)
        self.assertEqual(status, 200)

        _, clients_body = self._get("/api/clients", token=admin)
        self.assertIn(client_id, clients_body["clients"])

        _, accounts_body = self._get("/api/accounts", token=admin)
        ids = [a["client"] for a in accounts_body["accounts"]]
        self.assertIn(client_id, ids)
        acc = next(a for a in accounts_body["accounts"] if a["client"] == client_id)
        self.assertEqual(acc["tier"], "GROWTH")


@unittest.skipUnless(_UVICORN_AVAILABLE, "uvicorn no instalado — este test es opcional, no núcleo")
class TwilioWebhookHttpTest(unittest.TestCase):
    """El webhook de Twilio de punta a punta, sobre HTTP real: firma inválida →
    403 y CERO efectos; firma válida → parseo + handle_inbound (la cantidad
    procesada viaja en el header X-Zero-Received, porque el body es TwiML para
    Twilio, no JSON para nosotros).

    Corre con cwd en un tmpdir (y PYTHONPATH al repo para que uvicorn encuentre
    api:app): CRM_PATH/STATE_PATH son rutas relativas, así que un handle_inbound
    real escribiría crm.json/state.json DEL REPO si corriera desde la raíz — el
    test de Meta lo esquiva con un payload sin mensajes, este manda uno de verdad."""

    TWILIO_AUTH_TOKEN = "twilio-token-de-prueba"

    @classmethod
    def setUpClass(cls):
        cls.port = _free_port()
        cls.base = f"http://127.0.0.1:{cls.port}"
        repo_root = Path(__file__).resolve().parent.parent
        cls._tmpdir = tempfile.mkdtemp()
        env = dict(os.environ)
        env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")
        env["TWILIO_AUTH_TOKEN"] = cls.TWILIO_AUTH_TOKEN
        env["WHATSAPP_PROVIDER"] = "twilio"
        # Aislamiento y determinismo (mismas razones documentadas en ApiHttpTest):
        # vacío = presente para el setdefault de load_env, así el .env real del
        # repo no re-activa nada — ni auth, ni motor live, ni Supabase (un
        # handle_inbound real contra Supabase escribiría en la NUBE), ni envíos.
        env["AUTH_USERS_PATH"] = os.path.join(cls._tmpdir, "users.json")
        env["SUPABASE_URL"] = ""
        env["SUPABASE_KEY"] = ""
        env["LOCAL_MODEL"] = ""
        env["ANTHROPIC_API_KEY"] = ""
        env["OUTBOX_LIVE"] = ""
        env["TWILIO_WEBHOOK_URL"] = ""   # que firme sobre str(req.url), como el cliente
        cls.proc = _start_and_wait(
            [sys.executable, "-m", "uvicorn", "api:app", "--port", str(cls.port),
             "--log-level", "warning"],
            cls._tmpdir, env, cls.base,
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

    def _webhook_url(self) -> str:
        return f"{self.base}/api/webhooks/twilio-whatsapp"

    def _sign(self, url: str, params: dict) -> str:
        """La firma exacta que Twilio manda en X-Twilio-Signature:
        base64(HMAC-SHA1(auth_token, url + params ordenados clave+valor))."""
        import base64
        import hashlib
        import hmac
        signed = url + "".join(k + v for k, v in sorted(params.items()))
        return base64.b64encode(
            hmac.new(self.TWILIO_AUTH_TOKEN.encode(), signed.encode(), hashlib.sha1).digest()
        ).decode()

    def _post(self, params: dict, signature: str | None):
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if signature is not None:
            headers["X-Twilio-Signature"] = signature
        req = urllib.request.Request(
            self._webhook_url(), data=urllib.parse.urlencode(params).encode("utf-8"),
            method="POST", headers=headers,
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            # r.headers (email.message.Message) es case-insensitive — uvicorn
            # emite los nombres en minúsculas (x-zero-received), un dict no matchearía
            return r.status, r.read().decode("utf-8"), r.headers

    PARAMS = {"From": "whatsapp:+56900000000", "To": "whatsapp:+14155238886",
              "Body": "hola, me interesa", "MessageSid": "SM-http-test"}

    def test_unsigned_request_is_403(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post(self.PARAMS, signature=None)
        self.assertEqual(ctx.exception.code, 403)

    def test_bad_signature_is_403(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._post(self.PARAMS, signature="firma-que-no-cuadra")
        self.assertEqual(ctx.exception.code, 403)

    def test_valid_signature_reaches_handle_inbound(self):
        """Con la firma correcta, la respuesta llega al toque: X-Zero-Received:
        1 confirma que pasó firma → parseo, ANTES de que el procesamiento real
        (handle_inbound, en background — ver _process_inbound_messages en
        api.py) siquiera empiece. Que el trabajo se complete de verdad lo
        prueba test_processing_happens_in_background_after_response."""
        sig = self._sign(self._webhook_url(), self.PARAMS)
        status, body, headers = self._post(self.PARAMS, signature=sig)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Zero-Received"), "1")
        self.assertEqual(body, "<Response></Response>")   # TwiML vacío para Twilio

    def test_processing_happens_in_background_after_response(self):
        """La respuesta HTTP no espera a que termine handle_inbound — se
        agenda con BackgroundTasks y corre después de responder (ver
        _process_inbound_messages en api.py). Esto es justo lo que evita el
        error 11200 de Twilio ('HTTP retrieval failure') cuando el motor real
        tarda 15-20s+ en generar la respuesta: Twilio ya no espera esa espera.

        Prueba que el trabajo se COMPLETA igual (no que se pierda al no
        esperarlo): el remitente es nuevo (sin lead previo) y esta clase corre
        con el catch-all por defecto activo (config.DEFAULT_INBOUND_CLIENT_ID
        — ver zero/config.py), así que debe aparecer auto-registrado en
        crm.json (mismo cwd que STATE_PATH/CRM_PATH relativos del subproceso,
        ver setUpClass) poco después de que la respuesta ya volvió."""
        params = {"From": "whatsapp:+56900000123", "To": "whatsapp:+14155238886",
                  "Body": "hola, prueba background", "MessageSid": "SM-bg-test"}
        sig = self._sign(self._webhook_url(), params)
        status, _, headers = self._post(params, signature=sig)
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("X-Zero-Received"), "1")

        crm_path = os.path.join(self._tmpdir, "crm.json")
        deadline = time.time() + 5
        found = False
        while time.time() < deadline:
            if os.path.exists(crm_path) and "56900000123" in Path(crm_path).read_text("utf-8"):
                found = True
                break
            time.sleep(0.2)
        self.assertTrue(found, "el mensaje se recibió pero el registro en background nunca se completó")


if __name__ == "__main__":
    unittest.main()
