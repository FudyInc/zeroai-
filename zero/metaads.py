"""Meta Ads — campañas de marketing digital, por cliente.

Cada cliente tiene su propia config de marketing (cuenta publicitaria, presupuesto
mensual, zonas) → las campañas son personalizadas y aisladas por cliente. Foco
mercado chileno: montos en CLP y geo por defecto Santiago (RM).

Misma filosofía que canales/CRM: mock fiel al contrato + backend real (Meta
Marketing API) que se enchufa con credenciales.

Contrato de una campaña:
  {id, name, objective, status, region, budget_clp, spent_clp, leads, cpl_clp}

En HTTP, cada negocio necesita su token y cuenta publicitaria propios.
"""
from __future__ import annotations

import json
import hashlib
import os
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation
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
    """Campañas e Insights reales vía Meta Marketing API (Graph)."""
    live = True
    API = "https://graph.facebook.com/v20.0"

    def __init__(self, ad_account: str, token: Optional[str] = None) -> None:
        self.token = token if token is not None else os.environ["META_ADS_TOKEN"]
        self.account = ad_account

    def campaigns(self, client_id: str, cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        items = _graph_pages(f"{self.account}/campaigns", self.token, {
            "fields": "id,name,objective,effective_status,daily_budget,lifetime_budget,created_time",
            "limit": 100,
        })
        insights = _graph_pages(f"{self.account}/insights", self.token, {
            "fields": "campaign_id,spend,actions,account_currency",
            "level": "campaign", "date_preset": "this_month", "limit": 100,
        })
        by_campaign = {str(r.get("campaign_id")): r for r in insights
                       if isinstance(r, dict) and r.get("campaign_id")}
        out: List[Dict[str, Any]] = []
        for c in items:
            if not isinstance(c, dict):
                continue
            insight = by_campaign.get(str(c.get("id"))) or {}
            spent = _amount(insight.get("spend"))
            leads = _lead_count(insight.get("actions"))
            daily = c.get("daily_budget")
            lifetime = c.get("lifetime_budget")
            budget = daily if daily is not None else lifetime
            out.append({
                "id": c.get("id"), "name": c.get("name"), "objective": c.get("objective"),
                "status": "active" if c.get("effective_status") == "ACTIVE" else "paused",
                "region": ((cfg or {}).get("regions") or [CHILE["default_region"]])[0],
                "budget_clp": _amount(budget) if budget is not None else None,
                "budget_period": "daily" if daily is not None else "lifetime" if lifetime is not None else None,
                "spent_clp": spent, "leads": leads,
                "cpl_clp": round(spent / leads) if leads else 0,
                "created_at": c.get("created_time"),
                "currency": insight.get("account_currency") or CHILE["currency"],
            })
        return out

    def daily_spend(self) -> List[Dict[str, Any]]:
        rows = _graph_pages(f"{self.account}/insights", self.token, {
            "fields": "date_start,spend", "level": "account",
            "date_preset": "last_7d", "time_increment": 1, "limit": 100,
        })
        return [{"date": r.get("date_start"), "spent_clp": _amount(r.get("spend"))}
                for r in rows if isinstance(r, dict) and r.get("date_start")]

    def lead_ads(self, client_id: str, cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        # Lead Ads real (Graph: /{form}/leads) — pendiente de pago/token. Por ahora vacío.
        return []


_API = "https://graph.facebook.com/v20.0"

_LEAD_ACTION_TYPES = (
    "onsite_conversion.lead_grouped", "onsite_conversion.lead",
    "lead", "offsite_conversion.fb_pixel_lead",
)


def _amount(value: Any) -> int:
    try:
        return int(Decimal(str(value or 0)).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        return 0


def _lead_count(actions: Any) -> int:
    """Elige una métrica de lead: sumar action types duplicaría conversiones."""
    values = {a.get("action_type"): _amount(a.get("value"))
              for a in actions if isinstance(a, dict)} if isinstance(actions, list) else {}
    for kind in _LEAD_ACTION_TYPES:
        if kind in values:
            return values[kind]
    return 0


def _graph(path: str, token: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{_API}/{path}?{urllib.parse.urlencode(params or {})}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(detail).get("error", {}).get("message", detail)
        except Exception:
            msg = detail
        raise RuntimeError(f"Meta HTTP {e.code}: {msg[:200]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"no pude contactar a Meta: {e}") from e
    try:
        data = json.loads(raw)
    except Exception:
        raise RuntimeError(f"Meta: respuesta no-JSON ({raw[:200]!r})")
    if not isinstance(data, dict):
        raise RuntimeError(f"Meta: forma de respuesta inesperada ({data!r:.200})")
    return data


def _graph_pages(path: str, token: str, params: Dict[str, Any], max_pages: int = 20) -> List[Dict[str, Any]]:
    """Lee todas las páginas hasta un límite explícito; nunca trunca en silencio."""
    out: List[Dict[str, Any]] = []
    cursor = None
    for _ in range(max_pages):
        query = dict(params)
        if cursor:
            query["after"] = cursor
        data = _graph(path, token, query)
        items = data.get("data")
        if not isinstance(items, list):
            return out
        out.extend(x for x in items if isinstance(x, dict))
        paging = data.get("paging") or {}
        cursors = paging.get("cursors") or {}
        next_cursor = cursors.get("after") if isinstance(cursors, dict) else None
        if not paging.get("next") or not next_cursor or next_cursor == cursor:
            return out
        cursor = next_cursor
    raise RuntimeError("Meta devolvió más páginas que el límite de lectura; no se muestran cifras parciales")


def list_ad_accounts(token: str) -> List[Dict[str, Any]]:
    """Cuentas publicitarias que el token puede ver — para elegir el act_ correcto."""
    items = _graph_pages("me/adaccounts", token, {"fields": "id,name,account_status", "limit": 100})
    return [{"id": a.get("id"), "name": a.get("name"), "status": a.get("account_status")}
            for a in items if isinstance(a, dict)]


def client_token_key(client_id: str) -> str:
    """Nombre estable del secreto de Meta de un negocio; el valor nunca va al CRM."""
    digest = hashlib.sha256(client_id.encode("utf-8")).hexdigest()[:20].upper()
    return f"META_ADS_TOKEN_CLIENT_{digest}"


def client_token(client_id: str) -> Optional[str]:
    return os.environ.get(client_token_key(client_id))


def make_metaads(cfg: Optional[Dict[str, Any]] = None, *, client_id: Optional[str] = None):
    """En HTTP exige cuenta y token asignados al negocio; sin mezcla global.

    La llamada sin cliente conserva el modo histórico de CLI/pruebas, pero las
    rutas por negocio siempre entregan `client_id` y no usan esa credencial.
    """
    if client_id is not None:
        account = (cfg or {}).get("ad_account")
        token = client_token(client_id)
    else:
        account = os.environ.get("META_AD_ACCOUNT_ID") if cfg is None else cfg.get("ad_account")
        token = os.environ.get("META_ADS_TOKEN")
    if account:
        account = str(account).strip()
        if account and not account.startswith("act_"):   # tolera que peguen solo el número
            account = "act_" + account
    if token and account:
        try:
            return MetaAds(account, token)
        except Exception:
            pass
    return MockMetaAds()
