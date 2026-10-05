#!/usr/bin/env python3
"""Check coexistence and start Meta's one-time Business App data sync.

Run ``status`` after Embedded Signup. Run ``sync`` once, immediately after the
phone reports both ``is_on_biz_app=true`` and ``platform_type=CLOUD_API``.
The signed webhook archives history, contacts, and app message echoes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from zero._env import load_env  # noqa: E402


API = "https://graph.facebook.com/v26.0"


def graph(path: str, token: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}/{path}", data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc).get("error", {}).get("message", "Error de Meta")
        except Exception:
            detail = f"HTTP {exc.code}"
        raise RuntimeError(detail) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "sync"))
    parser.add_argument("--kind", choices=("contacts", "history", "both"), default="both",
                        help="reintentar solo la parte que falte si una solicitud falla")
    args = parser.parse_args()
    load_env()
    token = os.environ.get("WHATSAPP_TOKEN")
    phone_id = os.environ.get("WHATSAPP_PHONE_ID")
    if not token or not phone_id:
        parser.error("faltan WHATSAPP_TOKEN / WHATSAPP_PHONE_ID")
    fields = urllib.parse.urlencode({"fields": "display_phone_number,status,platform_type,is_on_biz_app"})
    status = graph(f"{phone_id}?{fields}", token)
    ready = status.get("is_on_biz_app") is True and status.get("platform_type") == "CLOUD_API"
    print(json.dumps({"number": status.get("display_phone_number"),
                      "status": status.get("status"),
                      "platform_type": status.get("platform_type"),
                      "is_on_biz_app": status.get("is_on_biz_app"),
                      "coexistence_active": ready}, ensure_ascii=False))
    if args.action == "status":
        return 0
    if not ready:
        print("Coexistencia aún no activa; no inicio una sincronización única.", file=sys.stderr)
        return 2
    kinds = {"contacts": ("smb_app_state_sync",), "history": ("history",),
             "both": ("smb_app_state_sync", "history")}[args.kind]
    for kind in kinds:
        result = graph(f"{phone_id}/smb_app_data", token,
                       {"messaging_product": "whatsapp", "sync_type": kind})
        print(json.dumps({"sync_type": kind, "request_id": result.get("request_id")},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
