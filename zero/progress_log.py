"""Registro versionado de decisiones y avances publicado en el dashboard.

Solo lectura. Las entradas se editan en docs/registro-avances.json junto al cambio
que describen, para que el historial viaje con el código y no dependa de state.json.
"""
from __future__ import annotations

import json
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "docs" / "registro-avances.json"


def list_entries(path: Path = REGISTRY_PATH) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("entries"), list):
        raise ValueError("registro de avances inválido")
    seen = set()
    entries = []
    for entry in data["entries"]:
        if not isinstance(entry, dict) or not all(
            isinstance(entry.get(key), str) and entry[key].strip()
            for key in ("id", "date", "type", "title", "origin", "summary", "status", "scope", "evidence")
        ):
            raise ValueError("entrada de avances incompleta")
        if entry["id"] in seen:
            raise ValueError("identificador de avance duplicado")
        seen.add(entry["id"])
        entries.append(entry)
    return sorted(entries, key=lambda e: (e["date"], e["id"]), reverse=True)
