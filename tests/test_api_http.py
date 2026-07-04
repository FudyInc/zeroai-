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

import json
import os
import socket
import subprocess
import sys
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
        env.pop("AUTH_PASSWORD", None)  # sin password -> /api/* queda abierto para probar
        env["WHATSAPP_APP_SECRET"] = cls.WHATSAPP_APP_SECRET
        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "api:app", "--port", str(cls.port),
             "--log-level", "warning"],
            cwd=str(repo_root), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            cls._wait_until_up()
        except Exception:
            cls.proc.kill()
            raise

    @classmethod
    def _wait_until_up(cls, timeout: float = 15.0) -> None:
        deadline = time.time() + timeout
        last_err = None
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                raise RuntimeError(f"uvicorn murió antes de arrancar (exit {cls.proc.returncode})")
            try:
                with urllib.request.urlopen(f"{cls.base}/api/health", timeout=1) as r:
                    if r.status == 200:
                        return
            except Exception as e:   # noqa: BLE001 — reintenta hasta el timeout
                last_err = e
            time.sleep(0.3)
        raise RuntimeError(f"el servidor no respondió a tiempo en {cls.base}: {last_err}")

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

    def test_auth_status_endpoint(self):
        status, body = self._get("/api/auth/status")
        self.assertEqual(status, 200)
        self.assertIn("enabled", body)
        self.assertIn("authenticated", body)

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


if __name__ == "__main__":
    unittest.main()
