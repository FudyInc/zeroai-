"""Respaldo diario y cifrado de los datos de producción, fuera del PC.

Por qué existe: `state.json`, `crm.json`, la bandeja de WhatsApp (sqlite) y el
`.env` vivían solo en el disco de un PC. Si el disco muere, se pierde todo — la
auditoría del 2026-11-27 lo encontró sin respaldo externo.

Qué hace: arma un .tar.gz con lo que lista `zero.config` (RESPALDO_*), más las
rutas de RESPALDO_EXTRA (código o estado que aún vive fuera del repo); lo cifra
con openssl (AES-256-CBC, PBKDF2, sal) usando la clave de RESPALDO_CLAVE_ARCHIVO;
lo VERIFICA descifrándolo y leyendo el tar; y recién ahí lo deja en
RESPALDO_DESTINO (una carpeta dedicada y sincronizada con la nube, p.ej.
OneDrive), conservando los últimos RESPALDO_RETENER. Si algo falla, avisa al
dueño por WhatsApp y sale con error: un respaldo que falla en silencio es peor
que no tener respaldo.

LA CLAVE: sin ella el respaldo es ilegible. Vive en el mismo disco que se quiere
proteger, así que guarda una COPIA fuera del PC y fuera de OneDrive (gestor de
contraseñas). Crearla:
    mkdir -p ~/.config/zero-respaldo && openssl rand -base64 48 > ~/.config/zero-respaldo/clave \
        && chmod 600 ~/.config/zero-respaldo/clave
openssl `-pass file:` lee solo la PRIMERA línea de ese archivo.

Restaurar (a una carpeta temporal; revisar antes de copiar sobre producción):
    mkdir /tmp/restaurado && openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
        -pass file:$HOME/.config/zero-respaldo/clave -in zeroai-AAAAMMDD-HHMM.tar.gz.enc \
        | tar -xz -C /tmp/restaurado

Uso: python3 scripts/respaldo_diario.py [--raiz /home/diego/zeroai]
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zero._env import load_env  # noqa: E402
from zero.config import (RESPALDO_ARCHIVOS, RESPALDO_CLAVE_MIN_BYTES,  # noqa: E402
                         RESPALDO_DIRECTORIOS, RESPALDO_PBKDF2_ITER, RESPALDO_RETENER,
                         RESPALDO_SQLITE, RESPALDO_SQLITE_TIMEOUT_S)

PREFIJO, SUFIJO = "zeroai-", ".tar.gz.enc"
NOMBRE_VALIDO = re.compile(r"^zeroai-\d{8}-\d{4}\.tar\.gz\.enc$")
PARCIAL = re.compile(r"^\.zeroai-\d{8}-\d{4}\.tar\.gz\.enc\.parcial$")


class RespaldoError(RuntimeError):
    pass


def _copia_sqlite(origen: Path) -> bytes:
    """Copia consistente de una sqlite en uso (API de backup), sin tocar disco."""
    src = sqlite3.connect(f"{origen.resolve().as_uri()}?mode=ro", uri=True,
                          timeout=RESPALDO_SQLITE_TIMEOUT_S)
    try:
        dst = sqlite3.connect(":memory:")
        try:
            src.backup(dst)
            return dst.serialize()
        finally:
            dst.close()
    finally:
        src.close()


def _agregar_bytes(tar: tarfile.TarFile, nombre: str, datos: bytes) -> None:
    info = tarfile.TarInfo(nombre)
    info.size, info.mtime, info.mode = len(datos), int(time.time()), 0o600
    tar.addfile(info, io.BytesIO(datos))


def _agregar_archivo(tar: tarfile.TarFile, ruta: Path, nombre: str) -> bool:
    """Lee el archivo entero a memoria y lo agrega: si cambia mientras se lee,
    el tar no queda cortado (sigue el symlink; uno roto se omite)."""
    try:
        datos = ruta.read_bytes()
    except FileNotFoundError:
        return False
    _agregar_bytes(tar, nombre, datos)
    return True


def _agregar_arbol(tar: tarfile.TarFile, raiz: Path, prefijo: str) -> int:
    n = 0
    for ruta in sorted(raiz.rglob("*")):
        if ruta.is_file():
            n += _agregar_archivo(tar, ruta, f"{prefijo}/{ruta.relative_to(raiz).as_posix()}")
    return n


def armar_tar(raiz: Path, extra: List[Path], sqlites: List[Path]) -> Tuple[bytes, List[str]]:
    """Devuelve (tar.gz en bytes, lista de lo incluido). Lo que no existe se omite."""
    incluidos: List[str] = []
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for nombre in RESPALDO_ARCHIVOS:
            if _agregar_archivo(tar, raiz / nombre, f"repo/{nombre}"):
                incluidos.append(nombre)
        for nombre in RESPALDO_DIRECTORIOS:
            if (raiz / nombre).is_dir() and _agregar_arbol(tar, raiz / nombre, f"repo/{nombre}"):
                incluidos.append(nombre + "/")
        for p in sqlites:
            if p.is_file():
                _agregar_bytes(tar, f"repo/{p.name}", _copia_sqlite(p))
                incluidos.append(p.name)
        for p in extra:
            destino = f"extra/{p.as_posix().lstrip('/')}"
            if p.is_dir() and _agregar_arbol(tar, p, destino):
                incluidos.append(str(p))
            elif p.is_file() and _agregar_archivo(tar, p, destino):
                incluidos.append(str(p))
    if not incluidos:
        raise RespaldoError(f"no se encontró nada que respaldar en {raiz}")
    return buf.getvalue(), incluidos


def validar_clave(clave: Path) -> None:
    if not clave.is_file():
        raise RespaldoError(f"falta la clave de cifrado: {clave}")
    lineas = clave.read_bytes().splitlines()
    if len(lineas[0].strip() if lineas else b"") < RESPALDO_CLAVE_MIN_BYTES:
        raise RespaldoError(f"la clave de cifrado es demasiado corta (mínimo "
                            f"{RESPALDO_CLAVE_MIN_BYTES} bytes en la primera línea): {clave}")
    if clave.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise RespaldoError(f"la clave es legible por otros usuarios; corre: chmod 600 {clave}")


def _openssl(args: List[str], entrada: Optional[bytes] = None) -> bytes:
    r = subprocess.run(["openssl", "enc", *args, "-aes-256-cbc", "-pbkdf2",
                        "-iter", str(RESPALDO_PBKDF2_ITER)],
                       input=entrada, capture_output=True)
    if r.returncode != 0:
        raise RespaldoError("openssl falló: " + r.stderr.decode(errors="replace")[:200])
    return r.stdout


def cifrar(datos: bytes, clave: Path, salida: Path) -> None:
    validar_clave(clave)
    _openssl(["-salt", "-pass", f"file:{clave}", "-out", str(salida)], datos)


def verificar(archivo: Path, clave: Path, esperados: int) -> None:
    """Descifra y lee el tar completo: un archivo con nombre válido debe restaurarse."""
    plano = _openssl(["-d", "-pass", f"file:{clave}", "-in", str(archivo)])
    try:
        with tarfile.open(fileobj=io.BytesIO(plano), mode="r:gz") as tar:
            miembros = tar.getmembers()
            for m in miembros:
                if m.isfile():
                    tar.extractfile(m).read()
    except (tarfile.TarError, OSError, EOFError) as e:
        raise RespaldoError(f"el respaldo cifrado no se pudo leer de vuelta: {e}") from e
    if len(miembros) < esperados:
        raise RespaldoError("el respaldo verificado tiene menos archivos de los esperados")


def podar(destino: Path, retener: int, ahora: float) -> Tuple[List[str], List[str]]:
    """Borra los respaldos sobrantes (solo nombres exactos de este script) y los
    .parcial huérfanos de más de un día. Nunca lanza: devuelve (borrados, errores)."""
    borrados, errores = [], []
    propios = sorted(p for p in destino.iterdir() if p.is_file() and NOMBRE_VALIDO.match(p.name))
    huerfanos = [p for p in destino.iterdir()
                 if p.is_file() and PARCIAL.match(p.name) and ahora - p.stat().st_mtime > 86400]
    for p in (propios[:-retener] if retener > 0 else []) + huerfanos:
        try:
            p.unlink()
            borrados.append(p.name)
        except OSError as e:
            errores.append(f"{p.name}: {e}")
    return borrados, errores


def respaldar(raiz: Path, destino: Path, clave: Path, extra: List[Path],
              retener: int = RESPALDO_RETENER, ahora: Optional[float] = None,
              sqlites: Optional[List[Path]] = None) -> dict:
    ahora = ahora or time.time()
    if not destino.is_dir():
        raise RespaldoError(f"el destino no existe o no es carpeta: {destino}")
    validar_clave(clave)
    if sqlites is None:
        sqlites = [raiz / n for n in RESPALDO_SQLITE]
    datos, incluidos = armar_tar(raiz, extra, sqlites)
    sello = time.strftime("%Y%m%d-%H%M", time.localtime(ahora))
    final = destino / f"{PREFIJO}{sello}{SUFIJO}"
    parcial = destino / f".{final.name}.parcial"
    try:
        cifrar(datos, clave, parcial)
        with open(parcial, "rb") as f:
            os.fsync(f.fileno())
        verificar(parcial, clave, esperados=1)
        os.replace(parcial, final)      # nunca queda un respaldo a medias con nombre válido
    finally:
        if parcial.exists():
            parcial.unlink()
    borrados, errores_poda = podar(destino, retener, ahora)
    return {"archivo": str(final), "bytes": final.stat().st_size, "incluidos": incluidos,
            "podados": borrados, "errores_poda": errores_poda}


def _avisar(msg: str) -> None:
    print(msg, file=sys.stderr)
    try:
        from zero.alerts import notify_owner
        notify_owner(msg, kind="respaldo")
    except Exception:  # noqa: BLE001 — un aviso que falla no tumba nada
        pass


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--raiz", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args(argv)
    raiz = Path(args.raiz).resolve()
    load_env(str(raiz / ".env"))
    destino = os.environ.get("RESPALDO_DESTINO", "").strip()
    clave = os.environ.get("RESPALDO_CLAVE_ARCHIVO", "").strip() or \
        str(Path.home() / ".config/zero-respaldo/clave")
    extra = [Path(p).expanduser() for p in os.environ.get("RESPALDO_EXTRA", "").split(":") if p.strip()]
    sqlites = [raiz / n for n in RESPALDO_SQLITE]
    evento = os.environ.get("WHATSAPP_WEB_EVENT_DB", "").strip()
    if evento:
        sqlites = [Path(evento) if Path(evento).is_absolute() else raiz / evento]
    try:
        if not destino:
            raise RespaldoError("RESPALDO_DESTINO no está definido en el .env")
        r = respaldar(raiz, Path(destino).expanduser(), Path(clave).expanduser(), extra,
                      sqlites=sqlites)
    except Exception as e:  # noqa: BLE001 — cualquier falla se avisa
        _avisar(f"⚠️ Respaldo diario de ZeroAI FALLÓ: {e}")
        return 1
    print(f"respaldo ok: {r['archivo']} ({r['bytes']} B) · incluye: {', '.join(r['incluidos'])}"
          + (f" · podados: {', '.join(r['podados'])}" if r["podados"] else ""))
    if r["errores_poda"]:
        _avisar("⚠️ Respaldo de ZeroAI OK, pero no se pudieron borrar respaldos viejos: "
                + "; ".join(r["errores_poda"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
