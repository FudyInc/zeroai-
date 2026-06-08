"""PITCHWRITER — redacta el pitch de venta, creativo y distinto cada vez.

El problema con las plantillas: un mail obviamente automatizado lo ignoran. Este
agente escribe personalizado al prospecto, con el ángulo que le pases en `notes`,
y VARÍA en cada generación. Vende el servicio de lead-gen (leads B2B calificados).

Mock: ensambla con variación real (random) para que no sea el mismo mensaje. El
modelo real (prompts/pitchwriter.md) lo hace de verdad creativo — con Anthropic o
un modelo local.
"""
from __future__ import annotations

import random
from typing import Any, Dict, Optional, Tuple

from ..contracts import TaskPayload
from .base import BaseAgent


class PitchWriter(BaseAgent):
    name = "PITCHWRITER"
    prompt_file = "pitchwriter.md"

    def _mock_result(self, task: TaskPayload) -> Tuple[Dict[str, Any], str, Optional[str]]:
        p: Dict[str, Any] = task.data.get("prospect") or {}
        notes = (task.data.get("notes") or "").strip()
        name = (p.get("name") or "").strip()
        company = (p.get("company") or "").strip()
        first = name.split()[0] if name else ""
        hi = f"Hola {first}," if first else "Hola,"
        comp = company or "tu empresa"

        hooks = [
            "Voy directo y en corto: la mayoría del tiempo de ventas se va buscando y filtrando prospectos, no vendiendo.",
            f"Vi {comp} y quise escribirte sin rodeos.",
            f"Una pregunta honesta: ¿cuánto le cuesta a {comp} llegar cada semana a empresas que SÍ quieren comprar?",
            "Una sola idea: que tu equipo solo cierre, y nosotros te pasamos los prospectos ya calificados.",
            f"Te escribo porque creo que a {comp} le sirve esto, y prefiero decírtelo en dos líneas.",
        ]
        value = [
            "Te entregamos leads B2B ya calificados: empresa, decisor, contacto verificado y el primer mensaje escrito.",
            "No es una lista fría de 500 — son pocos pero buenos, filtrados por intención y calidad.",
            "Cada lead llega listo para contactar. Tú solo cierras.",
            "Nosotros prospectamos y filtramos; tú recibes solo lo que vale la pena.",
        ]
        ctas = [
            f"¿Te mando 5 de prueba esta semana, gratis y para tu rubro?",
            "¿Lo vemos en 10 minutos por llamada y te muestro ejemplos reales?",
            "Si te hace sentido, respóndeme y te paso una muestra sin compromiso.",
            "¿Te interesa que te muestre 3 ejemplos concretos hoy?",
        ]
        subjects = [
            f"Leads B2B listos para {comp}",
            (f"{first}, " if first else "") + "prospectos que sí compran",
            "Menos prospectar, más cerrar",
            f"5 leads de prueba para {comp}",
            "Te paso clientes, no listas frías",
        ]

        if notes:
            # El correo ARRANCA desde la idea/contexto que dio el usuario (es la base);
            # el modelo real la reescribe creativa, el mock la enmarca tal cual.
            opener = notes[0].upper() + notes[1:]
            if opener[-1] not in ".!?":
                opener += "."
            cuerpo = [hi, "", opener, "", random.choice(value), "", random.choice(ctas), "", "Saludos,"]
        else:
            cuerpo = [hi, "", random.choice(hooks), "", random.choice(value), "", random.choice(ctas), "", "Saludos,"]
        body = "\n".join(cuerpo)
        return {"subject": random.choice(subjects), "body": body}, "done", "pitch generado (mock variado)"
