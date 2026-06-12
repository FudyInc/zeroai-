"""MEDIABUYER — gestor de campañas Meta Ads con Claude.

Analiza las campañas de un cliente (CPL, gasto, leads, zona) contra el CPL objetivo
del mercado chileno (foco Santiago) y propone un plan de gestión: escalar las de
mejor CPL, pausar/realojar las de CPL alto, priorizar leads y geo Santiago.

Recomienda; NO gasta. Aplicar cambios es una acción aparte y confirmada, y solo
cuando Meta esté conectado de verdad. Mock determinista para construir/demostrar;
el modelo real (prompts/mediabuyer.md) razona mejor sobre el caso.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..contracts import TaskPayload
from .base import BaseAgent


class MediaBuyer(BaseAgent):
    name = "MEDIABUYER"
    prompt_file = "mediabuyer.md"

    def _mock_result(self, task: TaskPayload) -> Tuple[Dict[str, Any], str, Optional[str]]:
        camps: List[Dict[str, Any]] = list(task.data.get("campaigns") or [])
        good = int(task.data.get("good_cpl_clp") or 6000)

        recs: List[Dict[str, Any]] = []
        best = None
        best_cpl = None
        for c in camps:
            cpl = c.get("cpl_clp") or 0
            leads = c.get("leads") or 0
            status = c.get("status")
            obj = c.get("objective")
            region = c.get("region") or "Santiago (RM)"
            if status == "active" and leads and cpl <= good:
                action = "scale"
                reason = f"CPL ${cpl:,} bajo el objetivo (${good:,}). Subí presupuesto manteniendo {region}."
                if best is None or cpl < best_cpl:
                    best, best_cpl = c, cpl
            elif status == "active" and leads and cpl > good:
                action = "reallocate"
                reason = f"CPL ${cpl:,} sobre el objetivo (${good:,}). Bajá presupuesto y realojá a la de mejor CPL."
            elif status == "active" and obj != "OUTCOME_LEADS" and not leads:
                action = "reallocate"
                reason = "No trae leads. Realojá el gasto a campañas de leads en Santiago."
            elif status == "active" and obj == "OUTCOME_LEADS" and not leads:
                # leads=0 y cpl=0: activa pero sin resultados todavía (p.ej. insights
                # de Meta aún no conectados) — no es "rendimiento aceptable", es "sin dato".
                action = "keep"
                reason = "Activa pero sin leads reportados todavía. Esperá unos días o revisá que los insights de Meta estén conectados."
            elif status == "paused":
                action = "keep"
                reason = "Pausada. Reactivá solo si liberás presupuesto de una de CPL alto."
            else:
                action = "keep"
                reason = "Rendimiento aceptable. Sin cambios por ahora."
            recs.append({"campaign_id": c.get("id"), "name": c.get("name"), "action": action, "reason": reason})

        if best:
            plan = (f"Foco leads + Santiago. Escalá «{best['name']}» (mejor CPL ${best_cpl:,}), "
                    f"realojá el gasto de las de CPL > ${good:,}, y pausá lo que no trae leads. "
                    f"Mantené el objetivo de CPL ≤ ${good:,} para Chile.")
        else:
            plan = (f"Ninguna campaña está bajo el CPL objetivo (${good:,}). Concentrá presupuesto en "
                    f"una sola campaña de leads en Santiago y optimizá creativos antes de escalar.")

        return {"recommendations": recs, "plan": plan}, "done", f"{len(recs)} recomendaciones (mock)"
