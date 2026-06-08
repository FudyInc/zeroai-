"""Shared Supabase (PostgREST) HTTP helper — stdlib urllib, no dependency.

One place for the REST call so `crm_supabase` and `memory_supabase` don't each
keep their own copy. Raises SupabaseError on any HTTP/network failure.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional


class SupabaseError(RuntimeError):
    """An HTTP or network error talking to Supabase. Carries the HTTP code if any."""

    def __init__(self, message: str, code: Optional[int] = None):
        super().__init__(message)
        self.code = code


def sb_request(base_url: str, key: str, method: str, path: str,
               body: Any = None, prefer: Optional[str] = None) -> Any:
    """Call `{base_url}/rest/v1/{path}` and return parsed JSON (or None if empty)."""
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{base_url}/rest/v1/{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise SupabaseError(f"Supabase {e.code}: {detail}", code=e.code) from e
    except urllib.error.URLError as e:
        raise SupabaseError(f"no pude contactar a Supabase: {e}") from e
