"""Respaldo diario y cifrado de los datos de producción, fuera del PC.

Por qué existe: `state.json`, `crm.json`, la bandeja de WhatsApp (sqlite) y el
`.env` vivían solo en el disco de un PC. Si el disco muere, se pierde todo — la
auditoría del 2026-11-27 lo encontró sin respaldo externo.

Qué hace: arma un .tar.gz con lo que lista `zero.config` (RESPALDO_*), más las
rutas de RESPALDO_EXTRA; lo cifra con openssl (AES-256-CBC, PBKDF2, sal) usando
la clave de RESPALDO_CLAVE_ARCHIVO; lo deja en RESPALDO_DESTINO (una carpeta
sincronizada con la nube, p.ej. OneDrive) y conserva los últimos
RESPALDO_RETENER. Si algo falla, avisa al dueño por WhatsApp y sale con error:
un respaldo que falla en silencio es peor que no tener respaldo.

Restaurar:
    openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
        -pass file:$RESPALDO_CLAVE_ARCHIVO -in zeroai-AAAAMMDD-HHMM.tar.gz.enc \
        | tar -xz -C /ruta/destino

Uso: python3 scripts/respaldo_diario.py [--raiz /home/diego/zeroai]
"""
from __future__ import annotations

import argparse
import io
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zero._env import load_env  # noqa: E402
from zero.config import (RESPALDO_ARCHIVOS, RESPALDO_DIRECTORIOS,  # noqa: E402
                         RESPALDO_PBKDF2_ITER, RESPALDO_RETENER, RESPALDO_SQLITE)

PREFIJO = "zeroai-"
SUFIJO = ".tar.gz.enc"


class RespaldoError(RuntimeError):
    pass


def _copia_sqlite(origen: Path) -> bytes:
    """Copia consistente de una sqlite en uso (API de backup), como bytes."""
    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp) / origen.name
        src = sqlite3.connect(f"file:{origen}?mode=ro", uri=True)
        try:
            dst = sqlite3.connect(destino)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        return destino.read_bytes()


def armar_tar(raiz: Path, extra: List[Path]) -> tuple[bytes, List[str]]:
    """Devuelve (tar.gz en bytes, lista de lo incluido). Lo que no existe se omite."""
    incluidos: List[str] = []
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for nombre in RESPALDO_ARCHIVOS:
            p = raiz / nombre
            if p.is_file():
                tar.add(p, arcname=f"repo/{nombre}")
                incluidos.append(nombre)
        for nombre in RESPALDO_DIRECTORIOS:
            p = raiz / nombre
            if p.is_dir():
                tar.add(p, arcname=f"repo/{nombre}")
                incluidos.append(nombre + "/")
        for nombre in RESPALDO_SQLITE:
            p = raiz / nombre
            if p.is_file():
                datos = _copia_sqlite(p)
                info = tarfile.TarInfo(f"repo/{nombre}")
                info.size, info.mtime, info.mode = len(datos), int(time.time()), 0o600
                tar.addfile(info, io.BytesIO(datos))
                incluidos.append(nombre)
        for p in extra:
            if p.exists():
                tar.add(p, arcname=f"extra/{p.as_posix().lstrip('/')}")
                incluidos.append(str(p))
    if not incluidos:
        raise RespaldoError(f"no se encontró nada que respaldar en {raiz}")
    return buf.getvalue(), incluidos


def cifrar(datos: bytes, clave: Path, salida: Path) -> None:
    if not clave.is_file():
        raise RespaldoError(f"falta la clave de cifrado: {clave}")
    r = subprocess.run(
        ["openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2",
         "-iter", str(RESPALDO_PBKDF2_ITER), "-pass", f"file:{clave}", "-out", str(salida)],
        input=datos, capture_output=True)
    if r.returncode != 0:
        raise RespaldoError("openssl falló: " + r.stderr.decode(errors="replace")[:200])


def podar(destino: Path, retener: int) -> List[str]:
    archivos = sorted(p for p in destino.glob(PREFIJO + "*" + SUFIJO) if p.is_file())
    sobran = archivos[:-retener] if retener > 0 else []
    for p in sobran:
        p.unlink()
    return [p.name for p in sobran]


def respaldar(raiz: Path, destino: Path, clave: Path, extra: List[Path],
              retener: int = RESPALDO_RETENER, ahora: Optional[float] = None) -> dict:
    if not destino.is_dir():
        raise RespaldoError(f"el destino no existe o no es carpeta: {destino}")
    datos, incluidos = armar_tar(raiz, extra)
    sello = time.strftime("%Y%m%d-%H%M", time.localtime(ahora or time.time()))
    final = destino / f"{PREFIJO}{sello}{SUFIJO}"
    parcial = destino / f".{final.name}.parcial"
    try:
        cifrar(datos, clave, parcial)
        os.replace(parcial, final)          # nunca queda un respaldo a medias con nombre válido
    finally:
        if parcial.exists():
            parcial.unlink()
    borrados = podar(destino, retener)
    return {"archivo": str(final), "bytes": final.stat().st_size,
            "incluidos": incluidos, "podados": borrados}


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
    try:
        if not destino:
            raise RespaldoError("RESPALDO_DESTINO no está definido en el .env")
        r = respaldar(raiz, Path(destino).expanduser(), Path(clave).expanduser(), extra)
    except Exception as e:  # noqa: BLE001 — cualquier falla se avisa
        msg = f"⚠️ Respaldo diario de ZeroAI FALLÓ: {e}"
        print(msg, file=sys.stderr)
        try:
            from zero.alerts import notify_owner
            notify_owner(msg, kind="respaldo")
        except Exception:  # noqa: BLE001
            pass
        return 1
    print(f"respaldo ok: {r['archivo']} ({r['bytes']} B) · incluye: {', '.join(r['incluidos'])}"
          + (f" · podados: {', '.join(r['podados'])}" if r["podados"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
