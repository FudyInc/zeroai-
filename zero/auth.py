"""Agency auth — per-person login, gitignored local users file.

Model: each teammate has their own account (username + password) in a local
JSON file (`AUTH_USERS_PATH`, default "users.json" — same pattern as
`crm.json`/`state.json`: plain data, gitignored, Diego edits it by hand,
never versioned, never self-service). No file (or an empty one) → the app is
open, exactly like the old "no AUTH_PASSWORD set" dev/mock behavior — never a
500, never an ambiguous state.

Tokens are per-user: `"<username>.<exp>.<sig>"`, HMAC-signed with THAT
user's stored password hash as the key (not a single shared secret). That's
the whole revocation mechanism: changing (or removing) one person's password
in the users file invalidates only THEIR outstanding tokens — everyone
else's keep working, because they're signed with a different, unchanged key.
No server-side session table or blocklist needed.

Passwords are never stored in the clear: PBKDF2-HMAC-SHA256 (stdlib —
`hashlib.pbkdf2_hmac`, no bcrypt/argon2 dependency) with a random salt per
user, iteration count stored alongside so it can be bumped later without
invalidating already-hashed passwords.

Replaces the old single-AUTH_PASSWORD model — that env var is no longer read
here. See the top of this repo's docs/roadmap.md if AUTH_PASSWORD is still
referenced anywhere outside this module (Config UI) after this change; that's
a separate, already-flagged follow-up, not something this module depends on.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

TTL = 7 * 24 * 3600   # a week
PBKDF2_ITERATIONS = 260_000   # OWASP 2023 minimum recommendation for PBKDF2-SHA256

# El token es "<username>.<exp>.<sig>", partido por punto — un username con
# puntos rompería ese parseo. Se valida acá, no en el caller.
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _users_path() -> Path:
    return Path(os.environ.get("AUTH_USERS_PATH") or "users.json")


def _load_users() -> Dict[str, Dict[str, Any]]:
    """{username: {"salt": hex, "hash": hex, "iterations": int}}. Missing,
    empty, or unreadable file -> {} (app abierta) — misma disciplina de
    "nunca crashear, degradar a modo dev" que el resto de la capa de
    persistencia (ver zero/persistence.py)."""
    path = _users_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_users(users: Dict[str, Dict[str, Any]]) -> None:
    _users_path().write_text(json.dumps(users, indent=2, ensure_ascii=False), encoding="utf-8")


def auth_enabled() -> bool:
    return bool(_load_users())


def _hash_password(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, iterations).hex()


# --- account management (manual — Diego runs this, no HTTP endpoint) ---------
def add_user(username: str, password: str, iterations: int = PBKDF2_ITERATIONS) -> None:
    """Crea o actualiza una cuenta (mismo username = resetea su password, lo
    que además invalida sus tokens viejos de un saque — nuevo salt+hash).

    Pensado para correrse una vez desde una consola, no un endpoint HTTP: dar
    de alta gente es una acción manual de Diego, no self-service.
        python3 -c "from zero.auth import add_user; add_user('lucas', 'lo-que-sea')"
    """
    username = (username or "").strip()
    if not _USERNAME_RE.match(username):
        raise ValueError(
            f"username inválido: {username!r} — solo letras, números, guion y guion bajo"
        )
    if not password:
        raise ValueError("password vacío")
    users = _load_users()
    salt = secrets.token_bytes(16)
    users[username] = {
        "salt": salt.hex(),
        "hash": _hash_password(password, salt, iterations),
        "iterations": iterations,
    }
    _save_users(users)


def remove_user(username: str) -> bool:
    """Da de baja una cuenta. True si existía. Sus tokens vigentes quedan
    inválidos de inmediato — la firma se verifica contra el hash guardado,
    que deja de existir."""
    users = _load_users()
    if username not in users:
        return False
    del users[username]
    _save_users(users)
    return True


def list_users() -> list:
    """Nombres de usuario dados de alta — nunca expone salt/hash."""
    return sorted(_load_users())


# --- login/session -------------------------------------------------------------
def verify_password(username: str, password: str) -> bool:
    rec = _load_users().get((username or "").strip())
    if not rec:
        return False
    try:
        salt = bytes.fromhex(rec.get("salt", ""))
    except ValueError:
        return False
    iterations = int(rec.get("iterations") or PBKDF2_ITERATIONS)
    expected = _hash_password(password, salt, iterations)
    return hmac.compare_digest(expected, rec.get("hash", ""))


def _user_secret(username: str) -> Optional[bytes]:
    rec = _load_users().get((username or "").strip())
    if not rec or not rec.get("hash"):
        return None
    try:
        return bytes.fromhex(rec["hash"])
    except ValueError:
        return None


def make_token(username: str, ttl: int = TTL) -> Optional[str]:
    """None si el usuario no existe (nada con qué firmar) — en la práctica
    `login()` ya llamó a verify_password antes, así que esto solo pasaría en
    una carrera rarísima con remove_user entremedio."""
    username = (username or "").strip()
    secret = _user_secret(username)
    if secret is None:
        return None
    exp = str(int(time.time()) + ttl)
    sig = hmac.new(secret, f"{username}.{exp}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{username}.{exp}.{sig}"


def token_username(token: str) -> Optional[str]:
    """Username del token si es válido (firma + no vencido); None si no.
    `valid_token` es el atajo booleano para el gate; esto es para quien
    necesite saber QUIÉN es (ej. /api/auth/status)."""
    try:
        username, exp, sig = (token or "").split(".", 2)
    except ValueError:
        return None
    secret = _user_secret(username)
    if secret is None:
        return None
    good = hmac.new(secret, f"{username}.{exp}".encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return None
    try:
        if int(exp) <= time.time():
            return None
    except ValueError:
        return None
    return username


def valid_token(token: str) -> bool:
    return token_username(token) is not None
