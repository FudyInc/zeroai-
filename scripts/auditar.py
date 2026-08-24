#!/usr/bin/env python3
"""Auditoría diaria del repo: comprobaciones que o pasan o fallan, sin opinión.

    python3 scripts/auditar.py              # audita y reporta
    python3 scripts/auditar.py --json       # solo el JSON (para encadenar)

## Por qué este auditor y no uno con modelo

La tentación es pedirle a un modelo "revisa el repo y dime qué está mal". No hacerlo:
un modelo al que se le pide encontrar problemas **siempre encuentra alguno**, porque esa
es la tarea que recibió. Produce hallazgos plausibles y bien escritos sobre cosas que no
están rotas, la cola se llena de trabajo inventado, y cada tarea inventada cuesta una
corrida de agente y deja código que igual hay que mantener después. Es exactamente lo que
`prompts/planificador.md` prohíbe en su regla 6, pero por la puerta de atrás.

Acá cada hallazgo es un hecho reproducible: algo que hoy falla y que se puede volver a
correr para comprobarlo. Por eso todo hallazgo trae `evidencia` — el comando que lo
demuestra. Si no se puede escribir ese comando, no es un hallazgo: es una opinión, y no
entra.

Consecuencia práctica: esto no cuesta tokens y corre en segundos. El modelo se gasta
después, en arreglar lo que el auditor ya probó que está roto.

## Lo que NO hace

No juzga estilo, arquitectura ni "buenas prácticas". No propone refactors. No mide
cobertura como si fuera una nota. Eso es trabajo de una persona con criterio, y meterlo
acá convierte la cola en una lista de tareas de limpieza que nadie pidió.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REPO = Path(__file__).resolve().parent.parent
SALIDA = REPO / "auditoria.json"

ALTA, MEDIA = "alta", "media"


def _hallazgo(check: str, gravedad: str, detalle: str, evidencia: str,
              extra: Any = None) -> Dict[str, Any]:
    return {"check": check, "gravedad": gravedad, "detalle": detalle,
            "evidencia": evidencia, "extra": extra}


def _corre(cmd: List[str], timeout: int = 900, cwd: Path = REPO):
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout)
        return r.returncode, ((r.stdout or "") + (r.stderr or ""))
    except subprocess.TimeoutExpired:
        return 124, f"pasó de {timeout}s"
    except FileNotFoundError:
        return 127, f"no existe el comando: {cmd[0]}"


# --- Comprobaciones -----------------------------------------------------------------
def suite_de_tests() -> List[Dict[str, Any]]:
    """La red de seguridad del núcleo. Si está roja, nada más importa."""
    code, salida = _corre(["python3", "-m", "unittest", "discover", "-s", "tests", "-t", "."])
    if code == 0:
        return []
    return [_hallazgo("tests", ALTA, "la suite del núcleo está en rojo",
                      "python3 -m unittest discover -s tests -t .", salida[-1500:])]


def imports_del_nucleo() -> List[Dict[str, Any]]:
    """Cada módulo de `zero/` tiene que poder importarse solo.

    Un módulo que solo importa cuando otro lo importó antes está roto y no se nota:
    la suite lo carga en un orden que funciona, y falla el día que alguien lo usa
    directo desde un script.
    """
    fallos = []
    for modulo in sorted((REPO / "zero").glob("*.py")):
        if modulo.stem.startswith("_") or modulo.stem == "__init__":
            continue
        code, salida = _corre(["python3", "-c", f"import zero.{modulo.stem}"], timeout=60)
        if code != 0:
            fallos.append(_hallazgo(
                "imports", ALTA, f"zero/{modulo.name} no se puede importar solo",
                f"python3 -c 'import zero.{modulo.stem}'", salida[-600:]))
    return fallos


def pipeline_en_mock() -> List[Dict[str, Any]]:
    """El camino feliz completo, sin red y sin key. Es el humo del producto entero."""
    code, salida = _corre(["python3", "main.py", "--client", "auditoria",
                           "--tier", "GROWTH", "--query", "fintech LATAM"], timeout=300)
    if code == 0:
        return []
    return [_hallazgo("pipeline_mock", ALTA, "el pipeline en mock no termina bien",
                      'python3 main.py --client auditoria --tier GROWTH --query "fintech LATAM"',
                      salida[-1500:])]


_RUTA_RE = re.compile(r'@app\.(get|post|put|patch|delete)\(\s*["\']([^"\']+)["\']', re.I)


def rutas_duplicadas() -> List[Dict[str, Any]]:
    """Dos handlers para el mismo (método, ruta) en `api.py`.

    FastAPI no se queja: registra ambos y gana el primero, callado. El segundo queda
    como código muerto que alguien mantiene creyendo que corre. Ya pasó en este repo —
    dos `/api/vendors` distintos que llegaron por ramas de larga vida— y se descubrió
    por casualidad, no por una prueba.
    """
    texto = (REPO / "api.py").read_text(encoding="utf-8")
    vistas: Dict[tuple, int] = {}
    dupes = []
    for m in _RUTA_RE.finditer(texto):
        clave = (m.group(1).lower(), m.group(2))
        linea = texto.count("\n", 0, m.start()) + 1
        if clave in vistas:
            dupes.append(_hallazgo(
                "rutas_duplicadas", ALTA,
                f"{clave[0].upper()} {clave[1]} está declarada dos veces en api.py "
                f"(líneas {vistas[clave]} y {linea}); gana la primera y la segunda es código muerto",
                f"grep -n '\"{clave[1]}\"' api.py"))
        else:
            vistas[clave] = linea
    return dupes


def ficha_se_trunca() -> List[Dict[str, Any]]:
    """La ficha viaja cortada a 4000 caracteres y el corte es silencioso.

    Lo que se pase de esa marca simplemente no llega al modelo: el agente responde sin
    saber lo que se escribió al final del archivo, y no hay ningún error que lo avise.
    """
    ruta = REPO / "docs" / "ficha-zeroai.md"
    texto = ruta.read_text(encoding="utf-8")
    i, f = texto.find("<!-- INICIO FICHA"), texto.find("<!-- FIN FICHA")
    if i == -1 or f == -1:
        return [_hallazgo("ficha", MEDIA, "docs/ficha-zeroai.md perdió sus marcadores "
                          "INICIO/FIN FICHA; ya no se puede medir qué se carga",
                          "grep -n 'FICHA' docs/ficha-zeroai.md")]
    cuerpo = texto[texto.find("\n", i) + 1:f].strip()
    if len(cuerpo) > 4000:
        return [_hallazgo("ficha", ALTA,
                          f"la ficha tiene {len(cuerpo)} caracteres y se corta en 4000: "
                          f"los últimos {len(cuerpo) - 4000} nunca llegan al agente",
                          "python3 scripts/auditar.py")]
    return []


DATOS = ("state.json", "crm.json", "users.json", "finance.json", "tareas.json")


def datos_locales_corruptos() -> List[Dict[str, Any]]:
    """Los archivos de datos locales tienen que ser JSON legible.

    Si uno se corrompe, el código está escrito para avisar en vez de borrarlo — pero
    ese aviso solo aparece cuando alguien corre la parte que lo usa. Acá se nota al día
    siguiente.
    """
    fallos = []
    for nombre in DATOS:
        ruta = REPO / nombre
        if not ruta.exists():
            continue
        try:
            json.loads(ruta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            fallos.append(_hallazgo("datos", ALTA, f"{nombre} no es JSON válido: {e}",
                                    f"python3 -c \"import json;json.load(open('{nombre}'))\""))
    return fallos


# Patrones de credencial. Se reporta ARCHIVO Y LÍNEA, nunca el valor: un auditor que
# imprime la clave que encontró la copia al log, al correo de alerta y al historial.
_SECRETOS = (
    ("clave de Anthropic", re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")),
    ("token de OpenAI", re.compile(r"\bsk-[A-Za-z0-9]{32,}")),
    ("token de Meta/WhatsApp", re.compile(r"\bEAA[A-Za-z0-9]{60,}")),
    ("service key de Supabase", re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.")),
    # OJO: el patrón de arriba pesca cualquier JWT, y la anon key de Supabase ES un JWT
    # que va público en el frontend a propósito. `_jwt_es_publico` la distingue leyendo
    # el claim `role`, en vez de mantener una lista de archivos perdonados: una lista así
    # perdona el archivo entero y el día que ahí aparezca una service_role, nadie avisa.
    ("token de GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}")),
)


def _jwt_es_publico(token: str) -> bool:
    """¿Es un JWT que está bien que sea público? Se decide por el claim `role`.

    La anon/publishable key de Supabase es un JWT firmado que el navegador necesita
    tener: exponerla es el diseño, y lo que la hace inofensiva es que su rol es `anon`
    y las políticas RLS mandan. La `service_role`, en cambio, se salta RLS entera: la
    misma forma, consecuencias opuestas. Por eso se lee el rol y no el nombre de la
    variable ni el comentario de al lado, que es lo que uno querría creer.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        rol = json.loads(base64.urlsafe_b64decode(payload)).get("role")
    except Exception:      # noqa: BLE001 — un JWT ilegible no se declara inofensivo
        return False
    return rol == "anon"


def secretos_versionados() -> List[Dict[str, Any]]:
    """Una credencial dentro de un archivo que git rastrea.

    `.env` está ignorado, pero una key pegada a un script o a un test sí se sube — y una
    vez subida hay que rotarla, no basta con borrarla en el commit siguiente.
    """
    code, salida = _corre(["git", "ls-files"], timeout=60)
    if code != 0:
        return []
    fallos = []
    for archivo in salida.splitlines():
        ruta = REPO / archivo
        if not ruta.is_file() or ruta.stat().st_size > 2_000_000:
            continue
        try:
            texto = ruta.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for nombre, patron in _SECRETOS:
            m = patron.search(texto)
            if m:
                if m.group(0).startswith("eyJ") and _jwt_es_publico(
                        texto[m.start():m.start() + 2000].split("'")[0].split('"')[0]):
                    continue
                linea = texto.count("\n", 0, m.start()) + 1
                fallos.append(_hallazgo(
                    "secretos", ALTA,
                    f"posible {nombre} versionada en {archivo}:{linea} "
                    f"(si es real, hay que ROTARLA: borrarla del commit no la invalida)",
                    f"sed -n '{linea}p' {archivo}"))
    return fallos


def build_del_dashboard() -> List[Dict[str, Any]]:
    """El dashboard tiene que compilar. Ningún test de Python toca una línea de JSX."""
    if not (REPO / "frontend" / "node_modules").is_dir():
        return []          # sin dependencias no se puede afirmar nada, ni bueno ni malo
    code, salida = _corre(["npm", "run", "build"], timeout=600, cwd=REPO / "frontend")
    if code == 0:
        return []
    return [_hallazgo("build_dashboard", ALTA, "el dashboard no compila",
                      "cd frontend && npm run build", salida[-1500:])]


CHECKS = (
    ("suite de tests", suite_de_tests),
    ("imports del núcleo", imports_del_nucleo),
    ("pipeline en mock", pipeline_en_mock),
    ("rutas duplicadas en api.py", rutas_duplicadas),
    ("límite de la ficha", ficha_se_trunca),
    ("datos locales", datos_locales_corruptos),
    ("secretos versionados", secretos_versionados),
    ("build del dashboard", build_del_dashboard),
)


def auditar() -> Dict[str, Any]:
    hallazgos, corridos = [], []
    for nombre, fn in CHECKS:
        t0 = time.time()
        try:
            encontrados = fn()
        except Exception as e:               # noqa: BLE001
            # Un check que revienta es un check que no comprobó nada. Decirlo, no
            # tragárselo: un auditor que falla en silencio da el peor de los verdes.
            encontrados = [_hallazgo(nombre, MEDIA,
                                     f"la comprobación «{nombre}» no pudo correr: {e}",
                                     "python3 scripts/auditar.py")]
        hallazgos.extend(encontrados)
        corridos.append({"check": nombre, "hallazgos": len(encontrados),
                         "segundos": round(time.time() - t0, 1)})
    return {"cuando": time.time(), "checks": corridos, "hallazgos": hallazgos}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="solo el JSON, para encadenar")
    args = ap.parse_args()

    informe = auditar()
    SALIDA.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(informe, ensure_ascii=False))
        return 0

    for c in informe["checks"]:
        marca = "✗" if c["hallazgos"] else "·"
        print(f"  {marca} {c['check']:32} {c['segundos']:>6.1f}s"
              + (f"  → {c['hallazgos']}" if c["hallazgos"] else ""))
    print()
    altas = [h for h in informe["hallazgos"] if h["gravedad"] == ALTA]
    if not informe["hallazgos"]:
        print("sin hallazgos")
        return 0
    for h in informe["hallazgos"]:
        print(f"[{h['gravedad']}] {h['detalle']}")
        print(f"    reproducir: {h['evidencia']}")
    print(f"\n{len(informe['hallazgos'])} hallazgos ({len(altas)} de gravedad alta) → {SALIDA.name}")
    return 1 if altas else 0


if __name__ == "__main__":
    raise SystemExit(main())
