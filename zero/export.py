"""Export the deliverable — the artifact a client actually receives.

A pipeline run produces qualified leads + their first-touch message. This turns
that into a CSV the operator can hand over (or open in Sheets/Excel). Kept apart
from the pipeline so it's pure and testable: data in, file out.
"""
from __future__ import annotations

import csv
from typing import Any, Dict

_COLUMNS = [
    ("empresa", "company"),
    ("contacto", "name"),
    ("cargo", "role"),
    ("email", "email"),
    ("telefono", "phone"),
    ("canal", "channel"),
    ("score", "score"),
]


_CRM_COLUMNS = [
    ("empresa", "company"),
    ("contacto", "name"),
    ("cargo", "role"),
    ("email", "email"),
    ("telefono", "phone"),
    ("canal", "channel"),
    ("score", "score"),
    ("etapa", "stage"),
]


def crm_to_csv(crm: Any, client: str, path: str) -> int:
    """Write a client's whole CRM book (every lead + its current stage) to `path`."""
    leads = crm.list(client)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([h for h, _ in _CRM_COLUMNS] + ["actualizado"])
        for r in leads:
            w.writerow(
                [r.get(field) if r.get(field) is not None else "" for _, field in _CRM_COLUMNS]
                + [r.get("updated") or ""]
            )
    return len(leads)


def deliverable_to_csv(deliverable: Dict[str, Any], path: str) -> int:
    """Write the qualified leads (+ their outreach message) to `path`. Returns the count."""
    leads = deliverable.get("qualified_leads", [])
    by_company = {m.get("company"): m for m in deliverable.get("outreach", [])}

    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([h for h, _ in _COLUMNS] + ["asunto", "mensaje", "motivos_icp"])
        for ld in leads:
            msg = by_company.get(ld.get("company"), {})
            w.writerow(
                [ld.get(field) if ld.get(field) is not None else "" for _, field in _COLUMNS]
                + [
                    msg.get("subject") or "",
                    msg.get("body") or "",
                    " | ".join(ld.get("icp_reasons") or []),
                ]
            )
    return len(leads)
