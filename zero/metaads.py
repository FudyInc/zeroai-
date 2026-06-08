"""Meta Ads — campañas de marketing digital, mock-first.

Misma filosofía que canales/CRM: una abstracción con mock fiel al contrato y un
backend real (Meta Marketing API) que se enchufa con credenciales. El mock es
determinista por cliente para demostrar offline; el real lee campañas + insights
de la cuenta publicitaria.

Contrato de una campaña:
  {id, name, objective, status: active|paused, budget_usd, spent_usd, leads, cpl_usd}

Real: necesita META_ADS_TOKEN y META_AD_ACCOUNT_ID (formato act_123…). Se activa solo
si ambos están en .env; si no, mock.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List

from ._env import load_env

load_env()

_OBJECTIVES = ["OUTCOME_LEADS", "OUTCOME_TRAFFIC", "OUTCOME_AWARENESS"]


def _round(x: float) -> float:
    return round(x, 2)


class MockMetaAds:
    """Campañas deterministas por cliente — para construir y demostrar sin cuenta Meta."""
    live = False

    def campaigns(self, client_id: str) -> List[Dict[str, Any]]:
        seed = sum(ord(c) for c in (client_id or "demo"))
        out: List[Dict[str, Any]] = []
        plantillas = [
            ("Leads B2B - Búsqueda", "OUTCOME_LEADS", "active"),
            ("Remarketing - Web", "OUTCOME_TRAFFIC", "active"),
            ("Awareness - Rubro", "OUTCOME_AWARENESS", "paused"),
        ]
        for i, (name, obj, status) in enumerate(plantillas):
            budget = 200 + ((seed + i * 37) % 8) * 50          # 200–550
            spent = _round(budget * (0.3 + ((seed + i) % 6) / 10))  # 30–80% del presupuesto
            leads = max(1, (seed + i * 13) % 40) if obj == "OUTCOME_LEADS" else (seed + i) % 8
            cpl = _round(spent / leads) if leads else 0.0
            out.append({
                "id": f"mock-{client_id}-{i}",
                "name": name, "objective": obj, "status": status,
                "budget_usd": float(budget), "spent_usd": spent,
                "leads": leads, "cpl_usd": cpl,
            })
        return out


class MetaAds:
    """Campañas reales vía Meta Marketing API (Graph). Lectura básica de campañas;
    el gasto/resultados finos vienen del endpoint de insights (siguiente iteración)."""
    live = True
    API = "https://graph.facebook.com/v20.0"

    def __init__(self) -> None:
        self.token = os.environ["META_ADS_TOKEN"]
        self.account = os.environ["META_AD_ACCOUNT_ID"]   # act_123…

    def campaigns(self, client_id: str) -> List[Dict[str, Any]]:
        params = urllib.parse.urlencode({
            "fields": "name,objective,effective_status,daily_budget",
            "access_token": self.token, "limit": 50,
        })
        req = urllib.request.Request(f"{self.API}/{self.account}/campaigns?{params}")
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Meta Ads {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from e
        out: List[Dict[str, Any]] = []
        for c in data.get("data", []):
            budget = float(c.get("daily_budget", 0) or 0) / 100  # Meta da centavos
            out.append({
                "id": c.get("id"), "name": c.get("name"),
                "objective": c.get("objective"),
                "status": "active" if (c.get("effective_status") == "ACTIVE") else "paused",
                "budget_usd": budget, "spent_usd": 0.0, "leads": 0, "cpl_usd": 0.0,
            })
        return out


def make_metaads():
    """Real si hay credenciales de Meta; si no, mock (seguro por defecto)."""
    if os.environ.get("META_ADS_TOKEN") and os.environ.get("META_AD_ACCOUNT_ID"):
        try:
            return MetaAds()
        except Exception:
            pass
    return MockMetaAds()
