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

--- Supabase Auth (Google login) + roles, 2026-07-16 ---------------------------
Second, PREFERRED login path on top of the per-person model above (added, not
replacing it — the per-person model stays as a transitional fallback, see
`token_identity()`). Diego turned on Google as a provider in Supabase Auth's
own panel (a manual step, already done); the frontend does the OAuth dance
with Supabase directly and hands this backend the resulting JWT.

Roles live in the token's `app_metadata` (never `user_metadata` — that one a
user can edit about themselves via the Supabase client API, so it can't be
trusted for authorization). Diego assigns `app_metadata.role` by hand from the
Supabase panel per person — no admin endpoint here for that yet. A JWT that
verifies but carries no role is authenticated with nobody home: fail closed,
never treated as "sees everything" (see `token_identity()`'s `role: None`
case, and `api.py::auth_guard`, which turns that into a 403, not a free pass).

**Dos algoritmos de firma soportados** (encontrado en vivo, 2026-07-17 —
Diego se logueaba de verdad con Google, Supabase lo confirmaba, pero este
backend igual lo rechazaba y lo mandaba de vuelta al login):
- `HS256` — el modelo original de esta sección, firma con `SUPABASE_JWT_SECRET`
  (Settings → API → JWT Secret), verificable 100% stdlib (hmac).
- `ES256` — lo que Supabase usa de VERDAD para los tokens que emite Google
  Auth en proyectos nuevos (confirmado vía el endpoint público
  `<SUPABASE_URL>/auth/v1/.well-known/jwks.json` de este proyecto: trae una
  clave `"kty":"EC","crv":"P-256"`, nunca HS256). `SUPABASE_JWT_SECRET`
  configurado no alcanza para estos tokens — ninguna cantidad de secreto
  compartido verifica una firma asimétrica.

Verificar ECDSA (P-256) no es viable en stdlib puro — Python no trae
primitivas de curva elíptica utilizables para esto. Única excepción
documentada a la disciplina "stdlib only" de zero/*.py: se suma `cryptography`
(ver requirements.txt) SOLO para este verify, nada más del módulo la usa.
Las claves públicas se traen del endpoint JWKS de Supabase (público, no es un
secreto) y se cachean en memoria (`_JWKS_CACHE`, 1h) — a diferencia de HS256,
esto sí puede hacer una llamada de red, pero como mucho una vez por hora, no
por request; nunca lanza (red caída → ese token no verifica hasta el próximo
refresh, no un crash).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

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
    return bool(_load_users()) or bool(os.environ.get("SUPABASE_JWT_SECRET"))


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


# --- Supabase Auth (Google login) — JWT verification (HS256 y ES256) ---------
def _b64url_decode(seg: str) -> bytes:
    return base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4))


def _supabase_jwt_secret() -> Optional[bytes]:
    s = os.environ.get("SUPABASE_JWT_SECRET")
    return s.encode("utf-8") if s else None


# Claves públicas ES256 del proyecto, por kid — traídas del JWKS de Supabase
# (endpoint público, no un secreto) y cacheadas para no pedirlas en cada
# request. `fetched_at = 0.0` fuerza un primer fetch real la primera vez.
_JWKS_CACHE: Dict[str, Any] = {"keys": {}, "fetched_at": 0.0}
_JWKS_CACHE_TTL = 3600.0   # 1h — las claves rotan poco


def _jwks_url() -> Optional[str]:
    base = os.environ.get("SUPABASE_URL")
    return base.rstrip("/") + "/auth/v1/.well-known/jwks.json" if base else None


def _fetch_jwks() -> Dict[str, Any]:
    """{kid: EllipticCurvePublicKey}. Nunca lanza: sin SUPABASE_URL, red
    caída, o forma inesperada del JWKS -> {} (ese/esos kid simplemente no
    verifican hasta el próximo fetch que sí funcione)."""
    url = _jwks_url()
    if not url:
        return {}
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return {}
    keys: Dict[str, Any] = {}
    for jwk in (data.get("keys") if isinstance(data, dict) else None) or []:
        if not isinstance(jwk, dict) or jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
            continue
        kid = jwk.get("kid")
        if not kid:
            continue
        try:
            x = int.from_bytes(_b64url_decode(jwk["x"]), "big")
            y = int.from_bytes(_b64url_decode(jwk["y"]), "big")
            keys[kid] = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
        except Exception:
            continue   # una clave con forma rara no debe tirar abajo las demás
    return keys


def _get_jwks(force_refresh: bool = False) -> Dict[str, Any]:
    stale = time.time() - _JWKS_CACHE["fetched_at"] > _JWKS_CACHE_TTL
    if force_refresh or stale or not _JWKS_CACHE["keys"]:
        fresh = _fetch_jwks()
        if fresh:   # solo pisa el cache si de verdad trajo algo — una red
            _JWKS_CACHE["keys"] = fresh   # caída momentánea no borra lo que ya andaba
            _JWKS_CACHE["fetched_at"] = time.time()
    return _JWKS_CACHE["keys"]


def _verify_hs256(header_b64: str, payload_b64: str, sig_b64: str) -> bool:
    secret = _supabase_jwt_secret()
    if not secret:
        return False
    try:
        actual_sig = _b64url_decode(sig_b64)
    except Exception:
        return False
    expected_sig = hmac.new(secret, f"{header_b64}.{payload_b64}".encode("ascii"),
                            hashlib.sha256).digest()
    return hmac.compare_digest(expected_sig, actual_sig)


def _verify_es256(header_b64: str, payload_b64: str, sig_b64: str, kid: Optional[str]) -> bool:
    """La firma JWS de un ES256 viene como R||S crudo (64 bytes, RFC 7518
    §3.4) — cryptography espera DER, hay que convertirla antes de verify()."""
    try:
        raw_sig = _b64url_decode(sig_b64)
        if len(raw_sig) != 64:
            return False
        r = int.from_bytes(raw_sig[:32], "big")
        s = int.from_bytes(raw_sig[32:], "big")
        der_sig = encode_dss_signature(r, s)
    except Exception:
        return False

    pubkey = _get_jwks().get(kid) if kid else None
    if pubkey is None:
        # kid no está en cache — puede ser una rotación reciente de claves;
        # un único refresh forzado antes de rendirse (no en cada intento).
        pubkey = _get_jwks(force_refresh=True).get(kid) if kid else None
    if pubkey is None:
        return False
    try:
        pubkey.verify(der_sig, f"{header_b64}.{payload_b64}".encode("ascii"), ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False
    except Exception:
        return False


def verify_supabase_jwt(token: str) -> Optional[Dict[str, Any]]:
    """Firma + `exp` de un JWT de Supabase Auth. Soporta HS256 (verificable
    100% en el proceso, con SUPABASE_JWT_SECRET) y ES256 (firma asimétrica —
    lo que Supabase usa de verdad para Google Auth en proyectos nuevos;
    verifica contra las claves públicas del JWKS del proyecto). Devuelve el
    payload decodificado si es válido; None ante CUALQUIER problema (formato
    raro, firma mala, `alg` que no sea uno de los dos soportados, vencido,
    sin cómo verificar) — nunca lanza, el caller (`token_identity`) lo trata
    igual que "no es este tipo de token" y sigue probando el modelo local."""
    if not token:
        return None
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return None
    if not isinstance(header, dict) or not isinstance(payload, dict):
        return None

    alg = header.get("alg")
    if alg == "HS256":
        ok = _verify_hs256(header_b64, payload_b64, sig_b64)
    elif alg == "ES256":
        ok = _verify_es256(header_b64, payload_b64, sig_b64, header.get("kid"))
    else:
        ok = False   # nunca aceptar "none" ni ningún otro algoritmo
    if not ok:
        return None

    try:
        if float(payload.get("exp")) <= time.time():
            return None
    except (TypeError, ValueError):
        return None
    return payload


def supabase_role(payload: Dict[str, Any]) -> Optional[str]:
    """`app_metadata.role`, asignado a mano por Diego desde el panel de
    Supabase — nunca `user_metadata` (eso lo puede editar el propio usuario,
    no sirve para autorización)."""
    app_meta = payload.get("app_metadata")
    role = app_meta.get("role") if isinstance(app_meta, dict) else None
    return role if isinstance(role, str) and role else None


def token_identity(token: str) -> Optional[Dict[str, Any]]:
    """Identidad para un token de CUALQUIER mecanismo soportado — el punto
    único que usa api.py::auth_guard. None si la autenticación en sí falla
    (token vencido/mal firmado/con formato raro/usuario local desconocido):
    eso es un 401 para el caller. Si la autenticación es válida pero no trae
    rol utilizable (JWT de Supabase sin app_metadata.role), igual devuelve
    una identidad — con `role: None` — para que el caller pueda distinguir
    "no sé quién eres" (401) de "sé quién eres, pero no tienes permiso
    asignado" (403, fail closed, nunca 've todo por defecto').

    Prueba primero Supabase (el camino real, con roles); si el token no es
    un JWT de Supabase válido, cae al modelo local por-persona (users.json)
    como fallback transicional — ese modelo no tiene roles, así que se le
    asigna "admin" (ve todo). Es un hueco a propósito, documentado: mientras
    dure la transición, cualquier cuenta local dada de alta con add_user()
    tiene acceso total, sin restricción de "cro" — no uses el modelo local
    para alguien a quien de verdad quieras limitar a un rol acotado; dale
    login real de Google en Supabase en cambio."""
    payload = verify_supabase_jwt(token)
    if payload is not None:
        email = payload.get("email")
        return {"email": email, "username": email, "role": supabase_role(payload),
                "source": "supabase"}
    username = token_username(token)
    if username is not None:
        return {"email": None, "username": username, "role": "admin", "source": "local"}
    return None
