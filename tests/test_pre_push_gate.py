"""El gate de pre-push: la suite en verde es condición para empujar.

Prueba .githooks/pre-push contra repos de juguete (sin red, sin tocar este repo)
y .claude/hooks/guardia-push.sh, que le niega a un agente las salidas del gate.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
HOOK = RAIZ / ".githooks" / "pre-push"
GUARDIA = RAIZ / ".claude" / "hooks" / "guardia-push.sh"
CERO = "0" * 40

VERDE = "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
ROJO = "import unittest\nclass T(unittest.TestCase):\n    def test_mal(self):\n        self.assertTrue(False)\n"
VACIO = "# sin tests\n"


def _git(repo: Path, *args: str) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_NOSYSTEM="1", HOME=str(repo.parent))
    return subprocess.run(["git", "-C", str(repo), *args], check=True, env=env,
                          capture_output=True, text=True).stdout.strip()


class PrePushGate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        _git(self.repo, "init", "-q")

    def tearDown(self):
        self._tmp.cleanup()

    def _commit(self, cuerpo: str | None) -> str:
        if cuerpo is not None:
            (self.repo / "tests").mkdir(exist_ok=True)
            (self.repo / "tests" / "__init__.py").write_text("")
            (self.repo / "tests" / "test_x.py").write_text(cuerpo)
        else:
            (self.repo / "LEEME").write_text("sin tests\n")
        _git(self.repo, "add", "-A")
        _git(self.repo, "commit", "-q", "-m", "c")
        return _git(self.repo, "rev-parse", "HEAD")

    def _empujar(self, *shas: str) -> subprocess.CompletedProcess:
        stdin = "".join(f"refs/heads/main {s} refs/heads/main {CERO}\n" for s in shas)
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        return subprocess.run(["bash", str(HOOK), "origin", "x"], cwd=self.repo, input=stdin,
                              capture_output=True, text=True, env=env, timeout=120)

    def test_suite_verde_deja_empujar(self):
        r = self._empujar(self._commit(VERDE))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("verde", r.stderr)

    def test_suite_roja_rechaza_el_push(self):
        r = self._empujar(self._commit(ROJO))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("ROJO", r.stderr)
        self.assertIn("FAIL: test_mal", r.stderr)

    def test_suite_que_no_corre_nada_no_cuenta_como_verde(self):
        r = self._empujar(self._commit(VACIO))
        self.assertNotEqual(r.returncode, 0, "«Ran 0 tests» con salida 0 no es verde")

    def test_prueba_el_commit_no_el_arbol_de_trabajo(self):
        sha = self._commit(ROJO)
        (self.repo / "tests" / "test_x.py").write_text(VERDE)   # arreglo sin commitear
        self.assertNotEqual(self._empujar(sha).returncode, 0)
        sha_verde = self._commit(VERDE)
        (self.repo / "tests" / "test_x.py").write_text(ROJO)     # rotura sin commitear
        self.assertEqual(self._empujar(sha_verde).returncode, 0)

    def test_un_commit_rojo_entre_varios_rechaza_todo(self):
        verde = self._commit(VERDE)
        rojo = self._commit(ROJO)
        self.assertNotEqual(self._empujar(verde, rojo).returncode, 0)

    def test_borrar_rama_remota_y_commit_sin_tests_pasan(self):
        self.assertEqual(self._empujar(CERO).returncode, 0)
        self.assertEqual(self._empujar(self._commit(None)).returncode, 0)

    def test_un_test_que_lee_stdin_no_se_come_las_demas_refs(self):
        come = ("import sys, unittest\nclass T(unittest.TestCase):\n"
                "    def test_lee(self):\n        sys.stdin.read()\n")
        primero = self._commit(come)
        rojo = self._commit(ROJO)
        r = self._empujar(primero, rojo)
        self.assertNotEqual(r.returncode, 0, "la segunda ref (roja) debió probarse")

    def test_no_hereda_credenciales_de_la_shell(self):
        espia = ("import os, unittest\nclass T(unittest.TestCase):\n"
                 "    def test_limpio(self):\n        self.assertNotIn('SUPABASE_KEY', os.environ)\n")
        sha = self._commit(espia)
        stdin = f"refs/heads/main {sha} refs/heads/main {CERO}\n"
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env["SUPABASE_KEY"] = "secreto"
        r = subprocess.run(["bash", str(HOOK), "origin", "x"], cwd=self.repo, input=stdin,
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_no_deja_worktrees_colgando(self):
        self._empujar(self._commit(ROJO))
        self.assertEqual(len(_git(self.repo, "worktree", "list").splitlines()), 1)


class GuardiaDelAgente(unittest.TestCase):
    def _bloquea(self, comando: str) -> bool:
        r = subprocess.run(["bash", str(GUARDIA)], capture_output=True, text=True,
                           input=json.dumps({"tool_name": "Bash", "tool_input": {"command": comando}}))
        self.assertIn(r.returncode, (0, 2), r.stderr)
        return r.returncode == 2

    def test_niega_las_salidas_del_gate(self):
        for c in ("git push --no-verify",
                  "git push origin main --no-verify",
                  "cd x && git push -u origin rama --no-verify",
                  "git -c core.hooksPath=/dev/null push",
                  "git config core.hooksPath /dev/null",
                  "git config --unset core.hooksPath",
                  "git push --no-ver origin main",
                  "git push --no-v",
                  "git config core.hooksPath /dev/null; echo get",
                  "git config core.hooksPath .githooks-vacio",
                  "git config core.hooksPath .githooks",
                  "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x git push"):
            self.assertTrue(self._bloquea(c), c)

    def test_deja_pasar_lo_normal(self):
        for c in ("git push", "git push origin main", "git status",
                  "git config --get core.hooksPath",
                  "git commit -m 'no-verify en el mensaje'",
                  "python3 -m unittest discover -s tests -t ."):
            self.assertFalse(self._bloquea(c), c)


if __name__ == "__main__":
    unittest.main()
