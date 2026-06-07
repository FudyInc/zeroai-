"""ICP — Ideal Customer Profile por cliente.

Es la pieza que hace a ZeroAI una "empresa de soluciones": cada cliente define a
QUIÉN le vende y CON QUÉ (su catálogo, zonas de despacho, medidas, restricciones),
y ese perfil viaja en el task hacia PROSPECTOR / QUALIFIER / OUTREACH para que el
motor se adapte a ese negocio en vez de ser genérico.

Política, no mecanismo: aquí solo se normaliza y describe el ICP; la lógica de
scoring/redacción lo *usa* (vive en los prompts + agentes).
"""
from __future__ import annotations

from typing import Any, Dict, List

# Campos del ICP. Todos opcionales: un ICP vacío => criterio B2B genérico.
FIELDS = ("industry", "sells", "buyer_roles", "company_size", "regions",
          "must_have", "exclude", "context")

_LIST_FIELDS = ("buyer_roles", "regions", "must_have", "exclude")


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    # permite "ceo, gerente comercial" como string
    return [p.strip() for p in str(v).split(",") if p.strip()]


def normalize_icp(raw: Any) -> Dict[str, Any]:
    """Acepta lo que venga (dict parcial, None) y devuelve un ICP con forma fija.
    Nunca lanza: un ICP malformado degrada a genérico, no rompe el pipeline."""
    d = raw if isinstance(raw, dict) else {}
    icp: Dict[str, Any] = {}
    for f in FIELDS:
        if f in _LIST_FIELDS:
            icp[f] = _as_list(d.get(f))
        else:
            v = d.get(f)
            icp[f] = str(v).strip() if v not in (None, "") else ""
    return icp


def is_empty(icp: Dict[str, Any]) -> bool:
    icp = normalize_icp(icp)
    return not any(icp[f] for f in FIELDS)


def describe_icp(raw: Any) -> str:
    """Resumen humano de una línea — para notas/logs/UI."""
    icp = normalize_icp(raw)
    if is_empty(icp):
        return "ICP genérico (sin definir)"
    parts: List[str] = []
    if icp["sells"]:
        parts.append(f"vende {icp['sells']}")
    if icp["industry"]:
        parts.append(f"rubro {icp['industry']}")
    if icp["buyer_roles"]:
        parts.append("decisor " + "/".join(icp["buyer_roles"]))
    if icp["regions"]:
        parts.append("zona " + "/".join(icp["regions"]))
    if icp["company_size"]:
        parts.append(f"tamaño {icp['company_size']}")
    if icp["must_have"]:
        parts.append("requiere " + ", ".join(icp["must_have"]))
    return " · ".join(parts) or "ICP genérico (sin definir)"
