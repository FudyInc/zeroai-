"""Crédito del agente PoolEdge, conciliado con los costos de su clave dedicada."""
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

CLIENT = "losetaschile"
FIELD = "whatsapp_claude_credit"


BILLING_FILE = Path(__file__).resolve().parents[1] / ".runtime" / "pooledge-billing.json"


def billing_observation(saved, now):
    try:
        observation = json.loads(BILLING_FILE.read_text(encoding="utf-8-sig"))
        at = datetime.fromisoformat(observation["at"])
        amount = Decimal(str(observation["available"]))
        if saved <= at <= now and amount.is_finite() and amount >= 0:
            return at, amount
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
        pass
    return None


def source():
    return os.getenv("ANTHROPIC_ADMIN_API_KEY"), os.getenv("POOLEDGE_WHATSAPP_CLAUDE_KEY_ID")


def cost(start, end, admin_key, key_id):
    """Use minute rows for partial hours and aggregate complete hours in larger windows."""
    total = Decimal(0)
    while start < end:
        hour = start.replace(minute=0)
        partial = start != hour or end < hour + timedelta(hours=1)
        until = (min(hour + timedelta(hours=1), end) if partial else
                 min(start + timedelta(days=31), end.replace(minute=0)))
        params = {"starting_at": start.isoformat(), "ending_at": until.isoformat(),
                  "api_key_ids[]": key_id, "limit": 1000}
        if partial:
            params["time_bucket_width"] = "1m"
        url = "https://api.anthropic.com/v1/organizations/analytics/cost?" + urlencode(params)
        request = Request(url, headers={"x-api-key": admin_key, "anthropic-version": "2023-06-01",
                                        "anthropic-beta": "analytics-usage-cost-2026-08-24"})
        with urlopen(request, timeout=8) as response:
            report = json.load(response)
        if report["has_more"]:
            raise ValueError("Informe agregado incompleto")
        for row in report["data"]:
            charge = row["cost"]
            if charge["currency"] != "USD":
                raise ValueError("Moneda inesperada")
            total += Decimal(charge["amount"]) / 100
        start = until
    return total


def credit_status(record, now=None):
    if not record:
        return {"state": "empty"}
    available = Decimal(str(record["available"]))
    capacity = Decimal(str(record["capacity"]))
    saved = datetime.fromisoformat(record["at"])
    now = now or datetime.now(timezone.utc)
    observed = billing_observation(saved, now)
    if observed:
        at, amount = observed
        return {"state": "billing" if now - at <= timedelta(minutes=12) else "billing_stale",
                "available": float(amount), "capacity": float(capacity), "at": at.isoformat()}
    end = now.replace(second=0, microsecond=0)
    # The first partial minute is excluded to avoid charging usage prior to calibration.
    start = saved.replace(second=0, microsecond=0)
    if saved > start:
        start += timedelta(minutes=1)
    admin, key_id = source()
    state = "recorded"
    if admin and key_id:
        try:
            if now - saved > timedelta(days=360):
                raise ValueError("Actualizar referencia")
            available = max(Decimal(0), available - cost(start, end, admin, key_id))
            state = "estimated"
        except (OSError, ValueError, KeyError, ArithmeticError, TypeError):
            state = "unavailable"
    return {"state": state, "available": float(available.quantize(Decimal(".01"))),
            "capacity": float(capacity), "at": record["at"],
            "through": max(saved, end).isoformat() if state == "estimated" else None}
