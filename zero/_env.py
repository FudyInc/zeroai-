"""Tiny .env loader (stdlib) — so secrets live in a gitignored .env, set once.

Reads KEY=VALUE lines from the project's .env into os.environ, without clobbering
anything already set in the shell. No dependency on python-dotenv.
"""
from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | None = None) -> None:
    p = Path(path) if path else Path(__file__).resolve().parents[1] / ".env"
    if not p.exists():
        return
    for raw in p.read_text("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and val:                      # ignore empty placeholders
            os.environ.setdefault(key, val)  # shell value wins if already set


def set_env(key: str, value: str, path: str | None = None) -> None:
    """Persist KEY=value into .env (update in place or append) and set it live."""
    p = Path(path) if path else Path(__file__).resolve().parents[1] / ".env"
    lines = p.read_text("utf-8").splitlines() if p.exists() else []
    out, found = [], False
    for line in lines:
        if line.strip().split("=", 1)[0].strip() == key:
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    p.write_text("\n".join(out) + "\n", "utf-8")
    os.environ[key] = value
