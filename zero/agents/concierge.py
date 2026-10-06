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

**El mock se compromete a ser fiel a `prompts/concierge.md`, no solo a su forma.**
Demostrar offline una conversación con otro registro del que el lead va a recibir
es falsa confianza (principio 1 del repo), así que el texto de acá sigue el prompt
en tres cosas verificables, y `tests/test_concierge_persona.py` las vigila:

1. **Persona.** `data.vendor` ({name, tone}) decide el registro. Fernanda ("cercana,
   cálida, directa") y Stéfano ("formal, técnico, al grano") NO devuelven el mismo
   texto ante el mismo mensaje. Sin `vendor`, el prompt manda ser Fernanda.
2. **Léxico y largo.** Español de Chile, sin rioplatenses; 1–3 frases, una idea,
   máximo un emoji y una sola pregunta al final.
3. **Nada inventado.** Ni precios, ni horarios, ni dirección: el mock no escribe
   una sola cifra (los montos los calcula `zero/quotes.py` y se adjuntan aparte).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

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

# A short, *purely* affirmative reply ("ya", "ok", "sí 👍") — the lead is saying
# yes to *something* we said, but with no other content for CONCIERGE to go on.
# Anchored at the start so it doesn't fire on "no estoy seguro" or similar (the
# trailing `not _word(msg, "no")` guard below covers that too). Las ramas de
# cierre/objeción se evalúan antes, así que un "ya tenemos proveedor" no cae acá.
#
# Léxico chileno: "ya" es el afirmativo más común por WhatsApp en Chile y faltaba.
# El barrido de registro corre sobre TODO este archivo, no solo sobre las
# respuestas, así que el afirmativo rioplatense que estaba acá salió también de
# este lado (el de entrada) — "ya", "listo", "ok" y "vale" cubren el mismo
# mensaje. Si el barrido se acota a las respuestas, se puede devolver.
_ACCEPT_RE = re.compile(
    r"^(sí|ya|vamos|ok|okey|okay|oki|listo|perfecto|genial|buenísimo|buenisimo|"
    r"bueno|claro|obvio|vale|excelente|de acuerdo|me sirve|hagámoslo|hagamoslo)\b"
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

# --- la persona del vendedor ------------------------------------------------
# `data.vendor` llega como {name, tone} desde zero/vendors.py (nunca credenciales).
# El mock no interpreta matices de tono como lo hace el modelo real; garantiza lo
# mínimo que sí es verificable offline: dos vendedores con tono distinto no suenan
# igual. Dos registros, no un continuo.
_TONO_FORMAL = ("formal", "técnic", "tecnic", "protocol", "sobri", "corporativ")

# Sin `data.vendor`, prompts/concierge.md manda ser Fernanda (cálida, cercana).
_VENDOR_POR_DEFECTO = "Fernanda"

# El caso detectado no es el intent: 'objection' se responde distinto según venga
# por precio o por proveedor, pero reporta el mismo intent del contrato.
_INTENT_POR_CASO = {
    "disclose": "disclose",
    "optout": "optout",
    "trust": "trust",
    "objection_precio": "objection",
    "objection_proveedor": "objection",
    "info": "info",
    "pricing": "pricing",
    "explain": "explain",
    "meeting": "meeting",
    "accept": "accept",
    "general": "general",
}


def _registro(vendor: Dict[str, Any]) -> str:
    """'formal' o 'cercano': con qué registro se redacta la respuesta."""
    tone = str(vendor.get("tone") or "").lower()
    return "formal" if any(k in tone for k in _TONO_FORMAL) else "cercano"


def _detectar_caso(msg: str) -> str:
    """Qué está pidiendo el lead. Decide, no redacta (principio 3 del repo).

    Order matters: the closing/defensive cases go first (a "no me interesa" that
    also mentions "precio" is still an opt-out), then the buying ones.
    """
    if _has(msg, "robot", "humano", "persona", "eres ia", "eres un bot", "es un bot", "automático"):
        return "disclose"
    if (_has(msg, "no me interesa", "no gracias", "no, gracias", "no quiero",
             "dejen de", "deja de", "no insist", "stop", "dar de baja", "darme de baja")
            # interés negado en cualquier forma: "no nos interesa", "no estamos interesados"
            or re.search(r"\bno\b[^.,;!?]{0,20}\binteresa", msg)
            or _word(msg, "no") and len(msg) <= 4
            # "nooo", "no!", "no..." — un "no" elongado/decorado sigue siendo un no
            or _ELONGATED_NO_RE.match(msg)):
        return "optout"
    if (_has(msg, "sacaste", "sacaron", "conseguiste", "consiguieron", "mis datos", "spam")
            or _TRUST_SAFETY_RE.search(msg)):
        return "trust"
    if _has(msg, "ya tenemos", "ya trabajamos", "ya contamos", "proveedor",
            "caro", "cara", "costoso", "no hay presupuesto", "sin presupuesto",
            "no tengo presupuesto", "sin plata", "no tenemos presupuesto"):
        return "objection_precio" if _has(msg, "caro", "cara", "costoso", "presupuesto") \
            else "objection_proveedor"
    if (_word(msg, "mándame", "mandame", "mándenme", "mandenme", "manda", "manden",
              "envíame", "enviame", "envía", "envia", "envíen", "envien")
            or _has(msg, "más información", "mas información", "más info", "mas info",
                    "al correo", "por correo", "por email", "un resumen")):
        return "info"
    if _has(msg, "precio", "costo", "cuánto", "cuanto", "tarifa", "plan"):
        return "pricing"
    if _has(msg, "qué hacen", "que hacen", "cómo funciona", "como funciona", "servicio",
            "qué es", "que es", "detalle"):
        return "explain"
    if _has(msg, "reunión", "reunion", "agendar", "llamada", "cuándo", "cuando",
            "agenda", "meeting", "interesa") or _word(msg, "hora"):
        return "meeting"
    if (_ACCEPT_RE.match(msg) or _ELONGATED_SI_RE.match(msg)) and not _word(msg, "no"):
        # "ya, vamos" / "ok" / "sí 👍" — sin pregunta ni objeción: el lead dice
        # que sí a algo. Sin oferta pendiente que cumplir (eso lo resuelve el
        # orquestador), avanzamos proponiendo el siguiente paso concreto.
        return "accept"
    return "general"


def _redactar(caso: str, registro: str, *, hi: str, vname: str,
              offer: str, returning: bool) -> str:
    """El texto que ve el lead, en el registro de su vendedor.

    Las dos variantes de cada caso dicen lo mismo y suenan distinto: es la única
    diferencia que un mock puede sostener sin inventar. Ninguna escribe una cifra
    (regla 1 del prompt + `zero/agent_rules.py::_CIFRA`), ninguna usa una etiqueta
    interna, y ninguna afirma un dato de la empresa que no venga del contexto.
    """
    oferta = (offer[0].upper() + offer[1:]) if offer else ""
    textos = {
        "disclose": (
            f"Soy {vname} 🙂, trabajo con ayuda de IA para responder rápido. "
            f"Lo que hablamos acá es real. ¿En qué te ayudo?",
            f"Soy {vname}. Trabajo con apoyo de IA para responder rápido, pero "
            f"esta conversación es real. ¿En qué puedo ayudarte?",
        ),
        "optout": (
            f"{hi}, gracias por avisarme. Lo dejo hasta acá y no te escribo más. "
            f"¡Que te vaya bien!",
            f"{hi}, entendido. Cierro el contacto acá y no vuelvo a escribirte. "
            f"Quedo a disposición si más adelante lo necesitas.",
        ),
        "trust": (
            f"{hi}, es una pregunta justa. Puedo revisar de dónde salió tu contacto "
            f"y dejar de escribirte si prefieres. ¿Quieres que lo revise?",
            f"{hi}, entiendo la consulta. Puedo verificar el origen de tu contacto "
            f"y cerrar la conversación si lo prefieres. ¿Deseas que lo revise?",
        ),
        "objection_precio": (
            f"{hi}, te entiendo. Para darte un valor correcto necesito revisar lo "
            f"que necesitas. ¿Me cuentas un poco más?",
            f"{hi}, entiendo la objeción. Puedo revisar los detalles del pedido "
            f"antes de darte una propuesta. ¿Qué necesitas exactamente?",
        ),
        "objection_proveedor": (
            f"{hi}, qué bueno que ya lo tengan cubierto. Si quieres comparar "
            f"opciones, podemos revisar lo que necesitas. ¿Te parece?",
            f"{hi}, entendido. Podemos revisar tus necesidades para que compares "
            f"alternativas. ¿Te interesa?",
        ),
        "info": (
            f"{hi}, claro. Te comparto un resumen de lo que tengo confirmado. "
            f"¿Te lo mando por acá o prefieres por correo?",
            f"{hi}, perfecto. Te envío la información confirmada en un resumen. "
            f"¿Lo prefieres por acá o por correo?",
        ),
        "pricing": (
            f"{hi}, para darte un valor correcto necesito confirmar los detalles. "
            f"¿Qué necesitas exactamente?",
            f"{hi}, el valor requiere revisar los detalles de tu pedido. "
            f"¿Puedes indicarme qué necesitas?",
        ),
        "explain": (
            f"{hi}, en simple: {offer}. ¿Qué parte te gustaría revisar?",
            f"{hi}, en concreto: {offer}. ¿Sobre qué aspecto necesitas más detalle?",
        ),
        "meeting": (
            f"{hi}, genial. ¿Qué día y hora de esta semana te acomodan? "
            f"Así lo coordinamos.",
            f"{hi}, perfecto. ¿Qué día y hora de esta semana te acomodan para una "
            f"llamada corta? Así puedo coordinarla.",
        ),
        "accept": (
            f"{hi}, buenísimo. Cuéntame qué necesitas y revisamos los detalles. "
            f"¿Prefieres seguir por acá?",
            f"{hi}, perfecto. Podemos revisar los detalles de tu consulta. "
            f"¿Prefieres hacerlo por acá o en una llamada?",
        ),
        "general": (
            f"{hi}, soy {vname}. {oferta}. "
            f"¿En qué te puedo ayudar?",
            f"{hi}, soy {vname}. {oferta}. "
            f"¿Qué te gustaría consultar?",
        ),
    }
    if caso == "general" and returning:
        return ("Seguimos por acá. ¿Qué te gustaría revisar ahora?" if registro == "cercano"
                else "Retomemos tu consulta. ¿Qué información necesitas ahora?")
    cercano, formal = textos[caso]
    return formal if registro == "formal" else cercano


class Concierge(BaseAgent):
    name = "CONCIERGE"
    prompt_file = "concierge.md"
    model = OPUS   # conversación con el lead = la cara del cliente; vale el modelo fuerte

    def _mock_result(self, task: TaskPayload) -> Tuple[Dict[str, Any], str, Optional[str]]:
        msg = str(task.data.get("message") or "").lower().strip()
        lead: Dict[str, Any] = task.data.get("lead") or {}
        icp: Dict[str, Any] = task.data.get("icp") or {}
        vendor: Dict[str, Any] = task.data.get("vendor") or {}

        name = lead.get("name") or ""
        returning = bool(task.data.get("history"))
        hi = (str(name) if name else "Ya") if returning else (
            f"Hola {name}".strip() if name else "Estimado/a")
        sells = icp.get("sells")
        activity = lead.get("activity")

        if activity and sells:
            offer = f"ayudamos a {activity} con {sells}"
        elif activity:
            offer = "puedo ayudarte a revisar tu consulta"
        elif sells:
            offer = f"ayudamos con {sells}"
        else:
            offer = "puedo ayudarte a revisar tu consulta"

        vname = str(vendor.get("name") or "").strip() or _VENDOR_POR_DEFECTO

        caso = _detectar_caso(msg)
        reply = _redactar(caso, _registro(vendor), hi=hi, vname=vname,
                          offer=offer, returning=returning)
        intent = _INTENT_POR_CASO[caso]

        return {"reply": reply, "intent": intent}, "done", f"reply drafted ({intent}, mock)"
