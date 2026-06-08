"""Sales pitch composer — the cold email that offers the lead-gen service.

Built from the brand pitch (docs/pitch.md): what you sell in one line, the
"pocos pero buenos" differentiator, and the low-friction ask (10 free trial
leads). Includes a small sample of qualified leads as the demo. Deterministic
(mock-first); the dashboard lets the user edit subject/body before sending.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# A tiny, realistic sample shown inline as the "demo" of the deliverable.
DEFAULT_SAMPLES: List[Dict[str, Any]] = [
    {"company": "AgroNorte", "role": "Jefe de Compras", "contact": "compras@agronorte.cl", "score": 86},
    {"company": "LogiSur", "role": "Gerente de Operaciones", "contact": "+56 9 8123 4567", "score": 81},
    {"company": "Patagonia Foods", "role": "VP Ventas", "contact": "camila@patagoniafoods.cl", "score": 78},
]


def compose_pitch(name: Optional[str] = None, company: Optional[str] = None,
                  samples: Optional[List[Dict[str, Any]]] = None) -> Dict[str, str]:
    """Return {subject, body} — a personalized cold pitch with a demo sample."""
    comp = (company or "").strip()
    greeting = f"Hola {name.strip()}," if name and name.strip() else "Hola,"
    rows = samples or DEFAULT_SAMPLES
    demo = "\n".join(
        f"  • {s['company']} — {s['role']} · {s['contact']} · score {s['score']}"
        for s in rows
    )
    subject = f"Leads B2B calificados para {comp}" if comp else "Leads B2B calificados, listos para contactar"
    body = f"""{greeting}

¿Cuánto tiempo gasta tu equipo buscando y filtrando prospectos antes de poder venderles? En la mayoría de las empresas ahí se va el grueso del tiempo de ventas — no en vender.

Te entregamos leads B2B ya calificados y listos para contactar: empresa, decisor, contacto verificado y el primer mensaje escrito. Tú solo cierras.

No es una lista fría de 500 contactos. Son pocos pero buenos — solo los que pasan un filtro de calidad (score ≥ 70, contacto verificado, sin recontactar a quien ya tocaste).

Así se ve el entregable (muestra):
{demo}

¿Te haría sentido que te mande 10 leads calificados de prueba esta semana, gratis y para tu rubro? Así ves la calidad sin compromiso — solo respóndeme a este correo y te los hago llegar.

Saludos,
"""
    return {"subject": subject, "body": body}
