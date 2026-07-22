"""Tests de zero/sandbox.py — el runner de ejecución aislada (fase 1 de 3 del
futuro sistema de "funciones programadas").

Dos grupos, separados a propósito:
  1. Validación de ctx y construcción del comando `docker run` — no necesitan
     Docker instalado, corren siempre, son el núcleo obligatorio.
  2. Ejecución real dentro de un contenedor — necesitan Docker de verdad
     (mismo patrón que _UVICORN_AVAILABLE en test_api_http.py: se saltan
     limpio, nunca fallan, si el binario no está).

Run alone:  python3 -m unittest tests.test_sandbox -v
"""
from __future__ import annotations

import shutil
import time
import unittest
from unittest.mock import MagicMock, patch

from zero.sandbox import _assert_ctx_is_safe, run_sandboxed

_DOCKER_AVAILABLE = shutil.which("docker") is not None


class CtxSafetyTest(unittest.TestCase):
    def test_safe_ctx_passes(self):
        _assert_ctx_is_safe({"lead": {"nombre": "Acme", "score": 82}})  # no debe lanzar

    def test_top_level_token_is_rejected(self):
        with self.assertRaises(ValueError):
            _assert_ctx_is_safe({"api_token": "abc123"})

    def test_key_substring_is_rejected(self):
        with self.assertRaises(ValueError):
            _assert_ctx_is_safe({"api_key": "abc123"})

    def test_nested_secret_is_rejected(self):
        with self.assertRaises(ValueError):
            _assert_ctx_is_safe({"lead": {"config": {"webhook_secret": "shh"}}})

    def test_secret_inside_list_is_rejected(self):
        with self.assertRaises(ValueError):
            _assert_ctx_is_safe({"items": [{"ok": 1}, {"password": "x"}]})

    def test_case_insensitive(self):
        with self.assertRaises(ValueError):
            _assert_ctx_is_safe({"AUTH_TOKEN": "x"})


class RunSandboxedWithoutDockerTest(unittest.TestCase):
    def test_returns_error_dict_instead_of_raising(self):
        with patch("zero.sandbox.shutil.which", return_value=None):
            out = run_sandboxed("result = 1", {})
        self.assertIsNone(out["result"])
        self.assertEqual(out["stdout"], "")
        self.assertIn("Docker", out["error"])

    def test_unsafe_ctx_raises_before_touching_docker(self):
        with patch("zero.sandbox.shutil.which", return_value="/usr/bin/docker"), \
             patch("zero.sandbox.subprocess.run") as mock_run:
            with self.assertRaises(ValueError):
                run_sandboxed("result = 1", {"secret_key": "x"})
            mock_run.assert_not_called()


class DockerCommandShapeTest(unittest.TestCase):
    """Confirma que el comando docker run construido trae CADA flag de
    seguridad exigido — sin necesitar Docker real instalado."""

    def test_command_includes_all_required_security_flags(self):
        fake = MagicMock(returncode=0, stdout='{"result": 1, "stdout": "", "error": null}', stderr="")
        with patch("zero.sandbox.shutil.which", return_value="/usr/bin/docker"), \
             patch("zero.sandbox.subprocess.run", return_value=fake) as mock_run:
            run_sandboxed("result = 1", {"ok": True})
        cmd = mock_run.call_args[0][0]
        joined = " ".join(cmd)
        for flag in (
            "--rm",
            "--network=none",
            "--memory=128m",
            "--memory-swap=128m",
            "--cpus=0.5",
            "--pids-limit=50",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "1000:1000",
            "python:3.14-slim",
        ):
            self.assertIn(flag, joined, f"falta el flag de seguridad: {flag}")
        self.assertIn("/tmp:size=16m", joined)
        self.assertNotIn("docker.sock", joined)
        self.assertTrue(any(":ro" in part for part in cmd), "el mount de /sandbox debe ser read-only")


@unittest.skipUnless(_DOCKER_AVAILABLE, "docker no instalado — este test es opcional, no núcleo")
class RealDockerTest(unittest.TestCase):
    def test_simple_code_returns_result(self):
        out = run_sandboxed("result = {'ok': True, 'n': 1 + 1}", {})
        self.assertIsNone(out["error"])
        self.assertEqual(out["result"], {"ok": True, "n": 2})

    def test_stdout_is_captured(self):
        out = run_sandboxed("print('hola desde el sandbox'); result = None", {})
        self.assertIsNone(out["error"])
        self.assertIn("hola desde el sandbox", out["stdout"])

    def test_ctx_is_available_inside(self):
        out = run_sandboxed("result = ctx['lead']['nombre']", {"lead": {"nombre": "Acme"}})
        self.assertIsNone(out["error"])
        self.assertEqual(out["result"], "Acme")

    def test_exception_in_code_is_captured_not_raised(self):
        out = run_sandboxed("raise ValueError('boom')", {})
        self.assertIsNone(out["result"])
        self.assertIn("boom", out["error"])

    def test_network_is_actually_blocked(self):
        code = (
            "import socket\n"
            "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "s.settimeout(3)\n"
            "try:\n"
            "    s.connect(('8.8.8.8', 53))\n"
            "    result = 'CONECTADO'\n"
            "except Exception as e:\n"
            "    result = 'bloqueado: ' + str(e)\n"
        )
        out = run_sandboxed(code, {}, timeout=15)
        self.assertIsNotNone(out["result"])
        self.assertNotEqual(out["result"], "CONECTADO", "--network=none no está bloqueando la red de verdad")
        self.assertTrue(out["result"].startswith("bloqueado"))

    def test_infinite_loop_is_killed_by_timeout(self):
        start = time.time()
        out = run_sandboxed("while True:\n    pass\n", {}, timeout=3)
        elapsed = time.time() - start
        self.assertLess(elapsed, 15, "run_sandboxed no debe colgarse esperando al contenedor")
        self.assertIn("Tiempo de ejecución excedido", out["error"])

    def test_write_outside_tmp_fails_readonly(self):
        code = "open('/write_test.txt', 'w').write('x')\nresult = 'ESCRIBIO'\n"
        out = run_sandboxed(code, {}, timeout=15)
        self.assertNotEqual(out["result"], "ESCRIBIO", "--read-only no está bloqueando escritura de verdad")
        self.assertIsNotNone(out["error"])

    def test_write_inside_tmp_succeeds(self):
        code = "open('/tmp/scratch.txt', 'w').write('x')\nresult = 'ok'\n"
        out = run_sandboxed(code, {}, timeout=15)
        self.assertIsNone(out["error"])
        self.assertEqual(out["result"], "ok")

    def test_non_json_serializable_result_becomes_none_with_error(self):
        out = run_sandboxed("result = {1, 2, 3}", {})  # un set no es serializable
        self.assertIsNone(out["result"])
        self.assertIsNotNone(out["error"])


if __name__ == "__main__":
    unittest.main()
