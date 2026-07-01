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

from ..config import OPUS
from ..contracts import TaskPayload
from .base import BaseAgent


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def _word(text: str, *words: str) -> bool:
    """Whole-word match — a bare 'no' must not fire inside 'bueno'/'necesito'."""
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


# A message that is *only* "no" repeated/elongated ("no", "nooo", "no!", "noo...") —
# WhatsApp shorthand for a flat decline, distinct from "no" used inside a longer
# sentence ("no por ahora", "no tengo presupuesto") which other branches handle.
_ELONGATED_NO_RE = re.compile(r"^no+[\s!¡.]*$")

# A short, *purely* affirmative reply ("dale, vamos", "ok", "sí 👍") — the lead is
# saying yes to *something* we said, but with no other content for CONCIERGE to
# go on. Anchored at the start so it doesn't fire on "no estoy seguro" or similar
# (the trailing `not _word(msg, "no")` guard below covers that too).
_ACCEPT_RE = re.compile(
    r"^(sí|dale|vamos|ok|okey|okay|oki|listo|perfecto|genial|buenísimo|buenisimo|"
    r"bueno|claro|obvio|vale|excelente|de acuerdo|me sirve)\b"
)

# "sí" / "si" alargado ("siii", "siiii", "síii") — variante de WhatsApp del
# afirmativo corto, igual que "nooo" es la variante alargada del "no". Anclado
# al mensaje completo: no dispara dentro de "sin problema" ni "si tienes info".
_ELONGATED_SI_RE = re.compile(r"^s[ií]{2,}[\s!¡.]*$")

# "¿es esto seguro?", "¿esto es confiable?", "no es una estafa, no?" — doubts about
# legitimacy, phrased as "es / esto es / es esto" + seguro/confiable/legítimo/estafa/
# real, with up to ~15 chars between (covers "es esto seguro" word order too).
# Doesn't match "no estoy seguro" — "estoy" isn't the whole word "es".
_TRUST_SAFETY_RE = re.compile(
    r"\b(es|esto es|es esto)\b[^.,;!?]{0,15}\b(seguro|confiable|legítim\w*|legitim\w*|estafa|real)\b"
)


class Concierge(BaseAgent):
    name = "CONCIERGE"
    prompt_file = "concierge.md"
    model = OPUS   # conversación con el lead = la cara del cliente; vale el modelo fuerte

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
              or _word(msg, "no") and len(msg) <= 4
              # "nooo", "no!", "no..." — un "no" elongado/decorado sigue siendo un no
              or _ELONGATED_NO_RE.match(msg)):
            reply = (f"{hi}, sin problema y gracias por avisar. Lo dejo aquí; si más adelante necesitas "
                     f"leads B2B calificados, escríbeme y retomamos. ¡Éxito!")
            intent = "optout"
        elif (_has(msg, "sacaste", "sacaron", "conseguiste", "consiguieron", "mis datos", "spam")
              or _TRUST_SAFETY_RE.search(msg)):
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
        elif (_ACCEPT_RE.match(msg) or _ELONGATED_SI_RE.match(msg)) and not _word(msg, "no"):
            # "dale, vamos" / "ok" / "sí 👍" — sin pregunta ni objeción: el lead dice
            # que sí a algo. Sin oferta pendiente que cumplir (eso lo resuelve el
            # orquestador), avanzamos proponiendo el siguiente paso concreto.
            reply = (f"{hi}, ¡buenísimo! Te paso 3 ejemplos para que veas el nivel — "
                     f"¿te los mando por acá o prefieres que agendemos una llamada corta de 10 min?")
            intent = "accept"
        else:
            reply = (f"{hi}, gracias por escribir. {offer[0].upper() + offer[1:]}. "
                     f"¿Qué te gustaría saber — cómo funciona, precios, o vemos 3 ejemplos?")
            intent = "general"

        return {"reply": reply, "intent": intent}, "done", f"reply drafted ({intent}, mock)"
