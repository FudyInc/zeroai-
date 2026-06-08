"""Meta Ads — campañas de marketing digital, por cliente, mock-first.

Cada cliente tiene su propia config de marketing (cuenta publicitaria, presupuesto
mensual, zonas) → las campañas son personalizadas y aisladas por cliente. Foco
mercado chileno: montos en CLP y geo por defecto Santiago (RM).

Misma filosofía que canales/CRM: mock fiel al contrato + backend real (Meta
Marketing API) que se enchufa con credenciales.

Contrato de una campaña:
  {id, name, objective, status, region, budget_clp, spent_clp, leads, cpl_clp}

Real: token de la agencia (META_ADS_TOKEN) + cuenta del cliente (cfg.ad_account, o
META_AD_ACCOUNT_ID como fallback).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from ._env import load_env

load_env()

# Referencia B2B Chile (CLP) — para contexto/optimización; no es dato real de cuenta.
CHILE = {"default_region": "Santiago (RM)", "good_cpl_clp": 6000, "currency": "CLP"}


class MockMetaAds:
    """Campañas deterministas por cliente — construir y demostrar sin cuenta Meta."""
    live = False

    def campaigns(self, client_id: str, cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        cfg = cfg or {}
        regions = cfg.get("regions") or [CHILE["default_region"]]
        monthly = int(cfg.get("monthly_budget_clp") or 300_000)
        seed = sum(ord(c) for c in (client_id or "demo"))
        plantillas = [
            ("Leads B2B - Búsqueda", "OUTCOME_LEADS", "active", 0.45),
            ("Remarketing - Web", "OUTCOME_TRAFFIC", "active", 0.30),
            ("Awareness - Rubro", "OUTCOME_AWARENESS", "paused", 0.25),
        ]
        out: List[Dict[str, Any]] = []
        for i, (name, obj, status, share) in enumerate(plantillas):
            region = regions[i % len(regions)]
            budget = int(monthly * share)
            spent = int(budget * (0.3 + ((seed + i) % 6) / 10))     # 30–80%
            leads = max(1, (seed + i * 13) % 40) if obj == "OUTCOME_LEADS" else (seed + i) % 6
            cpl = round(spent / leads) if leads else 0
            out.append({
                "id": f"mock-{client_id}-{i}",
                "name": name, "objective": obj, "status": status, "region": region,
                "budget_clp": budget, "spent_clp": spent, "leads": leads, "cpl_clp": cpl,
            })
        return out


class MetaAds:
    """Campañas reales vía Meta Marketing API (Graph). Lectura de campañas; gasto/
    resultados finos vienen de insights (siguiente iteración)."""
    live = True
    API = "https://graph.facebook.com/v20.0"

    def __init__(self, ad_account: str) -> None:
        self.token = os.environ["META_ADS_TOKEN"]
        self.account = ad_account

    def campaigns(self, client_id: str, cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
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
            out.append({
                "id": c.get("id"), "name": c.get("name"), "objective": c.get("objective"),
                "status": "active" if c.get("effective_status") == "ACTIVE" else "paused",
                "region": (cfg or {}).get("regions", [CHILE["default_region"]])[0],
                "budget_clp": int(float(c.get("daily_budget", 0) or 0)),  # ya en CLP (sin decimales)
                "spent_clp": 0, "leads": 0, "cpl_clp": 0,
            })
        return out


def make_metaads(cfg: Optional[Dict[str, Any]] = None):
    """Real si hay token de agencia + cuenta del cliente (o cuenta global); si no, mock."""
    cfg = cfg or {}
    account = cfg.get("ad_account") or os.environ.get("META_AD_ACCOUNT_ID")
    if os.environ.get("META_ADS_TOKEN") and account:
        try:
            return MetaAds(account)
        except Exception:
            pass
    return MockMetaAds()
