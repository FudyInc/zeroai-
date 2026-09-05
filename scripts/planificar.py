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
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero import tasks              # noqa: E402
from zero._env import load_env      # noqa: E402

REPO = Path(__file__).resolve().parent.parent
MODELO = os.environ.get("PLAN_MODELO") or "haiku"

# --- La señal de criterio: entrada EXTERNA, no la produce este repo -------------
# `auditoria-criterio.json` lo escribe AUDIT a mano desde otra rama (ver `fuente`
# dentro del propio archivo). Es el hermano de auditoria.json y comparte su forma,
# pero con dos diferencias que mandan sobre cómo se lee:
#
#   · NO se regenera solo. auditar.py sobrescribe el suyo en cada corrida; este se
#     queda ahí hasta que una persona lo cambie. Un hallazgo viejo seguiría entrando
#     todos los días para siempre.
#   · Lo escribe otro proceso, a mano. Puede no existir, estar a medio escribir o
#     traer JSON inválido. Ninguno de esos casos puede tumbar al planificador: se
#     descarta la señal y el día sigue.
#
# La ruta se puede apuntar a otro archivo para probar sin tocar el real.
CRITERIO_PATH = Path(os.environ.get("AUDIT_CRITERIO_PATH")
                     or (REPO / "auditoria-criterio.json"))

# Cuántos días vale un hallazgo con arreglo determinado. Pasado ese plazo se ignora.
#
# Por qué existe: el arreglo "determinado" de hace unos días puede estar hecho hoy, y
# no hay forma de saberlo sin correr su evidencia — que este script no corre a
# propósito (no debe tardar diez minutos ni decidir cuándo se audita). Sin este tope,
# el primer efecto de leer el archivo sería encolar una tarea YA HECHA, que es
# exactamente la enfermedad que el dedup de 0c81b19 vino a cortar. El único hallazgo
# de hoy lo demuestra: pide agregar `industry` a crm._FIELDS, y ese campo ya no
# existe — lo cerró el rename a `activity`.
#
# Por qué acá y no en zero/config.py: config.py es la política del PRODUCTO (tiers,
# gate, cadencia, forecast). Esto es política de la maquinaria autónoma, y meterlo
# ahí obligaría al núcleo a saber de scripts/.
CRITERIO_VIGENCIA_DIAS = 2

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


# Lo mínimo que necesita un hallazgo para poder convertirse en tarea. Sin `evidencia`
# no hay criterio de terminado, y sin `check`/`detalle` no hay qué arreglar.
CAMPOS_DEL_HALLAZGO = ("check", "detalle", "evidencia", "gravedad")


def _leer_informe(ruta: Path) -> Tuple[Optional[Dict[str, Any]], str]:
    """(informe, problema). Nunca lanza: un archivo roto es una señal menos, no una
    corrida perdida."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, ""                      # no existe todavía: no hay señal, y punto
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        return None, f"{ruta.name} ilegible ({e})"
    if not isinstance(datos, dict):
        return None, f"{ruta.name}: se esperaba un objeto JSON, llegó {type(datos).__name__}"
    return datos, ""


def _hallazgos_altos(informe: Dict[str, Any], *, origen: str,
                     vigencia_dias: Optional[float] = None
                     ) -> Tuple[List[str], List[str], List[int]]:
    """(señales, descartadas, índices consumibles) de un informe ya leído.

    Solo gravedad alta: lo medio se reporta para que una persona lo mire, no para
    gastarle una corrida de agente automáticamente. Lo que se descarta se devuelve
    escrito, no en silencio — en el simulacro Diego lo ve y decide.
    """
    senales: List[str] = []
    descartadas: List[str] = []
    consumibles: List[int] = []
    ahora = time.time()
    cuando_informe = informe.get("cuando")

    for i, h in enumerate(informe.get("hallazgos") or []):
        if not isinstance(h, dict):
            descartadas.append(f"{origen}: hallazgo #{i} no es un objeto")
            continue
        faltan = [c for c in CAMPOS_DEL_HALLAZGO if not str(h.get(c) or "").strip()]
        if faltan:
            descartadas.append(f"{origen}: hallazgo #{i} sin {', '.join(faltan)}")
            continue
        if h.get("gravedad") != "alta":
            continue                          # gravedad media: se informa, no se encola
        if h.get("consumido_en"):
            descartadas.append(f"{origen}: [{h['check']}] ya consumido el {h['consumido_en']}")
            continue
        if vigencia_dias is not None:
            cuando = h.get("cuando") or cuando_informe
            try:
                dias = (ahora - float(cuando)) / 86400.0
            except (TypeError, ValueError):
                descartadas.append(f"{origen}: [{h['check']}] sin fecha legible")
                continue
            if dias > vigencia_dias:
                descartadas.append(
                    f"{origen}: [{h['check']}] vencido ({dias:.1f} días; el tope son "
                    f"{vigencia_dias}) — puede estar arreglado; corre su evidencia")
                continue
        linea = f"[{h['check']}] {h['detalle']} — reproducir: {h['evidencia']}"
        extra = h.get("extra") if isinstance(h.get("extra"), dict) else {}
        if extra.get("workspace"):
            linea += f" — workspace sugerido: {extra['workspace']}"
        if extra.get("archivos"):
            linea += f" — archivos: {', '.join(str(a) for a in extra['archivos'])}"
        senales.append(linea)
        consumibles.append(i)
    return senales[:10], descartadas, consumibles[:10]


def hallazgos_de_la_auditoria() -> Tuple[List[str], List[str]]:
    """Lo que `scripts/auditar.py` probó que está roto HOY.

    Es la señal de mayor calidad que tiene el planificador, porque cada línea viene con
    un comando que la reproduce: no es "podría haber un problema en X", es "esto falla,
    corre esto y lo ves". Una tarea nacida de acá tiene criterio de terminado gratis —
    el comando deja de fallar— que es justo lo que le falta a las tareas vagas.

    Se lee del informe en disco y no se corre la auditoría acá: el planificador no debe
    tardar diez minutos ni decidir cuándo se audita. Si el informe no existe todavía, no
    hay señal, y punto. Sin tope de antigüedad: auditar.py lo reescribe entero en cada
    corrida y dia.sh lo corre antes que esto, así que siempre es de hoy.
    """
    informe, problema = _leer_informe(REPO / "auditoria.json")
    if informe is None:
        return [], ([problema] if problema else [])
    senales, descartadas, _ = _hallazgos_altos(informe, origen="auditoría")
    return senales, descartadas


def hallazgos_con_arreglo_determinado() -> Tuple[List[str], List[str], List[int]]:
    """Los hallazgos que AUDIT dejó listos para encolar en `auditoria-criterio.json`.

    Misma forma que el informe de auditar.py y misma lectura, con dos guardas propias
    de ser una entrada externa que no se regenera sola: vigencia (ver
    CRITERIO_VIGENCIA_DIAS) y marca de consumo. Devuelve además los índices de lo que
    se envió, para poder marcarlo cuando la corrida encola de verdad.
    """
    informe, problema = _leer_informe(CRITERIO_PATH)
    if informe is None:
        return [], ([problema] if problema else []), []
    return _hallazgos_altos(informe, origen="criterio",
                            vigencia_dias=CRITERIO_VIGENCIA_DIAS)


def marcar_consumidos(indices: List[int]) -> str:
    """Anota `consumido_en` en los hallazgos que ya se mandaron al planificador.

    El archivo NO se borra ni se mueve: lo escribe AUDIT a mano desde otra rama, y
    borrárselo bajo los pies es la clase de sorpresa que nadie quiere depurar. Se
    reescribe entero (escritura atómica) conservando todo lo demás tal cual.
    """
    if not indices:
        return ""
    informe, problema = _leer_informe(CRITERIO_PATH)
    if informe is None:
        return problema or "no se pudo releer el archivo de criterio"
    hallazgos = informe.get("hallazgos") or []
    sello = datetime.now(timezone.utc).isoformat()
    marcados = 0
    for i in indices:
        if 0 <= i < len(hallazgos) and isinstance(hallazgos[i], dict):
            hallazgos[i]["consumido_en"] = sello
            marcados += 1
    try:
        tmp = CRITERIO_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CRITERIO_PATH)
    except OSError as e:
        return f"no se pudo marcar el consumo en {CRITERIO_PATH.name} ({e})"
    return f"{marcados} hallazgo(s) de criterio marcados como consumidos"


def tareas_atascadas() -> List[str]:
    """Lo que el juez rechazó dos veces: o la tarea estaba mal planteada, o el problema
    es más difícil de lo que parecía. En ambos casos hay que replantearla, no repetirla."""
    return [f"{t['titulo']} — {(t.get('veredicto') or {}).get('motivo_rechazo') or 'sin motivo'}"
            for t in tasks.listar(estado=tasks.ATASCADA)][:10]


def recolectar_senales() -> Dict[str, Any]:
    """Las señales del día, más lo que se descartó al leerlas y los índices del
    archivo de criterio que se enviaron (para marcarlos si la corrida encola)."""
    auditoria, descartes_auditoria = hallazgos_de_la_auditoria()
    criterio, descartes_criterio, consumibles = hallazgos_con_arreglo_determinado()
    return {
        "senales": {
            "hallazgos_de_la_auditoria": auditoria,
            "hallazgos_con_arreglo_determinado": criterio,
            "pendientes_del_roadmap": pendientes_del_roadmap(),
            "marcas_en_el_codigo": marcas_en_el_codigo(),
            "modulos_sin_test_propio": modulos_sin_test(),
            "tareas_atascadas": tareas_atascadas(),
        },
        "descartadas": [*descartes_auditoria, *descartes_criterio],
        "criterio_consumible": consumibles,
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
    recogido = recolectar_senales()
    senales = recogido["senales"]
    consumibles = recogido["criterio_consumible"]

    print(f"objetivos: {len(objetivos)}")
    for o in objetivos:
        print(f"  · {o}")
    print("señales:")
    for k, v in senales.items():
        print(f"  {k}: {len(v)}")
    # Lo que se descartó al leer las señales se muestra siempre: en el simulacro es lo
    # que deja ver que un hallazgo existe pero venció, o que el archivo está roto. Un
    # descarte en silencio se lee igual que "no había nada".
    for d in recogido["descartadas"]:
        print(f"  (descartada) {d}")
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

    # Marcar el consumo solo en corrida real: un simulacro no puede gastar la señal.
    # Se marca lo que se ENVIÓ al planificador, haya propuesto tarea por ello o no —
    # si se dejara sin marcar, mañana volvería a entrar igual y la única defensa sería
    # el dedup de la cola, que es la red de abajo, no la de arriba.
    if args.encolar and consumibles:
        aviso = marcar_consumidos(consumibles)
        if aviso:
            print(f"  {aviso}")

    print()
    print(f"{encoladas} encoladas" if args.encolar
          else f"{len(propuestas)} propuestas (simulacro — usa --encolar para dejarlas en la cola)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
