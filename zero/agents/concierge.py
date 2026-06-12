"""CONCIERGE — the conversational agent that handles inbound replies.

When a lead answers (WhatsApp/email), CONCIERGE drafts the response: it answers
questions about the client's business using the ICP/business context, stays
on-brand, and steers toward a meeting. WhatsApp allows free-form replies within
the 24h window after the lead writes, so this is the policy-safe place to converse.

Mock mode is intent-aware (price / what-you-do / meeting / is-this-a-bot / …) so
the conversation is demoable offline; the real model (prompts/concierge.md) does
the same with genuine understanding. It never invents facts beyond the business
context, and it discloses it's an AI assistant if asked (no deception — protects
the client's brand).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from ..contracts import TaskPayload
from .base import BaseAgent


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def _word(text: str, *words: str) -> bool:
    """Whole-word match — a bare 'no' must not fire inside 'bueno'/'necesito'."""
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


class Concierge(BaseAgent):
    name = "CONCIERGE"
    prompt_file = "concierge.md"

    def _mock_result(self, task: TaskPayload) -> Tuple[Dict[str, Any], str, Optional[str]]:
        msg = str(task.data.get("message") or "").lower().strip()
        lead: Dict[str, Any] = task.data.get("lead") or {}
        icp: Dict[str, Any] = task.data.get("icp") or {}

        name = lead.get("name") or ""
        hi = f"Hola {name}".strip() if name else "Hola"
        sells = icp.get("sells")
        offer = f"ayudamos a empresas como la tuya con {sells}" if sells else \
            "te entregamos leads B2B ya calificados, listos para contactar"

        company = lead.get("company") or "tu empresa"

        # Order matters: the closing/defensive intents go first (a "no me interesa"
        # that also mentions "precio" is still an opt-out), then the buying ones.
        if _has(msg, "robot", "humano", "persona", "eres ia", "eres un bot", "es un bot", "automático"):
            reply = (f"{hi}, buena pregunta — soy el asistente con IA del equipo. "
                     f"Estoy para ayudarte rápido y, si prefieres, te paso con una persona cuando quieras. "
                     f"¿En qué te ayudo?")
            intent = "disclose"
        elif (_has(msg, "no me interesa", "no gracias", "no, gracias", "no quiero",
                   "dejen de", "deja de", "no insist", "stop", "dar de baja", "darme de baja")
              # interés negado en cualquier forma: "no nos interesa", "no estamos interesados"
              or re.search(r"\bno\b[^.,;!?]{0,20}\binteresa", msg)
              or _word(msg, "no") and len(msg) <= 4):
            reply = (f"{hi}, sin problema y gracias por avisar. Lo dejo aquí; si más adelante necesitas "
                     f"leads B2B calificados, escríbeme y retomamos. ¡Éxito!")
            intent = "optout"
        elif _has(msg, "sacaste", "sacaron", "conseguiste", "consiguieron", "mis datos", "spam"):
            reply = (f"{hi}, justa pregunta: tu contacto aparece en información pública de "
                     f"{company} (su sitio web). Te escribí porque creí que podía aportarles; "
                     f"si prefieres que no te contacte más, lo borro y listo. ¿Te cuento en una "
                     f"línea de qué se trataba?")
            intent = "trust"
        elif _has(msg, "ya tenemos", "ya trabajamos", "ya contamos", "proveedor",
                  "caro", "cara", "costoso", "no hay presupuesto", "sin presupuesto",
                  "no tengo presupuesto", "sin plata", "no tenemos presupuesto"):
            if _has(msg, "caro", "cara", "costoso", "presupuesto"):
                reply = (f"{hi}, te entiendo — por eso el plan se arma según el volumen que necesites, "
                         f"y pagas por leads calificados, no por promesas. ¿Te muestro 3 ejemplos "
                         f"reales para que evalúes si el valor está?")
            else:
                reply = (f"{hi}, entiendo, qué bueno que ya lo tengan cubierto. Si algún día quieres "
                         f"comparar calidad de leads como segunda fuente, encantado de mostrarte "
                         f"3 ejemplos sin compromiso. ¿Te los dejo?")
            intent = "objection"
        elif (_word(msg, "mándame", "mandame", "mándenme", "mandenme", "manda", "manden",
                    "envíame", "enviame", "envía", "envia", "envíen", "envien")
              or _has(msg, "más información", "mas información", "más info", "mas info",
                      "al correo", "por correo", "por email", "un resumen")):
            reply = (f"{hi}, claro — te preparo un resumen corto con cómo funciona y 3 ejemplos. "
                     f"¿Te lo mando por acá o prefieres por correo?")
            intent = "info"
        elif _has(msg, "precio", "costo", "cuánto", "cuanto", "tarifa", "plan"):
            reply = (f"{hi}, el plan se arma según el volumen de leads que necesites; "
                     f"hay opciones desde un tier de entrada. ¿Te paso una propuesta corta a tu medida "
                     f"o prefieres verlo en una llamada de 10 min?")
            intent = "pricing"
        elif _has(msg, "qué hacen", "que hacen", "cómo funciona", "como funciona", "servicio",
                  "qué es", "que es", "detalle"):
            reply = (f"{hi}, en simple: {offer}. Calificamos cada uno contra tu perfil ideal "
                     f"y te llegan listos para contactar. ¿Te muestro 3 de ejemplo?")
            intent = "explain"
        elif _has(msg, "reunión", "reunion", "agendar", "llamada", "cuándo", "cuando",
                  "agenda", "meeting", "interesa") or _word(msg, "hora"):
            reply = (f"{hi}, genial. ¿Te acomoda esta semana? Puedo proponerte hoy o mañana "
                     f"en la tarde — dime qué horario te sirve y lo dejamos agendado.")
            intent = "meeting"
        else:
            reply = (f"{hi}, gracias por escribir. {offer[0].upper() + offer[1:]}. "
                     f"¿Qué te gustaría saber — cómo funciona, precios, o vemos 3 ejemplos?")
            intent = "general"

        return {"reply": reply, "intent": intent}, "done", f"reply drafted ({intent}, mock)"
