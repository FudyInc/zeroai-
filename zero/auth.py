"""Agency auth — a single password gate over the API + dashboard.

Model: one owner (the agency). If no AUTH_PASSWORD is set the app is open (dev /
mock convenience); set one and the API requires a token. Tokens are stateless and
signed with HMAC over their expiry, keyed by the password itself — so changing the
password invalidates every old token. Stdlib only.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

TTL = 7 * 24 * 3600   # a week


def auth_enabled() -> bool:
    return bool(os.environ.get("AUTH_PASSWORD"))


def _secret() -> bytes:
    return (os.environ.get("AUTH_PASSWORD") or "").encode("utf-8")


def verify_password(password: str) -> bool:
    real = os.environ.get("AUTH_PASSWORD") or ""
    return bool(real) and hmac.compare_digest(password or "", real)


def make_token(ttl: int = TTL) -> str:
    exp = str(int(time.time()) + ttl)
    sig = hmac.new(_secret(), exp.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_token(token: str) -> bool:
    if not _secret():
        return False
    try:
        exp, sig = (token or "").split(".", 1)
    except ValueError:
        return False
    good = hmac.new(_secret(), exp.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return False
    try:
        return int(exp) > time.time()
    except ValueError:
        return False
