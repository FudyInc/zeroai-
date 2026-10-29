"""Meta Ads — campañas de marketing digital, por cliente.

Cada cliente tiene su propia config de marketing (cuenta publicitaria, presupuesto
mensual, zonas) → las campañas son personalizadas y aisladas por cliente. Foco
mercado chileno: montos en CLP y geo por defecto Santiago (RM).

Misma filosofía que canales/CRM: mock fiel al contrato + backend real (Meta
Marketing API) que se enchufa con credenciales.

Contrato de una campaña:
  {id, name, objective, status, region, budget_clp, spent_clp, leads, cpl_clp}

Contrato de un anuncio pagado (`ads`):
  {ad_id, ad_name, campaign_id, campaign_name, status, post_id,
   creative: {title, body, image_url, thumbnail_url, call_to_action},
   spend, impressions, reach, clicks, ctr, leads, cpl}
  `cpl` es None sin leads: nunca se divide por cero ni se inventa un 0.

En HTTP, cada negocio necesita su token y cuenta publicitaria propios.
"""
from __future__ import annotations

import json
import hashlib
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from ._env import load_env
from .config import LEAD_ADS_CURSOR_MARGIN_SECONDS

load_env()

# Referencia B2B Chile (CLP) — para contexto/optimización; no es dato real de cuenta.
CHILE = {"default_region": "Santiago (RM)", "good_cpl_clp": 6000, "currency": "CLP",
         "timezone": "America/Santiago"}


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

    def ads(self, client_id: str, cfg: Optional[Dict[str, Any]] = None,
            since: Optional[str] = None) -> List[Dict[str, Any]]:
        """Anuncios pagados deterministas — misma forma que MetaAds.ads. Solo suite."""
        seed = sum(ord(c) for c in (client_id or "demo"))
        out: List[Dict[str, Any]] = []
        for i, camp in enumerate(self.campaigns(client_id, cfg)):
            spend = camp["spent_clp"]
            impressions = 1000 + (seed * (i + 3)) % 9000
            clicks = 10 + (seed + i * 7) % 90
            leads = camp["leads"]
            out.append(_ad_item(
                ad_id=f"mock-ad-{client_id}-{i}", ad_name=f"Anuncio demo {i + 1}",
                campaign_id=camp["id"], campaign_name=camp["name"], status=camp["status"],
                post_id=f"mock-page_mock-post-{i}",
                creative={"title": f"Anuncio demo {i + 1}", "body": "Texto de ejemplo del post",
                          "image_url": None, "thumbnail_url": None,
                          "call_to_action": "LEARN_MORE"},
                spend=spend, impressions=impressions, reach=int(impressions * 0.7),
                clicks=clicks, ctr=round(clicks / impressions * 100, 2), leads=leads))
        return out

    failed_forms: List[Dict[str, str]] = []     # misma forma que MetaAds
    cursors: Dict[str, str] = {}

    def lead_ads(self, client_id: str, cfg: Optional[Dict[str, Any]] = None,
                 since: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
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
        email = f"{first}.{i}@{empresa.lower().replace(' ', '')}.cl"
        form_id = ((cfg.get("lead_form_ids") or ["0"])[0])
        out.append({
            "key": email, "meta_lead_id": f"mock-lead-{seed}-{i}", "meta_form_id": form_id,
            "income_range": ["Menos de $1.000.000", "$1.000.000 - $3.000.000",
                             "Más de $3.000.000"][(seed + i) % 3],
            "lead_origin": {"platform": "ig", "form_id": form_id, "ad_id": f"mock-ad-{i}",
                            "ad_name": "Anuncio demo", "campaign_name": "Leads B2B - Búsqueda",
                            "lead_id": f"mock-lead-{seed}-{i}"},
            "company": empresa, "name": nombre,
            "role": _LEAD_ROLES[(seed + i) % len(_LEAD_ROLES)],
            "email": email,
            "phone": f"+56 9 {3000 + (seed + i * 131) % 6000} {1000 + (seed * 7 + i) % 8999}",
            "channel": "whatsapp", "source": "meta_ads",
            "campaign": "Leads B2B - Búsqueda", "region": regions[i % len(regions)],
        })
    return out


_NOT_CLP = "La cuenta publicitaria no usa CLP; se ocultaron importes para evitar cifras incorrectas"


class MetaAds:
    """Campañas e Insights reales vía Meta Marketing API (Graph)."""
    live = True
    API = "https://graph.facebook.com/v20.0"

    def __init__(self, ad_account: str, token: Optional[str] = None) -> None:
        self.token = token if token is not None else os.environ["META_ADS_TOKEN"]
        self.account = ad_account

    def campaigns(self, client_id: str, cfg: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        try:
            items = _graph_pages(f"{self.account}/campaigns", self.token, {
                "fields": "id,name,objective,effective_status,daily_budget,lifetime_budget,created_time",
                "limit": 100,
            })
        except RuntimeError as exc:
            if "forma de respuesta inesperada" not in str(exc):
                raise
            return []
        insights = _graph_pages(f"{self.account}/insights", self.token, {
            "fields": "campaign_id,spend,actions,account_currency",
            "level": "campaign", "date_preset": "this_month", "limit": 100,
        })
        # Los montos se muestran como CLP: si la cuenta usa otra moneda, ocultarlos
        # es mejor que mostrar 50 USD como $50. Sin moneda conocida, tampoco se
        # asume CLP (una cuenta sin Insights aún puede tener presupuestos).
        currencies = {str(r.get("account_currency")) for r in insights
                      if isinstance(r, dict) and r.get("account_currency")}
        if not currencies and items:
            currencies = {str(_graph(self.account, self.token, {"fields": "currency"}).get("currency"))}
        if currencies and currencies != {"CLP"}:
            raise RuntimeError(_NOT_CLP)
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

    def ads(self, client_id: str, cfg: Optional[Dict[str, Any]] = None,
            since: Optional[str] = None) -> List[Dict[str, Any]]:
        """Anuncios ya pagados de la cuenta, con su post/creatividad y sus métricas.

        Solo lectura. La base son los Insights a nivel anuncio (gasto > 0): así un
        anuncio archivado que sí gastó no desaparece. La lista de /ads solo aporta
        estado y creatividad; si un anuncio no aparece ahí, su creatividad va en None.
        `since` = "YYYY-MM-DD" acota los Insights desde esa fecha hasta hoy; sin
        `since`, todo el historial (date_preset=maximum).
        """
        params: Dict[str, Any] = {
            "fields": "ad_id,ad_name,campaign_id,campaign_name,spend,impressions,reach,"
                      "clicks,ctr,actions,account_currency",
            "level": "ad", "limit": 100,
        }
        if since:
            params["time_range"] = json.dumps({"since": since, "until": today_chile().isoformat()})
        else:
            params["date_preset"] = "maximum"
        insights = _graph_pages(f"{self.account}/insights", self.token, params, strict=True)
        # Misma regla que campaigns(): los montos se entregan como CLP, así que una
        # cuenta en otra moneda se declara en vez de convertirse en silencio.
        currencies = {str(r.get("account_currency")) for r in insights if r.get("account_currency")}
        if not currencies and insights:
            currencies = {str(_graph(self.account, self.token, {"fields": "currency"}).get("currency"))}
        if currencies and currencies != {"CLP"}:
            raise RuntimeError(_NOT_CLP)
        paid = [r for r in insights if r.get("ad_id") and _amount(r.get("spend")) > 0]
        if not paid:
            return []
        rows = _graph_pages(f"{self.account}/ads", self.token, {
            "fields": "id,name,campaign_id,campaign{name},effective_status,"
                      "creative{title,body,image_url,thumbnail_url,call_to_action_type,"
                      "effective_object_story_id}",
            # Sin este filtro Graph omite ARCHIVED/DELETED, justo los que ya gastaron.
            "filtering": json.dumps([{"field": "effective_status", "operator": "IN",
                                      "value": _AD_STATUSES}]),
            "limit": 100,
        }, strict=True)
        by_ad = {str(r.get("id")): r for r in rows if r.get("id")}
        out: List[Dict[str, Any]] = []
        for ins in paid:
            ad = by_ad.get(str(ins.get("ad_id"))) or {}
            creative = ad.get("creative") if isinstance(ad.get("creative"), dict) else {}
            campaign = ad.get("campaign") if isinstance(ad.get("campaign"), dict) else {}
            status = ad.get("effective_status")
            out.append(_ad_item(
                ad_id=str(ins.get("ad_id")), ad_name=ad.get("name") or ins.get("ad_name"),
                campaign_id=ad.get("campaign_id") or ins.get("campaign_id"),
                campaign_name=campaign.get("name") or ins.get("campaign_name"),
                status=str(status).lower() if status else None,
                post_id=creative.get("effective_object_story_id"),
                creative={"title": creative.get("title"), "body": creative.get("body"),
                          "image_url": creative.get("image_url"),
                          "thumbnail_url": creative.get("thumbnail_url"),
                          "call_to_action": creative.get("call_to_action_type")},
                spend=_amount(ins.get("spend")), impressions=_amount(ins.get("impressions")),
                reach=_amount(ins.get("reach")), clicks=_amount(ins.get("clicks")),
                ctr=_ratio(ins.get("ctr")), leads=_lead_count(ins.get("actions"))))
        out.sort(key=lambda a: a["spend"], reverse=True)
        return out

    def daily_spend(self) -> List[Dict[str, Any]]:
        rows = _graph_pages(f"{self.account}/insights", self.token, {
            "fields": "date_start,spend", "level": "account",
            "date_preset": "last_7d", "time_increment": 1, "limit": 100,
        })
        if rows and _graph(self.account, self.token, {"fields": "currency"}).get("currency") != "CLP":
            raise RuntimeError(_NOT_CLP)
        return [{"date": r.get("date_start"), "spent_clp": _amount(r.get("spend"))}
                for r in rows if isinstance(r, dict) and r.get("date_start")]

    def lead_ads(self, client_id: str, cfg: Optional[Dict[str, Any]] = None,
                 since: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """Lee solamente los formularios asignados explícitamente a este cliente.

        `since` = {form_id: created_time ISO} de la última lectura exitosa de cada
        formulario: se piden solo los leads posteriores (con margen de
        LEAD_ADS_CURSOR_MARGIN_SECONDS; la dedupe del CRM absorbe los repetidos).
        Un formulario que falla no aborta a los demás: queda en `self.failed_forms`
        [{form_id, error}] y su cursor no avanza. `self.cursors` deja el nuevo cursor
        de cada formulario leído sin error. Si fallan todos, lanza RuntimeError.
        """
        forms = (cfg or {}).get("lead_form_ids") or []
        self.failed_forms, self.cursors = [], {}
        if not forms:
            return []
        leads = []
        ad_accounts = {}
        for form_id in forms:
            params = {
                "fields": "id,created_time,ad_id,ad_name,campaign_name,platform,form_id,field_data",
                "limit": 100,
            }
            cursor = (since or {}).get(form_id)
            moment = _parse_graph_time(cursor)
            if moment is not None:
                params["filtering"] = json.dumps([{
                    "field": "time_created", "operator": "GREATER_THAN",
                    "value": int(moment.timestamp()) - LEAD_ADS_CURSOR_MARGIN_SECONDS}])
            try:
                rows = _graph_pages(f"{form_id}/leads", self.token, params, strict=True)
                form_leads = self._normalize_rows(form_id, rows, ad_accounts)
            except RuntimeError as e:
                self.failed_forms.append({"form_id": form_id, "error": str(e)})
                continue
            leads.extend(form_leads)
            times = [(t, r.get("created_time")) for r in rows
                     if (t := _parse_graph_time(r.get("created_time"))) is not None]
            newest = max(times)[1] if times else None
            if newest and (moment is None or _parse_graph_time(newest) > moment):
                self.cursors[form_id] = newest
            elif cursor:
                self.cursors[form_id] = cursor
        if self.failed_forms and len(self.failed_forms) == len(forms):
            raise RuntimeError("; ".join(f"formulario {f['form_id']}: {f['error']}"
                                         for f in self.failed_forms))
        return leads

    def _normalize_rows(self, form_id: str, rows: List[Dict[str, Any]],
                        ad_accounts: Dict[str, str]) -> List[Dict[str, Any]]:
        leads = []
        for row in rows:
            ad_id = str(row.get("ad_id") or "").strip()
            if not ad_id:
                continue  # sin anuncio no se puede acreditar a la cuenta asignada
            if ad_id not in ad_accounts:
                ad_accounts[ad_id] = str(_graph(ad_id, self.token, {"fields": "account_id"}).get("account_id") or "")
            if ad_accounts[ad_id] != self.account.removeprefix("act_"):
                continue
            fields = {}
            for field in row.get("field_data") or []:
                if isinstance(field, dict) and isinstance(field.get("values"), list):
                    field_name = str(field.get("name") or "").strip()
                    values = [str(value).strip() for value in field["values"] if str(value).strip()]
                    fields[field_name] = ", ".join(values)
            name = fields.get("full_name") or " ".join(filter(None, (
                fields.get("first_name"), fields.get("last_name"))))
            email = fields.get("email") or None
            phone = fields.get("phone_number") or None
            if not (email or phone):
                continue
            custom_fields = {
                key: value for key, value in fields.items()
                if key and key.lower() not in _CONTACT_FIELDS and value
            }
            income_field = next((
                question for question in custom_fields
                if any(term in question.casefold() for term in _INCOME_TERMS)
            ), None)
            if income_field is None and len(custom_fields) == 1:
                # Si la única pregunta propia del formulario es una sola, es la renta.
                income_field = next(iter(custom_fields))
            income_range = custom_fields.get(income_field) if income_field else None
            leads.append({"key": (email or phone).lower(), "name": name or None,
                          "company": fields.get("company_name") or name or None,
                          "role": fields.get("job_title") or None,
                          "email": email.lower() if email else None, "phone": phone,
                          "channel": "whatsapp" if phone else "email",
                          "source": "meta_ads", "meta_lead_id": row.get("id"),
                          "meta_form_id": form_id, "income_range": income_range,
                          "lead_origin": {"platform": row.get("platform"), "form_id": form_id,
                                          "ad_id": ad_id, "ad_name": row.get("ad_name"),
                                          "campaign_name": row.get("campaign_name"),
                                          "lead_id": row.get("id")}})
        return leads


def _parse_graph_time(value: Any) -> Optional[datetime]:
    """created_time de Graph ("2026-10-15T10:00:00+0000") -> datetime con zona; None si no se entiende."""
    if not value:
        return None
    try:
        moment = datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


_API = "https://graph.facebook.com/v20.0"

# Todos los effective_status de un anuncio en Graph v20.0 (para no perder archivados).
_AD_STATUSES = ["ACTIVE", "PAUSED", "DELETED", "PENDING_REVIEW", "DISAPPROVED", "PREAPPROVED",
                "PENDING_BILLING_INFO", "CAMPAIGN_PAUSED", "ARCHIVED", "ADSET_PAUSED",
                "IN_PROCESS", "WITH_ISSUES"]


def today_chile():
    """Fecha de hoy en Chile: el `until` de Insights no depende de la zona del servidor."""
    return datetime.now(ZoneInfo(CHILE["timezone"])).date()

# Campos de contacto estándar de un formulario; cualquier otro es una pregunta propia.
_CONTACT_FIELDS = frozenset({"full_name", "first_name", "last_name", "email", "phone_number",
                             "company_name", "job_title"})
# Palabras que delatan la pregunta de renta (en minúsculas, comparadas con casefold).
_INCOME_TERMS = ("renta", "ingres", "income", "sueldo", "salario")

_LEAD_ACTION_TYPES = (
    "onsite_conversion.lead_grouped", "onsite_conversion.lead",
    "lead", "offsite_conversion.fb_pixel_lead",
)


def _amount(value: Any) -> int:
    try:
        return int(Decimal(str(value or 0)).quantize(Decimal("1")))
    except (InvalidOperation, ValueError):
        return 0


def _ratio(value: Any) -> Optional[float]:
    """CTR de Graph ("1.2345", en %) -> float; None si no viene (no se inventa 0)."""
    try:
        return round(float(Decimal(str(value))), 4) if value not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


def _ad_item(*, ad_id, ad_name, campaign_id, campaign_name, status, post_id, creative,
             spend: int, impressions: int, reach: int, clicks: int, ctr, leads: int) -> Dict[str, Any]:
    """Un anuncio pagado con la forma del contrato; real y mock pasan por aquí."""
    return {"ad_id": ad_id, "ad_name": ad_name, "campaign_id": campaign_id,
            "campaign_name": campaign_name, "status": status, "post_id": post_id,
            "creative": creative, "spend": spend, "impressions": impressions, "reach": reach,
            "clicks": clicks, "ctr": ctr, "leads": leads,
            "cpl": round(spend / leads) if leads else None}


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


def _graph_pages(path: str, token: str, params: Dict[str, Any], max_pages: int = 20,
                 strict: bool = False) -> List[Dict[str, Any]]:
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
            if strict:
                raise RuntimeError("Meta devolvió una lista inválida")
            return out
        if strict and any(not isinstance(x, dict) for x in items):
            raise RuntimeError("Meta devolvió un elemento con forma inválida")
        out.extend(x for x in items if isinstance(x, dict))
        paging = data.get("paging") or {}
        if not isinstance(paging, dict):
            if strict:
                raise RuntimeError("Meta devolvió paginación inválida; no se importa un resultado parcial")
            return out
        cursors = paging.get("cursors") or {}
        next_cursor = cursors.get("after") if isinstance(cursors, dict) else None
        if strict and paging.get("next") and not next_cursor:
            raise RuntimeError("Meta indicó otra página sin cursor; no se importa un resultado parcial")
        if strict and paging.get("next") and next_cursor == cursor:
            raise RuntimeError("Meta repitió el cursor de paginación; no se importa un resultado parcial")
        if not paging.get("next") or not next_cursor or next_cursor == cursor:
            return out
        cursor = next_cursor
    raise RuntimeError("Meta devolvió más páginas que el límite de lectura; no se muestran cifras parciales")




def list_ad_accounts(token: str) -> List[Dict[str, Any]]:
    """Cuentas publicitarias que el token puede ver — para elegir el act_ correcto."""
    items = _graph_pages("me/adaccounts", token, {"fields": "id,name,account_status,currency", "limit": 100})
    return [{"id": a.get("id"), "name": a.get("name"), "status": a.get("account_status"),
             "currency": a.get("currency")}
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
