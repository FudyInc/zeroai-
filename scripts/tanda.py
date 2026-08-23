#!/usr/bin/env python3
"""Corre una tanda de trabajo autónomo: toma tareas de la cola, las ejecuta en su
workspace, las somete al juez y commitea solo lo aprobado.

    python3 scripts/tanda.py                  # simulacro: dice qué haría, no ejecuta
    python3 scripts/tanda.py --ejecutar       # de verdad
    python3 scripts/tanda.py --ejecutar --max 2 --workspace dashboard

**Simulacro por defecto, siempre.** Esto lanza agentes con permiso de escritura sobre el
código; que arranque solo por escribir mal un comando sería el peor default posible.

## Las cuatro puertas

Ninguna es opcional, y están en este orden a propósito — cada una es más cara que la
anterior, así que la barata corre primero:

1. **Aislamiento.** Si un workspace tiene `.env`, la tanda se aborta entera. Sin `.env`
   el código cae a mock: no manda correos, no toca el CRM de Supabase, no gasta en APIs.
   Ese es el único motivo por el que soltar un agente acá es aceptable — hoy se cumple
   por omisión, y esta puerta lo vuelve una condición explícita.
2. **Alcance.** Al agente se le dice qué archivos puede tocar, y después se verifica qué
   tocó de verdad. Decirlo no basta: hay que comprobarlo.
3. **Tests.** La suite completa, en el workspace, después del cambio. En rojo no pasa
   nada, sin discusión.
4. **Juez.** `prompts/juez-codigo.md` lee el diff y decide. Es la última puerta antes de
   que quede código que nadie miró.

Solo lo aprobado se commitea, y **siempre en la rama del workspace, nunca en main**. El
merge a main sigue siendo una decisión de Diego.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero import tasks                        # noqa: E402
from zero._env import load_env                # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PADRE = REPO.parent

# Modelo por defecto para ejecutar y para juzgar. Haiku a propósito: las tareas de una
# tanda son acotadas y el juez decide sobre reglas objetivas — pagar Opus por eso es
# gastar lo caro en lo barato (mismo criterio que las automatizaciones sin IA).
MODELO_AGENTE = os.environ.get("TANDA_MODELO_AGENTE") or "haiku"
MODELO_JUEZ = os.environ.get("TANDA_MODELO_JUEZ") or "haiku"

# Techo de tiempo por tarea. Un agente atascado consume cuota sin producir nada, y en
# una tanda nocturna nadie lo va a ver colgado.
TIMEOUT_AGENTE = int(os.environ.get("TANDA_TIMEOUT") or 900)
TIMEOUT_TESTS = 900


def ruta_workspace(ws: str) -> Path:
    return PADRE / f"zero-{ws}"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                          text=True, timeout=120).stdout.strip()


# --- Puerta 1: aislamiento ----------------------------------------------------------
def revisar_aislamiento() -> List[str]:
    """Workspaces que tienen credenciales. Cualquiera aborta la tanda entera."""
    con_credenciales = []
    for ws in tasks.WORKSPACES:
        d = ruta_workspace(ws)
        if not d.exists():
            continue
        for archivo in (".env", "crm.json", "users.json"):
            if (d / archivo).exists():
                con_credenciales.append(f"{ws}/{archivo}")
    return con_credenciales


def workspace_limpio(ws: str) -> Tuple[bool, str]:
    """Un worktree con cambios sin commitear no se toca: son de una persona.

    También se exige estar **al día con origin/main**. Un agente trabajando sobre una
    rama atrasada reimplementa lo que ya existe en main y produce un conflicto o, peor,
    un duplicado que nadie nota — que es exactamente cómo aparecieron los duplicados de
    `/api/vendors` y de Vercel.
    """
    d = ruta_workspace(ws)
    if not d.exists():
        return False, "no existe"
    sucio = _git(d, "status", "--porcelain")
    if sucio:
        return False, f"{len(sucio.splitlines())} archivos sin commitear"
    atraso = _git(d, "rev-list", "--count", "HEAD..origin/main")
    if atraso.isdigit() and int(atraso) > 0:
        return False, f"{atraso} commits atrás de origin/main (corre el sync primero)"
    return True, ""


def sincronizar() -> None:
    """Pone los workspaces al día antes de repartir trabajo. Reusa el script ya probado,
    que nunca descarta trabajo propio: salta lo que tenga cambios sin subir."""
    script = REPO / "scripts" / "sincronizar-workspaces.sh"
    try:
        r = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=300)
        print(r.stdout.strip() or "(sync sin salida)")
    except Exception as e:   # noqa: BLE001
        print(f"(no se pudo sincronizar: {e})")


# --- Ejecución -----------------------------------------------------------------------
def _instruccion(tarea: Dict[str, Any]) -> str:
    """El prompt que recibe el agente. El alcance va primero y en duro: es la regla que
    más se rompe, y la que hace que dos tareas paralelas no se pisen."""
    archivos = tarea.get("archivos") or []
    alcance = ("\n".join(f"  - {a}" for a in archivos)
               if archivos else "  (no se declararon archivos: no crees ninguno nuevo "
                                "fuera de lo estrictamente necesario)")
    return f"""{tarea['prompt']}

--- REGLAS DE ESTA TAREA (no negociables) ---

SOLO puedes modificar estos archivos:
{alcance}

Cualquier cambio fuera de esa lista hace que el trabajo se descarte entero, aunque esté
bien hecho.

Además:
- NO instales dependencias ni agregues imports de terceros: el núcleo es solo stdlib.
- NO toques .env, state.json, crm.json, users.json ni deploy/.
- NO borres ni debilites tests para que pasen.
- Los números de negocio van en zero/config.py, nunca dentro de la lógica.
- Al terminar, corre: python3 -m unittest discover -s tests -t .
- NO hagas commit ni push: de eso se encarga la tanda después de que el juez revise.

Trabaja y termina. No preguntes: nadie va a responderte."""


def correr_agente(tarea: Dict[str, Any], modelo: str) -> Tuple[bool, str]:
    """Lanza al agente en el worktree de la tarea. (ok, salida)."""
    d = ruta_workspace(tarea["workspace"])
    cmd = ["claude", "-p", _instruccion(tarea), "--model", modelo,
           # El agente corre en un worktree sin credenciales y con alcance verificado
           # después; sin esto no puede editar archivos en modo no interactivo.
           "--permission-mode", "acceptEdits"]
    try:
        r = subprocess.run(cmd, cwd=str(d), capture_output=True, text=True,
                           timeout=TIMEOUT_AGENTE)
        return r.returncode == 0, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return False, f"el agente pasó de {TIMEOUT_AGENTE}s y se cortó"
    except FileNotFoundError:
        return False, "no se encontró el ejecutable `claude` en el PATH"


# --- Puerta 2: alcance ---------------------------------------------------------------
def fuera_de_alcance(tarea: Dict[str, Any]) -> List[str]:
    d = ruta_workspace(tarea["workspace"])
    tocados = [l[3:].strip() for l in _git(d, "status", "--porcelain").splitlines() if l]
    permitidos = set(tarea.get("archivos") or [])
    if not permitidos:
        return []
    return [t for t in tocados if t not in permitidos]


# --- Puerta 3: tests -----------------------------------------------------------------
def correr_tests(ws: str) -> Tuple[bool, str]:
    d = ruta_workspace(ws)
    try:
        r = subprocess.run(["python3", "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                           cwd=str(d), capture_output=True, text=True, timeout=TIMEOUT_TESTS)
        salida = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, salida[-4000:]
    except subprocess.TimeoutExpired:
        return False, f"la suite pasó de {TIMEOUT_TESTS}s"


# --- Puerta 4: el juez ---------------------------------------------------------------
def juzgar(tarea: Dict[str, Any], diff: str, salida_tests: str,
           tocados: List[str], modelo: str) -> Dict[str, Any]:
    """Somete el trabajo a prompts/juez-codigo.md. Un juez que no responde JSON válido
    NO se interpreta como aprobación: sin veredicto legible, no pasa."""
    prompt_juez = (REPO / "prompts" / "juez-codigo.md").read_text(encoding="utf-8")
    task = {
        "tarea": {"titulo": tarea["titulo"], "prompt": tarea["prompt"],
                  "archivos": tarea.get("archivos") or []},
        # El diff se acota: un juez con 200 KB de contexto juzga peor, no mejor.
        "diff": diff[:60000],
        "tests": salida_tests[-3000:],
        "archivos_tocados": tocados,
    }
    cmd = ["claude", "-p", json.dumps(task, ensure_ascii=False),
           "--model", modelo, "--append-system-prompt", prompt_juez]
    try:
        r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=600)
        crudo = (r.stdout or "").strip()
    except Exception as e:   # noqa: BLE001
        return {"aprobado": False, "motivo_rechazo": f"el juez no pudo correr ({e})",
                "riesgos": [], "hizo_lo_pedido": False, "notas": ""}

    inicio, fin = crudo.find("{"), crudo.rfind("}")
    if inicio == -1 or fin == -1:
        return {"aprobado": False, "motivo_rechazo": "el juez no devolvió JSON",
                "riesgos": [], "hizo_lo_pedido": False, "notas": crudo[:300]}
    try:
        veredicto = json.loads(crudo[inicio:fin + 1])
    except json.JSONDecodeError:
        return {"aprobado": False, "motivo_rechazo": "el juez devolvió JSON inválido",
                "riesgos": [], "hizo_lo_pedido": False, "notas": crudo[:300]}
    veredicto["aprobado"] = bool(veredicto.get("aprobado"))
    return veredicto


def commitear(tarea: Dict[str, Any], veredicto: Dict[str, Any]) -> str:
    """Commit en la rama del workspace. Nunca en main, nunca push: el merge lo decide
    una persona mirando el trabajo."""
    d = ruta_workspace(tarea["workspace"])
    mensaje = (f"{tarea['titulo']}\n\n"
               f"Tarea automática {tarea['id']} ({tarea.get('origen')}).\n"
               f"Juez: {veredicto.get('notas') or 'aprobada'}\n\n"
               f"Co-Authored-By: Claude <noreply@anthropic.com>")
    subprocess.run(["git", "add", "-A"], cwd=str(d), timeout=60)
    subprocess.run(["git", "commit", "-q", "-m", mensaje], cwd=str(d), timeout=120)
    return _git(d, "rev-parse", "--short", "HEAD")


def descartar(ws: str) -> None:
    """Deja el workspace como estaba. El trabajo rechazado no se guarda: su motivo sí
    queda en la tarea, que es lo que sirve para no repetir el error."""
    d = ruta_workspace(ws)
    subprocess.run(["git", "checkout", "--", "."], cwd=str(d), timeout=60)
    subprocess.run(["git", "clean", "-fd"], cwd=str(d), timeout=60)


# --- La tanda ------------------------------------------------------------------------
def procesar(tarea: Dict[str, Any], *, ejecutar: bool, modelo: str,
             modelo_juez: str) -> Dict[str, Any]:
    ws = tarea["workspace"]
    print(f"\n▶ [{ws}] {tarea['titulo']}  (intento {tarea['intentos']}, {tarea['origen']})")

    ok, motivo = workspace_limpio(ws)
    if not ok:
        # No es culpa de la tarea: vuelve a la cola sin gastarle un intento.
        print(f"  ⏭  workspace no disponible: {motivo}")
        tasks.devolver(tarea["id"], f"workspace no disponible: {motivo}")
        return {"tarea": tarea["id"], "resultado": "saltada"}

    if not ejecutar:
        print(f"  (simulacro) correría el agente sobre: {', '.join(tarea.get('archivos') or ['—'])}")
        # Un simulacro no intentó nada: devolver la tarea intacta. Si no, mirar dos
        # veces qué haría la tanda dejaría la tarea atascada sin haberla corrido nunca.
        tasks.devolver(tarea["id"], "simulacro")
        return {"tarea": tarea["id"], "resultado": "simulacro"}

    t0 = time.time()
    ok, salida = correr_agente(tarea, modelo)
    print(f"  agente: {'ok' if ok else 'falló'} ({time.time() - t0:.0f}s)")
    if not ok:
        descartar(ws)
        tasks.juzgar(tarea["id"], aprobada=False,
                     veredicto={"motivo_rechazo": "el agente no terminó",
                                "notas": salida[-400:]})
        return {"tarea": tarea["id"], "resultado": "agente_falló"}

    sobrantes = fuera_de_alcance(tarea)
    if sobrantes:
        print(f"  ✗ fuera de alcance: {', '.join(sobrantes[:5])}")
        descartar(ws)
        tasks.juzgar(tarea["id"], aprobada=False,
                     veredicto={"motivo_rechazo": f"tocó archivos fuera del alcance: {sobrantes[:5]}"})
        return {"tarea": tarea["id"], "resultado": "fuera_de_alcance"}

    d = ruta_workspace(ws)
    diff = _git(d, "diff") or _git(d, "diff", "--staged")
    if not diff.strip() and not _git(d, "status", "--porcelain"):
        print("  ✗ no cambió nada")
        tasks.juzgar(tarea["id"], aprobada=False,
                     veredicto={"motivo_rechazo": "el agente no dejó ningún cambio"})
        return {"tarea": tarea["id"], "resultado": "sin_cambios"}

    verde, salida_tests = correr_tests(ws)
    print(f"  tests: {'verde' if verde else 'ROJO'}")
    if not verde:
        descartar(ws)
        tasks.juzgar(tarea["id"], aprobada=False,
                     veredicto={"motivo_rechazo": "tests en rojo",
                                "notas": salida_tests[-400:]})
        return {"tarea": tarea["id"], "resultado": "tests_rojos"}

    tocados = [l[3:].strip() for l in _git(d, "status", "--porcelain").splitlines() if l]
    tasks.a_revision(tarea["id"], rama=_git(d, "rev-parse", "--abbrev-ref", "HEAD"))
    veredicto = juzgar(tarea, diff, salida_tests, tocados, modelo_juez)
    print(f"  juez: {'APROBADA' if veredicto['aprobado'] else 'rechazada'}"
          f" — {veredicto.get('motivo_rechazo') or veredicto.get('notas') or ''}")

    if not veredicto["aprobado"]:
        descartar(ws)
        tasks.juzgar(tarea["id"], aprobada=False, veredicto=veredicto)
        return {"tarea": tarea["id"], "resultado": "rechazada"}

    commit = commitear(tarea, veredicto)
    tasks.juzgar(tarea["id"], aprobada=True, veredicto=veredicto)
    tasks._actualizar(tarea["id"], {"commit": commit}, f"commit {commit}")
    print(f"  ✓ commiteada en {ws}: {commit}")
    return {"tarea": tarea["id"], "resultado": "aprobada", "commit": commit}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ejecutar", action="store_true",
                    help="ejecuta de verdad (sin esto, solo dice qué haría)")
    ap.add_argument("--max", type=int, default=3, help="tope de tareas en esta tanda")
    ap.add_argument("--workspace", help="limitar a un workspace")
    ap.add_argument("--modelo", default=MODELO_AGENTE)
    ap.add_argument("--modelo-juez", default=MODELO_JUEZ)
    ap.add_argument("--avisar", action="store_true", help="manda el resumen al dueño")
    args = ap.parse_args()

    load_env()

    intrusos = revisar_aislamiento()
    if intrusos:
        print("✗ TANDA ABORTADA — hay credenciales o datos de producción en un workspace:")
        for i in intrusos:
            print(f"    {i}")
        print("\n  Un agente autónomo ahí puede mandar correos reales y escribir en el "
              "CRM de producción.\n  Saca esos archivos del workspace antes de correr una tanda.")
        return 2

    # Tareas zombi: si un proceso murió a mitad (se apagó el PC, se colgó el agente),
    # su tarea quedó "en curso" y bloquea el workspace entero, en silencio.
    for t in tasks.liberar_colgadas():
        print(f"↺ liberada tarea colgada: [{t['workspace']}] {t['titulo']}")

    if args.ejecutar:
        # Antes de repartir nada: los workspaces al día. Es barato y evita la clase de
        # error más cara del repo (trabajo duplicado sobre una rama vieja).
        sincronizar()

    workspaces = [args.workspace] if args.workspace else list(tasks.WORKSPACES)
    hechas: List[Dict[str, Any]] = []

    for ws in workspaces:
        if len(hechas) >= args.max:
            break
        tarea = tasks.tomar(ws)
        if tarea is None:
            continue
        hechas.append(procesar(tarea, ejecutar=args.ejecutar, modelo=args.modelo,
                               modelo_juez=args.modelo_juez))

    print()
    if not hechas:
        print("no había tareas pendientes")
        return 0

    for h in hechas:
        print(f"  {h['resultado']:16} {h['tarea']}")
    aprobadas = sum(1 for h in hechas if h["resultado"] == "aprobada")
    print(f"\n{aprobadas}/{len(hechas)} aprobadas")

    if args.avisar and args.ejecutar:
        from zero.alerts import notify_owner
        lineas = [f"{h['resultado']}: {h['tarea']}" for h in hechas]
        notify_owner("ZERO — tanda automática:\n· " + "\n· ".join(lineas),
                     kind="tanda")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
