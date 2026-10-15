"""Importación de Lead Ads (formularios instantáneos de Instagram / Meta) al CRM.

Mecanismo: lee los formularios asignados al cliente, deduplica contra el CRM,
respeta el opt-out y deja los leads nuevos en etapa `new`. La política (renta
mínima, cadencia) vive en `config.py`.

Sin Meta conectado esto NO cae a mock: responde con el motivo (CLAUDE.md,
principio 1). Los errores son `LeadAdsError`; `ClienteNoEncontrado` es el caso
de cliente inexistente, para que quien llama lo distinga.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from .config import LEAD_ADS_MIN_INCOME_CLP
from .crm import BLOCK_TAG
from .metaads import make_metaads


class LeadAdsError(Exception):
    """La importación no pudo correr; el mensaje es apto para mostrarse."""


class ClienteNoEncontrado(LeadAdsError):
    """El cliente no existe en la memoria."""


# --- renta declarada ------------------------------------------------------------
_NUM = re.compile(r"(\d{1,3}(?:[.,]\d{3})+|\d+(?:[.,]\d+)?)\s*"
                  r"(millones|millon|mill|mm|m|mil|k)?(?![a-z])")
_FACTOR = {"millones": 1_000_000, "millon": 1_000_000, "mill": 1_000_000, "mm": 1_000_000,
           "m": 1_000_000, "mil": 1_000, "k": 1_000}
_MAX_WORDS = ("menos de", "menos que", "o menos", "hasta", "bajo", "inferior", "maximo", "no mas de", "<")
_MIN_WORDS = ("mas de", "mas que", "sobre", "desde", "superior", "mayor", "o mas", "+", "en adelante",
              "minimo", "al menos", "arriba de", "a partir", ">")


def _plain(text: str) -> str:
    nfd = unicodedata.normalize("NFD", str(text).casefold())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def parse_income_range(text: Any) -> Tuple[Optional[int], Optional[int]]:
    """Renta mensual en CLP declarada en el formulario -> (mínimo, máximo).

    Tolera "Más de $3.000.000", "$2.000.000 - $3.000.000", "Entre 2 y 3 millones",
    "3M", "+3M", "Menos de $1.000.000", "3.000.000 o más". Un solo monto sin
    palabra de dirección es exacto (mínimo = máximo). Si no se entiende: (None, None).
    También "5 millones o menos", "hasta $3.000.000", "como máximo 3 millones" (tope),
    "2 millones y medio" / "2 y medio millones" (2,5 M).

    Política ya vigente (la aplica `income_ok`): un rango que cruza el umbral usa su
    mínimo, así "Entre 2 y 3 millones" con umbral de 3 M queda bajo el umbral.
    """
    t = _plain(text or "")
    t = re.sub(r"(\d+)\s*(millones|millon|mill)\s+y\s+medio", r"\1,5 \2", t)
    t = re.sub(r"(\d+)\s+y\s+medio\s+(millones|millon|mill)", r"\1,5 \2", t)
    found = [(m.group(1), m.group(2)) for m in _NUM.finditer(t)]
    values = []
    suffix = None
    for raw, unit in reversed(found):          # un monto sin unidad hereda la del siguiente
        suffix = unit or suffix
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw):
            number = float(re.sub(r"[.,]", "", raw))
        else:
            number = float(raw.replace(",", "."))
        if unit or number >= 1000:
            amount = number * _FACTOR.get(unit, 1)
        elif suffix:
            amount = number * _FACTOR[suffix]
        else:
            return None, None                   # "3" a secas: no se sabe si son millones
        values.append(int(round(amount)))
    values.reverse()
    if not values:
        return None, None
    if len(values) >= 2:
        return min(values[0], values[1]), max(values[0], values[1])
    only = values[0]
    has_max = any(w in t for w in _MAX_WORDS)
    has_min = any(w in t for w in _MIN_WORDS) and "no mas de" not in t
    if has_max and not has_min:
        return None, only
    if has_min and not has_max:
        return only, None
    if has_min and has_max:
        return None, None
    return only, only


def min_income_clp(client: str) -> Optional[int]:
    return LEAD_ADS_MIN_INCOME_CLP.get(client)


def income_ok(text: Any, client: str) -> Optional[bool]:
    """True = declara renta >= umbral del cliente; False = bajo; None = sin umbral
    o no se pudo leer."""
    threshold = min_income_clp(client)
    if threshold is None or not str(text or "").strip():
        return None
    low, high = parse_income_range(text)
    if low is not None:
        return low >= threshold
    if high is not None and high <= threshold:
        return False
    return None


# --- importación ----------------------------------------------------------------
def _digits(value: Any) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


def _record_sync(memory, client: str, result: Dict[str, Any]) -> None:
    """Guarda el resultado de la última importación en la config del cliente.

    La importación tarda segundos (Graph) y `save()` escribe el snapshot entero:
    por eso se recarga JUSTO antes y se cambia solo `lead_sync`, para no borrar lo
    que el API haya escrito entretanto. Los cursores de la corrida anterior se
    conservan si esta no trae los suyos (p. ej. en un error)."""
    memory.reload()
    cfg = dict(memory.get_client_meta(client))
    previous = cfg.get("lead_sync") or {}
    sync = {"at": datetime.now(timezone.utc).isoformat(), **result}
    if "since" not in sync and previous.get("since"):
        sync["since"] = previous["since"]
    cfg["lead_sync"] = sync
    memory.set_client_meta(client, cfg)
    memory.save()


def import_lead_ads(client: str, memory, crm) -> Dict[str, Any]:
    """Importa los formularios del cliente a su CRM y devuelve el resumen.

    `crm` puede ser el CRM o una función sin argumentos que lo abre: así un
    cliente sin Meta conectado falla antes de tocar el CRM.

    Cursor: `lead_sync.since` guarda, por formulario, el `created_time` más reciente
    leído sin error. Es por formulario (no global) para que un formulario caído no
    retenga el cursor de los demás ni se pierdan sus leads al recuperarse.
    """
    if client not in memory.clients:
        raise ClienteNoEncontrado("cliente no encontrado")
    try:
        summary = _importar(client, memory, crm)
    except Exception as e:      # noqa: BLE001 — el fallo queda a la vista en lead_sync
        try:
            _record_sync(memory, client, {"error": str(e)})
        except Exception as record_error:   # noqa: BLE001 — no ocultar el error original
            e.add_note(f"además falló guardar lead_sync: {record_error}")
        raise
    since = summary.pop("since", None)
    record = {k: v for k, v in summary.items() if k != "client"}
    if since:
        record["since"] = since
    _record_sync(memory, client, record)
    return summary


def _importar(client: str, memory, crm) -> Dict[str, Any]:
    cfg = dict(memory.get_client_meta(client))
    if not cfg.get("lead_form_ids"):
        raise LeadAdsError("Asigna al menos un formulario Lead Ads a este negocio.")
    src = make_metaads(cfg, client_id=client)
    if not getattr(src, "live", False):
        raise LeadAdsError(
            "Meta Ads no está conectado para este negocio: configura su token y cuenta publicitaria.")
    try:
        leads = src.lead_ads(client, cfg, since=(cfg.get("lead_sync") or {}).get("since"))
    except RuntimeError as e:
        raise LeadAdsError(str(e)) from e
    failed_forms = list(getattr(src, "failed_forms", None) or [])
    since = dict((cfg.get("lead_sync") or {}).get("since") or {})
    since.update(getattr(src, "cursors", None) or {})
    crm = crm() if callable(crm) else crm

    by_key, by_email, by_phone = {}, {}, {}

    def index_contact(rec):
        key = str(rec.get("key") or "").lower()
        email = str(rec.get("email") or "").strip().lower()
        phone = _digits(rec.get("phone"))
        if key:
            by_key.setdefault(key, []).append(rec)
        if email:
            by_email.setdefault(email, []).append(rec)
        if phone:
            by_phone.setdefault(phone, []).append(rec)

    for rec in crm.list(client):
        index_contact(rec)

    def add_tags(rec, instagram):
        tags = rec.setdefault("tags", [])
        for tag in ("Meta Ads", "Instagram Ads") if instagram else ("Meta Ads",):
            if tag not in tags:
                tags.append(tag)

    created = skipped = already_present = 0
    changed = False
    for lead in leads:
        origin = lead.get("lead_origin") or {}
        instagram = origin.get("platform") == "ig" or cfg.get("lead_platform") == "instagram"
        lead["source"] = "instagram_ads" if instagram else "meta_ads"
        lead["income_ok"] = income_ok(lead.get("income_range"), client)
        key = str(lead.get("key") or "").lower()
        email = str(lead.get("email") or "").strip().lower()
        phone = _digits(lead.get("phone"))
        matches = by_key.get(key, []) + by_email.get(email, []) + by_phone.get(phone, [])
        if any(BLOCK_TAG in (rec.get("tags") or []) for rec in matches):
            skipped += 1
            continue
        if matches:
            # Enriquece la ficha existente sin pisar nada que ya tenga valor (puede ser
            # edición del operador o un lead B2B): solo completa contacto vacío y deja
            # la renta/origen del formulario, que es la fuente de verdad. Nunca cambia
            # etapa, source ni channel. Sin cambios no la toca (ni `updated`).
            rec = matches[0]
            patch = {f: lead[f] for f in ("name", "company", "role", "email", "phone")
                     if lead.get(f) and not rec.get(f)}
            patch.update({f: lead.get(f) for f in ("income_range", "income_ok", "lead_origin")
                          if lead.get(f) is not None and lead.get(f) != rec.get(f)})
            before = list(rec.get("tags") or [])
            if patch:
                rec = crm.upsert(client, {**patch, "key": rec.get("key")})
            add_tags(rec, instagram)
            if patch or rec["tags"] != before:
                changed = True
            already_present += 1
            continue
        rec = crm.upsert(client, lead, stage="new")
        add_tags(rec, instagram)
        crm.log(client, rec["key"], "meta_ads", f"formulario {lead.get('meta_form_id')}")
        index_contact(rec)
        created += 1
        changed = True
    if changed:
        crm.save()
    summary = {"client": client, "read": len(leads), "created": created,
               "already_present": already_present, "skipped_blocked": skipped}
    if failed_forms:
        summary["failed_forms"] = failed_forms
    if since:
        summary["since"] = since
    return summary
