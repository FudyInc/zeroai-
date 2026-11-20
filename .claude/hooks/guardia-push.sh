#!/usr/bin/env bash
# PreToolUse (Bash) — un agente no puede saltarse el gate de pre-push.
#
# .githooks/pre-push exige la suite en verde antes de cada push. Git deja dos
# salidas: --no-verify y apagar core.hooksPath. Este hook se las niega a los
# agentes; Diego, desde su terminal, sigue teniendo --no-verify para emergencias.
# Exit 2 = Claude Code bloquea la llamada y le muestra el motivo al agente.
#
# Es una barrera contra el descuido, no contra la intención: editar .git/config a
# mano o borrar el hook no se detecta aquí. Falla abierto (exit 0) si la entrada
# no es JSON legible, para no trabar toda la sesión por un formato raro.
python3 -I -c '
import json, re, sys
try:
    cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "") or ""
except Exception:
    sys.exit(0)
motivo = None
# git acepta prefijos únicos de opciones largas: --no-v, --no-ver… valen como --no-verify.
if re.search(r"\bgit\b", cmd) and re.search(r"\bpush\b", cmd) and re.search(r"(^|\s)--no-v(e(r(i(fy?)?)?)?)?(?=\s|$|=)", cmd):
    motivo = "git push --no-verify salta el gate de la suite"
elif re.search(r"core\.hookspath|GIT_CONFIG_(COUNT|PARAMETERS|KEY_)", cmd, re.I):
    c = cmd.strip()
    # El gate vive en .git/hooks/pre-push; fijar core.hooksPath (a lo que sea) hace
    # que git deje de mirar ahí. Solo se permite leer el valor.
    lectura = re.fullmatch(r"git\s+config\s+(--(get|get-all|show-origin)\s+)+core\.hooksPath", c, re.I)
    if not lectura:
        motivo = "tocar core.hooksPath (o inyectar config por entorno) apaga el gate de la suite"
if motivo:
    print(f"Bloqueado: {motivo} (.githooks/pre-push). Regla «Cierre» de CLAUDE.md: "
          "nada se empuja sin la suite en verde. Arregla la suite; si de verdad hay "
          "que saltarla, pídeselo a Diego.", file=sys.stderr)
    sys.exit(2)
'
