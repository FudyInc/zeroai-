#!/usr/bin/env python3
"""Convierte objetivos y señales del repo en tareas encoladas para los workspaces.

    python3 scripts/planificar.py --objetivo "subir el nivel visual del dashboard"
    python3 scripts/planificar.py                       # solo señales del repo
    python3 scripts/planificar.py --encolar             # encola de verdad

**Simulacro por defecto**: sin `--encolar` muestra las tareas propuestas y no toca la
cola. Una tarea mal planteada cuesta una corrida completa de agente, así que la primera
vez conviene leerlas.

## De dónde sale el trabajo

Dos fuentes, y el orden importa:

1. **Los objetivos de Diego** — por `--objetivo` (repetible) o el archivo `objetivos.md`
   de la raíz, una línea por objetivo. Siempre primero.
2. **Señales objetivas del repositorio** — pendientes del roadmap, `TODO`/`FIXME`,
   módulos sin test, tareas que quedaron atascadas. Rellenan el cupo que sobre.

Señales *medidas*, nunca "que al modelo se le ocurra algo": un planificador que inventa
trabajo produce features que nadie pidió y que igual hay que mantener después. Todo lo
que entra acá ya está escrito en alguna parte del repo por una persona.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero import tasks              # noqa: E402
from zero._env import load_env      # noqa: E402

REPO = Path(__file__).resolve().parent.parent
MODELO = os.environ.get("PLAN_MODELO") or "haiku"

# Qué workspace es dueño de qué. Los workspaces son ramas del MISMO repo: la separación
# es por zona de trabajo, no por código distinto. Sin este mapa el planificador manda
# trabajo de frontend a `core` y las tareas se pisan entre sí.
MAPA = {
    "core": "zero/ (núcleo: orquestador, agentes, contratos, CRM, config), main.py, tests/",
    "dashboard": "frontend/ (las 18 páginas del dashboard) y api.py (sus endpoints)",
    "landing": "web/ (la landing pública: HTML, CSS y JS sin build)",
    "motor-whatsapp": "zero/channels.py, zero/whatsapp_inbound.py, zero/twilio_inbound.py, "
                      "zero/agents/concierge.py",
    "motor-llamadas": "zero/calls.py, zero/voice.py",
    "prompts": "prompts/*.md (los prompts de cada agente)",
}


def _texto(ruta: Path) -> str:
    try:
        return ruta.read_text(encoding="utf-8")
    except OSError:
        return ""


# --- Señales: hechos, no opiniones --------------------------------------------------
def pendientes_del_roadmap() -> List[str]:
    """Casillas sin marcar en las notas de roadmap. Las escribió una persona."""
    salida = []
    for nombre in ("06 - Roadmap.md", "docs/roadmap.md"):
        for linea in _texto(REPO / nombre).splitlines():
            limpia = linea.strip()
            if limpia.startswith("- [ ]"):
                salida.append(limpia[5:].strip())
    return salida[:20]


def marcas_en_el_codigo() -> List[str]:
    """TODO / FIXME dejados en el código.

    El patrón exige la marca **pegada al inicio del comentario** (`# TODO`, `// FIXME`).
    Sin eso, en un repo escrito en español "todo" es una palabra corriente y colaban
    frases como "primero set_env() de TODO (así os.environ queda completo)" — una señal
    con ruido manda al planificador a inventar tareas sobre problemas que no existen.
    """
    try:
        r = subprocess.run(
            ["grep", "-rn", "-E", r"(#|//|/\*)\s*(TODO|FIXME)\b",
             "--include=*.py", "--include=*.jsx",
             "zero/", "api.py", "main.py", "frontend/src/"],
            cwd=str(REPO), capture_output=True, text=True, timeout=60)
        return [l.strip()[:200] for l in r.stdout.splitlines()][:20]
    except Exception:   # noqa: BLE001
        return []


def modulos_sin_test() -> List[str]:
    """Módulos de `zero/` que ningún test menciona siquiera.

    No basta con buscar `tests/test_<nombre>.py`: la mitad del núcleo está cubierta
    desde `test_core.py`, y contarlos como descubiertos produce una lista de quince
    módulos donde casi ninguno lo está de verdad. Se busca el nombre del módulo en el
    texto de los tests, que es una aproximación tosca pero honesta: si nadie lo nombra,
    nadie lo prueba.
    """
    texto_tests = " ".join(_texto(p) for p in (REPO / "tests").glob("test_*.py"))
    faltantes = []
    for modulo in sorted((REPO / "zero").glob("*.py")):
        if modulo.stem.startswith("_"):
            continue
        if re.search(rf"\b{re.escape(modulo.stem)}\b", texto_tests):
            continue
        faltantes.append(f"zero/{modulo.name}")
    return faltantes[:15]


def hallazgos_de_la_auditoria() -> List[str]:
    """Lo que `scripts/auditar.py` probó que está roto HOY.

    Es la señal de mayor calidad que tiene el planificador, porque cada línea viene con
    un comando que la reproduce: no es "podría haber un problema en X", es "esto falla,
    corre esto y lo ves". Una tarea nacida de acá tiene criterio de terminado gratis —
    el comando deja de fallar— que es justo lo que le falta a las tareas vagas.

    Se lee del informe en disco y no se corre la auditoría acá: el planificador no debe
    tardar diez minutos ni decidir cuándo se audita. Si el informe no existe todavía, no
    hay señal, y punto.
    """
    try:
        informe = json.loads((REPO / "auditoria.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    # Solo gravedad alta: lo medio se reporta para que una persona lo mire, no para
    # gastarle una corrida de agente automáticamente.
    return [f"[{h['check']}] {h['detalle']} — reproducir: {h['evidencia']}"
            for h in informe.get("hallazgos", []) if h.get("gravedad") == "alta"][:10]


def tareas_atascadas() -> List[str]:
    """Lo que el juez rechazó dos veces: o la tarea estaba mal planteada, o el problema
    es más difícil de lo que parecía. En ambos casos hay que replantearla, no repetirla."""
    return [f"{t['titulo']} — {(t.get('veredicto') or {}).get('motivo_rechazo') or 'sin motivo'}"
            for t in tasks.listar(estado=tasks.ATASCADA)][:10]


def recolectar_senales() -> Dict[str, List[str]]:
    return {
        "hallazgos_de_la_auditoria": hallazgos_de_la_auditoria(),
        "pendientes_del_roadmap": pendientes_del_roadmap(),
        "marcas_en_el_codigo": marcas_en_el_codigo(),
        "modulos_sin_test_propio": modulos_sin_test(),
        "tareas_atascadas": tareas_atascadas(),
    }


def leer_objetivos(extra: List[str]) -> List[str]:
    del_archivo = [l.strip() for l in _texto(REPO / "objetivos.md").splitlines()
                   if l.strip() and not l.strip().startswith("#")]
    return [*extra, *del_archivo]


# --- El planificador ----------------------------------------------------------------
def planificar(objetivos: List[str], senales: Dict[str, List[str]], cupo: int,
               modelo: str) -> Dict[str, Any]:
    prompt = _texto(REPO / "prompts" / "planificador.md")
    task = {
        "objetivos": objetivos,
        "señales": senales,
        "mapa": MAPA,
        "abiertas": [{"workspace": t["workspace"], "titulo": t["titulo"]}
                     for t in tasks.listar(abiertas=True)],
        "cupo": cupo,
    }
    cmd = ["claude", "-p", json.dumps(task, ensure_ascii=False),
           "--model", modelo, "--append-system-prompt", prompt]
    # `error` distingue "el planificador no pudo correr" de "corrió y no propuso nada".
    # Sin esa distinción los dos casos imprimían una salida casi igual y ambos salían
    # con 0: el 2026-08-30 el OAuth caducado se veía idéntico a un día sin trabajo
    # pendiente, y el ciclo autónomo siguió "verde" sin planificar nada.
    try:
        r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=600)
        crudo = (r.stdout or "").strip()
    except Exception as e:   # noqa: BLE001
        return {"tareas": [], "descartadas": [], "error": f"no se pudo ejecutar: {e}"}

    inicio, fin = crudo.find("{"), crudo.rfind("}")
    if inicio == -1:
        # Corrió, pero no devolvió JSON: la sesión caducada, el binario pidiendo login,
        # una cuota agotada. Todo eso sale por acá, y ninguno es "no había trabajo".
        detalle = (r.stderr or "").strip() or crudo or "sin salida"
        return {"tareas": [], "descartadas": [], "error": f"no devolvió JSON: {detalle[:300]}"}
    try:
        plan = json.loads(crudo[inicio:fin + 1])
    except json.JSONDecodeError as e:
        return {"tareas": [], "descartadas": [], "error": f"JSON inválido: {e}"}
    plan.setdefault("error", None)
    return plan


def validar(tarea: Dict[str, Any]) -> List[str]:
    """Revisa una tarea propuesta ANTES de encolarla.

    El planificador es un modelo: puede proponer un workspace que no existe o un archivo
    prohibido. Encolar sin revisar traslada ese error al agente, que lo va a ejecutar sin
    dudar — y recién ahí se descubre, después de gastar una corrida.
    """
    problemas = []
    if tarea.get("workspace") not in tasks.WORKSPACES:
        problemas.append(f"workspace inválido: {tarea.get('workspace')!r}")
    if not (tarea.get("titulo") or "").strip():
        problemas.append("sin título")
    if len((tarea.get("prompt") or "").strip()) < 40:
        problemas.append("prompt demasiado corto para trabajar sin preguntar")
    if not tarea.get("archivos"):
        problemas.append("sin archivos declarados (el agente no tendría alcance cerrado)")
    for archivo in tarea.get("archivos") or []:
        for prohibido in tasks.PROHIBIDOS:
            if str(archivo).startswith(prohibido):
                problemas.append(f"archivo prohibido: {archivo}")
    # Ya está en la cola o ya se hizo. Al planificador se le pasan las tareas abiertas
    # como contexto, pero eso es una sugerencia a un modelo: la cola llegó a tener dos
    # pares de duplicados exactos por título, y cada uno se come una corrida del cupo
    # diario rehaciendo trabajo hecho. `tasks.crear()` lo ataja igual; acá se muestra en
    # el simulacro, que es donde Diego lo puede leer antes de encolar.
    ya = tasks.duplicado_de(tarea.get("workspace") or "", tarea.get("titulo") or "")
    if ya is not None:
        problemas.append(f"duplicado de {ya['id']} ({ya['estado']}): {ya['titulo']}")
    return problemas


def mostrar_duplicados() -> int:
    """Lista los duplicados que ya están en la cola. Solo lista: no borra nada.

    Cuál de los dos se baja es una decisión de Diego — puede haber avanzado la segunda,
    o tener un prompt mejor. El código no adivina eso.
    """
    grupos = tasks.duplicados()
    if not grupos:
        print("sin duplicados en la cola")
        return 0
    print(f"{len(grupos)} título(s) duplicado(s) en la cola:")
    for grupo in grupos:
        print(f"\n  [{grupo[0]['workspace']}] {grupo[0]['titulo']}")
        for t in grupo:
            print(f"    · {t['id']}  {t['estado']:<11} origen={t.get('origen', '?')}")
    print("\n  (bájalas con: python3 -c \"from zero import tasks; tasks.cancelar('<id>')\")")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--objetivo", action="append", default=[],
                    help="un objetivo tuyo (repetible)")
    ap.add_argument("--cupo", type=int, default=3, help="tope de tareas a proponer")
    ap.add_argument("--encolar", action="store_true", help="encola de verdad")
    ap.add_argument("--modelo", default=MODELO)
    ap.add_argument("--duplicados", action="store_true",
                    help="lista los títulos repetidos que ya están en la cola y sale")
    args = ap.parse_args()

    if args.duplicados:
        return mostrar_duplicados()

    load_env()
    objetivos = leer_objetivos(args.objetivo)
    senales = recolectar_senales()

    print(f"objetivos: {len(objetivos)}")
    for o in objetivos:
        print(f"  · {o}")
    print("señales:")
    for k, v in senales.items():
        print(f"  {k}: {len(v)}")
    print()

    if not objetivos and not any(senales.values()):
        print("nada que planificar: sin objetivos y sin señales")
        return 0

    plan = planificar(objetivos, senales, args.cupo, args.modelo)
    propuestas = plan.get("tareas") or []

    if plan.get("error"):
        # No es lo mismo que un día tranquilo: hoy NO se planificó nada, y mañana el
        # ciclo arranca sin tareas nuevas por un problema de máquina, no de negocio.
        print(f"✗ EL PLANIFICADOR NO PUDO CORRER: {plan['error']}")
        print("  (esto NO es 'no había trabajo pendiente': hoy no se planificó nada)")
        # Solo en corrida real, por el mismo motivo que el aborto de la tanda: un
        # simulacro a mano no puede gastar mensajes. `kind` propio para que no comparta
        # ventana de antirrebote con ningún otro aviso.
        if args.encolar:
            from zero.alerts import notify_owner
            notify_owner(f"ZERO — el planificador no pudo correr: {plan['error']}\n"
                         "Hoy no se encoló ninguna tarea nueva.",
                         kind="planificador-caido")
        return 1

    if not propuestas:
        print("el planificador corrió bien y no propuso tareas (no hay trabajo pendiente)")
        for d in plan.get("descartadas") or []:
            print(f"  descartada: {d}")
        return 0

    # Para distinguir "encolada" de "ya estaba": crear() devuelve la tarea existente en
    # vez de duplicarla, así que un id ya conocido significa que no se encoló nada.
    conocidas = {t["id"] for t in tasks.listar()}
    encoladas = 0
    for t in propuestas:
        problemas = validar(t)
        marca = "✗" if problemas else "→"
        print(f"{marca} [{t.get('workspace')}] {t.get('titulo')}")
        print(f"    archivos: {', '.join(t.get('archivos') or []) or '—'}")
        print(f"    por qué:  {t.get('por_que') or '—'}")
        for p in problemas:
            print(f"    ✗ {p}")
        if problemas:
            continue
        if args.encolar:
            creada = tasks.crear(t["workspace"], t["titulo"], t["prompt"],
                                 archivos=t.get("archivos"),
                                 origen=t.get("origen") or "sistema",
                                 objetivo="; ".join(objetivos)[:200])
            if creada["id"] in conocidas:
                print(f"    = ya estaba en la cola ({creada['id']}, {creada['estado']})")
                continue
            conocidas.add(creada["id"])
            encoladas += 1

    for d in plan.get("descartadas") or []:
        print(f"  (descartada) {d}")

    print()
    print(f"{encoladas} encoladas" if args.encolar
          else f"{len(propuestas)} propuestas (simulacro — usa --encolar para dejarlas en la cola)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
