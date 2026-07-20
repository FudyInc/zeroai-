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

    def lead_ads(self, client_id: str, cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Leads que dejaron sus datos en un formulario de Meta (Lead Ads)."""
        return _ad_leads_mock(client_id, cfg)


_LEAD_NOMBRES = ["Camila Rojas", "Diego Soto", "Valentina Pérez", "Matías Fuentes",
                 "Fernanda Díaz", "Joaquín Reyes", "Antonia Muñoz", "Tomás Vega"]
_LEAD_EMPRESAS = ["Comercial Andes", "Importadora Sur", "Distribuidora Maipo",
                  "Servicios Cordillera", "Agro Pacífico", "Logística Biobío"]
_LEAD_ROLES = ["Gerente Comercial", "Jefe de Compras", "Dueño", "Encargado de Operaciones"]


def _ad_leads_mock(client_id: str, cfg: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cfg = cfg or {}
    regions = cfg.get("regions") or [CHILE["default_region"]]
    seed = sum(ord(c) for c in (client_id or "demo"))
    out: List[Dict[str, Any]] = []
    for i in range(3 + seed % 4):                      # 3–6 leads
        nombre = _LEAD_NOMBRES[(seed + i) % len(_LEAD_NOMBRES)]
        empresa = _LEAD_EMPRESAS[(seed + i * 3) % len(_LEAD_EMPRESAS)]
        first = nombre.split()[0].lower()
        out.append({
            "company": empresa, "name": nombre,
            "role": _LEAD_ROLES[(seed + i) % len(_LEAD_ROLES)],
            "email": f"{first}.{i}@{empresa.lower().replace(' ', '')}.cl",
            "phone": f"+56 9 {3000 + (seed + i * 131) % 6000} {1000 + (seed * 7 + i) % 8999}",
            "channel": "whatsapp", "source": "meta_ads",
            "campaign": "Leads B2B - Búsqueda", "region": regions[i % len(regions)],
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
                raw = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Meta Ads {e.code}: {e.read().decode('utf-8', 'replace')[:200]}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"no pude contactar a Meta Ads: {e}") from e
        try:
            data = json.loads(raw)
        except Exception:
            raise RuntimeError(f"Meta Ads: respuesta no-JSON ({raw[:200]!r})")
        # Defensivo: la Graph API siempre debería devolver {"data": [...]}, pero
        # si algún día cambia de forma no queremos reventar con AttributeError
        # iterando algo que no es una lista de dicts.
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return []
        out: List[Dict[str, Any]] = []
        for c in items:
            if not isinstance(c, dict):
                continue
            out.append({
                "id": c.get("id"), "name": c.get("name"), "objective": c.get("objective"),
                "status": "active" if c.get("effective_status") == "ACTIVE" else "paused",
                "region": (cfg or {}).get("regions", [CHILE["default_region"]])[0],
                "budget_clp": int(float(c.get("daily_budget", 0) or 0)),  # ya en CLP (sin decimales)
                "spent_clp": 0, "leads": 0, "cpl_clp": 0,
            })
        return out

    def lead_ads(self, client_id: str, cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        # Lead Ads real (Graph: /{form}/leads) — pendiente de pago/token. Por ahora vacío.
        return []


_API = "https://graph.facebook.com/v20.0"


def _graph(path: str, token: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    q = {"access_token": token, **(params or {})}
    url = f"{_API}/{path}?{urllib.parse.urlencode(q)}"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(detail).get("error", {}).get("message", detail)
        except Exception:
            msg = detail
        raise RuntimeError(f"Meta: {msg[:200]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"no pude contactar a Meta: {e}") from e
    try:
        data = json.loads(raw)
    except Exception:
        raise RuntimeError(f"Meta: respuesta no-JSON ({raw[:200]!r})")
    if not isinstance(data, dict):
        raise RuntimeError(f"Meta: forma de respuesta inesperada ({data!r:.200})")
    return data


def list_ad_accounts(token: str) -> List[Dict[str, Any]]:
    """Cuentas publicitarias que el token puede ver — para elegir el act_ correcto."""
    d = _graph("me/adaccounts", token, {"fields": "id,name,account_status", "limit": 100})
    items = d.get("data")
    if not isinstance(items, list):
        return []
    return [{"id": a.get("id"), "name": a.get("name"), "status": a.get("account_status")}
            for a in items if isinstance(a, dict)]


def make_metaads(cfg: Optional[Dict[str, Any]] = None):
    """Real si hay token de agencia + cuenta del cliente (o cuenta global); si no, mock."""
    cfg = cfg or {}
    account = cfg.get("ad_account") or os.environ.get("META_AD_ACCOUNT_ID")
    if account:
        account = str(account).strip()
        if account and not account.startswith("act_"):   # tolera que peguen solo el número
            account = "act_" + account
    if os.environ.get("META_ADS_TOKEN") and account:
        try:
            return MetaAds(account)
        except Exception:
            pass
    return MockMetaAds()
