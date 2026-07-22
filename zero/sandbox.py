"""Ejecuta código Python arbitrario de forma aislada — la base de seguridad del
futuro sistema de "funciones programadas" (fases 2 y 3: registro y pantalla en
el dashboard, todavía no construidas). Este módulo es 100% autocontenido: no lo
llama nada del sistema todavía.

Diseño: cada llamada a run_sandboxed() lanza un contenedor Docker desechable
(python:3.14-slim — misma versión que corre el backend en producción, ver
.github/workflows/tests.yml) con `docker` invocado vía `subprocess`, no una
librería cliente (mismo criterio que zero/calls.py invocando curl).

Aislamiento del contenedor (todo obligatorio, ver run_sandboxed._DOCKER_FLAGS):
  --network=none          cero acceso a red — ni internet, ni el backend, ni
                           otros contenedores.
  --memory / --cpus        límites de recursos, sin swap extra.
  --pids-limit=50          evita fork bombs.
  --read-only + tmpfs      filesystem de solo lectura; único lugar escribible
                           es un tmpfs chico en /tmp.
  --cap-drop=ALL           sin ningún privilegio de Linux.
  --security-opt=no-new-privileges
  --user 1000:1000         nunca corre como root dentro del contenedor.
  --rm + --name + kill     el contenedor se destruye solo al salir; si se pasa
                           del timeout lo matamos explícitamente por nombre
                           (ver _force_kill) porque matar el proceso `docker`
                           del lado del host NO garantiza matar el contenedor
                           que dockerd sigue corriendo.

El socket de Docker (/var/run/docker.sock) NUNCA se monta — eso le daría al
código sandboxed control sobre Docker mismo y sería fuga total del
aislamiento. No hay ningún camino en este módulo para hacerlo.

`code` y `ctx` se pasan al contenedor solo como archivos montados de solo
lectura (nunca variables de entorno). Antes de tocar Docker, run_sandboxed()
valida que `ctx` no tenga ningún campo con pinta de credencial (token/key/
secret/password/credential/auth) — ese contrato lo decide la fase 2 (quién arma
el ctx real), pero este módulo está diseñado para que sea imposible meter un
secreto ahí por accidente.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict

_SANDBOX_IMAGE = "python:3.14-slim"  # fija, nunca :latest — calza con el Python de producción
_MEMORY_LIMIT = "128m"
_CPU_LIMIT = "0.5"
_PIDS_LIMIT = "50"
_TMPFS_SIZE = "16m"
_RUN_AS = "1000:1000"
_STOP_TIMEOUT = "1"  # segundos de gracia tras SIGTERM — el corte real lo hace _force_kill()

# Campos de ctx con nombres que suenan a credencial → run_sandboxed los rechaza
# antes de escribir nada a disco o tocar Docker. Conservador a propósito: mejor
# rechazar de más (ej. "keyword") que dejar pasar un secreto por accidente.
_FORBIDDEN_KEY_SUBSTRINGS = ("token", "key", "secret", "password", "credential", "auth")

# Script fijo que corre DENTRO del contenedor. Lee code.py y ctx.json (montados
# read-only en /sandbox), ejecuta el código con `ctx` como global, y escribe UN
# solo JSON a stdout — es el único canal de salida que existe (no hay red).
_RUNNER_SOURCE = '''\
import contextlib
import io
import json
import sys


def main():
    with open("/sandbox/code.py", "r") as f:
        code = f.read()
    with open("/sandbox/ctx.json", "r") as f:
        ctx = json.load(f)

    ns = {"ctx": ctx}
    buf = io.StringIO()
    result = None
    error = None
    try:
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<sandboxed>", "exec"), ns)
        result = ns.get("result")
        json.dumps(result)  # falla temprano si el resultado no es serializable
    except BaseException as exc:
        error = "{}: {}".format(type(exc).__name__, exc)
        result = None

    sys.stdout.write(json.dumps({"result": result, "stdout": buf.getvalue(), "error": error}))


if __name__ == "__main__":
    main()
'''


def _assert_ctx_is_safe(value: Any, path: str = "ctx") -> None:
    """Recorre ctx buscando claves con nombre de credencial. Levanta ValueError
    si encuentra una — a propósito, ANTES de escribir nada a disco."""
    if isinstance(value, dict):
        for k, v in value.items():
            key_lower = str(k).lower()
            for bad in _FORBIDDEN_KEY_SUBSTRINGS:
                if bad in key_lower:
                    raise ValueError(
                        f"ctx contiene un campo con nombre sospechoso de credencial: "
                        f"'{path}.{k}' (coincide con '{bad}'). run_sandboxed rechaza esto "
                        f"a propósito — ctx nunca debe poder llevar secretos reales."
                    )
            _assert_ctx_is_safe(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _assert_ctx_is_safe(item, f"{path}[{i}]")


def _force_kill(container_name: str) -> None:
    """Best-effort: garantiza que el contenedor no sobreviva a un timeout. Matar
    el subprocess `docker run` del lado del host (lo que hace subprocess.run al
    expirar su timeout) mata al CLIENTE docker, no necesariamente al contenedor
    que dockerd sigue corriendo — por eso lo matamos explícitamente por nombre."""
    try:
        subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=5)
    except Exception:
        pass


def run_sandboxed(code: str, ctx: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
    """Ejecuta `code` de forma aislada en un contenedor Docker desechable.

    `code` corre con una variable global `ctx` (el dict pasado acá, tal cual).
    La convención es que `code` deje su salida en una variable `result`
    (ej. `result = {"ok": True}`) — no es una llamada a función, es un script.

    Devuelve siempre un dict con exactamente estas 3 claves, nunca lanza por un
    fallo del código sandboxed (sí puede lanzar ValueError si `ctx` no pasa la
    validación de seguridad, o si `ctx`/`code` tienen un tipo inválido — eso es
    un error de quien llama, no del código sandboxed):
      - "result": el valor de `result` al terminar el código, o None si no se
        definió, si no es serializable a JSON, o si hubo cualquier error.
      - "stdout": todo lo que el código imprimió con print(...), como texto.
        Cadena vacía si no imprimió nada o si el sandbox nunca llegó a correr.
      - "error": None si todo salió bien; si no, una descripción corta de qué
        falló (excepción del código, timeout, Docker no disponible, límite de
        memoria/proceso, salida inválida, etc.).

    Nunca monta el socket de Docker, nunca pasa datos por variables de entorno,
    nunca corre como root, nunca tiene acceso a red. Ver el docstring del módulo
    para el detalle completo de las restricciones del contenedor.
    """
    if not shutil.which("docker"):
        return {"result": None, "stdout": "", "error": "Docker no está disponible en este sistema"}

    _assert_ctx_is_safe(ctx)

    try:
        ctx_json = json.dumps(ctx)
    except TypeError as e:
        raise ValueError(f"ctx no es serializable a JSON: {e}") from e

    tmpdir = tempfile.mkdtemp(prefix="zero-sandbox-")
    container_name = f"zero-sandbox-{uuid.uuid4().hex[:12]}"
    try:
        (Path(tmpdir) / "code.py").write_text(code)
        (Path(tmpdir) / "ctx.json").write_text(ctx_json)
        (Path(tmpdir) / "runner.py").write_text(_RUNNER_SOURCE)
        # mkdtemp crea el directorio en modo 0700 (solo el dueño) — el usuario
        # no-root (1000:1000) dentro del contenedor necesita poder leerlo.
        os.chmod(tmpdir, 0o755)
        for name in ("code.py", "ctx.json", "runner.py"):
            os.chmod(Path(tmpdir) / name, 0o644)

        cmd = [
            "docker", "run",
            "--rm",
            "--name", container_name,
            "--network=none",
            f"--memory={_MEMORY_LIMIT}", f"--memory-swap={_MEMORY_LIMIT}",
            f"--cpus={_CPU_LIMIT}",
            f"--pids-limit={_PIDS_LIMIT}",
            "--read-only",
            "--tmpfs", f"/tmp:size={_TMPFS_SIZE}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user", _RUN_AS,
            "--stop-timeout", _STOP_TIMEOUT,
            "-v", f"{tmpdir}:/sandbox:ro",
            _SANDBOX_IMAGE,
            "python3", "/sandbox/runner.py",
        ]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            _force_kill(container_name)
            return {"result": None, "stdout": "", "error": f"Tiempo de ejecución excedido ({timeout}s)"}

        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()
            if proc.returncode == 137:
                stderr = stderr or "el contenedor fue terminado (posible límite de memoria)"
            return {
                "result": None,
                "stdout": proc.stdout or "",
                "error": stderr or f"docker run terminó con código {proc.returncode}",
            }

        try:
            payload = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            return {"result": None, "stdout": proc.stdout or "", "error": "salida inválida del sandbox (no es JSON)"}

        return {
            "result": payload.get("result"),
            "stdout": payload.get("stdout", ""),
            "error": payload.get("error"),
        }
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
