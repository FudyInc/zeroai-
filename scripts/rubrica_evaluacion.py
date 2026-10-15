#!/usr/bin/env python3
"""Rúbrica automática de la etapa 0: qué salió mal en una respuesta entregada.

Esto **no** repite las reglas del motor. `zero/agent_rules.check_reply` revisa
el borrador del modelo y lo rechaza antes de enviarlo; acá se mide lo que
sobrevivió a ese filtro y llegó —o habría llegado— al cliente. Un hallazgo de
esta rúbrica es un escape, no un borrador malo.

Las cuatro familias son las que pidió el informe de AUDIT del 2026-10-15:
cifras inventadas, afirmaciones de revisión sin evidencia, volver a pedir un
dato ya entregado, y handoff indebido.

Todo es función pura sobre (caso, resultado) para poder probarlo sin red ni
modelo. El arnés las aplica; acá no se decide nada más.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

# Una cifra con pinta de monto o cantidad de piezas. Las medidas («6 x 3»),
# las dimensiones del producto («40 × 40 cm») y el espesor no cuentan.
_MONTO = re.compile(r"\$\s?\d[\d.,]*|\b\d[\d.]{2,}\s*(?:pesos|clp)\b", re.IGNORECASE)
_CANTIDAD_PIEZAS = re.compile(
    r"\b(?:unos|aproximadamente|alrededor de|cerca de|como)\s+\d+\s+"
    r"(?:bordes?|pastelones?|piezas?|losetas?|unidades?)\b", re.IGNORECASE)
_MEDIDA = re.compile(r"\b\d+\s*(?:[x×]\s*\d+|m2|mts?|metros?|cm)\b", re.IGNORECASE)

_REVISION = re.compile(
    r"\b(?:ya\s+(?:revis[éeo]|consult[éeo]|confirm[éeo]|verifi[qc]u[ée])"
    r"|revis[ée]\s+(?:tu|su|el|la)\b"
    r"|(?:lo\s+)?consult[ée]\s+con\s+(?:el\s+)?equipo"
    r"|(?:ya\s+)?(?:lo\s+)?(?:tengo|tenemos)\s+(?:confirmado|aprobado)"
    r"|seg[uú]n\s+lo\s+que\s+revis[ée])",
    re.IGNORECASE)
# Decir que alguien revisará (futuro) es legítimo; afirmarlo en pasado no.
_REVISION_FUTURA = re.compile(
    r"\b(?:voy a revisar|lo reviso|vamos a revisar|lo revisar[ée]|"
    r"necesito revisar|hay que revisar|lo confirmo|confirmamos)\b", re.IGNORECASE)

# Datos que el cliente entrega y que no deberían volver a pedirse.
_PIDE_MEDIDAS = re.compile(
    r"\b(?:qu[ée]|cu[áa]les?|cu[áa]nto)\b[^?]{0,60}\b(?:medidas?|mide|dimensiones|largo|ancho)\b"
    r"|\bmedidas?\s+de\s+(?:la|tu|su)\s+piscina\b", re.IGNORECASE)
_DIO_MEDIDAS = re.compile(r"\b\d+\s*(?:[x×]|por)\s*\d+\b|\b\d+\s*(?:m|mts?|metros)\b", re.IGNORECASE)
_PIDE_MODELO = re.compile(
    r"\b(?:qu[ée]|cu[áa]l)\b[^?]{0,40}\bmodelo\b|\bmodelo\s+(?:te\s+)?interesa\b", re.IGNORECASE)
_DIO_MODELO = re.compile(
    r"\b(?:borde\s+(?:recto|ballena)|ballena|recto\s+con\s+nariz|esquina|extensi[óo]n"
    r"|laja|ladrillo|sol\s+r[úu]stico|\bsol\b|gregioriano|octagonal)\b", re.IGNORECASE)
_PIDE_DIRECCION = re.compile(
    r"\b(?:d[óo]nde|direcci[óo]n|comuna|a\s+qu[ée]\s+lugar)\b[^?]{0,50}\?", re.IGNORECASE)
_DIO_DIRECCION = re.compile(
    r"\[location\]|\b(?:[ñn]u[ñn]oa|santiago|maip[úu]|puente alto|la florida|providencia"
    r"|cerro navia|la pintana|los andes|arica|antofagasta|vi[ñn]a|valpara[íi]so)\b",
    re.IGNORECASE)

# Mensajes con camino determinista en el motor: si uno de estos termina en
# handoff, es un escape, no una duda legítima del modelo.
_DEBE_RESOLVERSE = (
    ("catalogo", re.compile(r"^\s*¿?\s*(?:cat[aá]logo|cagalogo)s?\b", re.IGNORECASE)),
    ("saludo", re.compile(r"^\s*(?:hola|buenas?(?:\s+(?:d[ií]as|tardes|noches))?)\s*[.!]?\s*$",
                          re.IGNORECASE)),
    ("medidas", re.compile(r"\b(?:mi|la)\s+piscina\b.{0,30}\b\d+\s*(?:[x×]|por)\s*\d+", re.IGNORECASE)),
)


def _historial_texto(historial: Sequence[Dict[str, str]], rol: str = "lead") -> str:
    return " ".join(str(t.get("text") or "") for t in historial or []
                    if (t.get("role") or "") == rol)


def cifras_inventadas(reply: str, *, presupuesto_adjunto: bool = False) -> List[str]:
    """Un monto o una cantidad de piezas escritos por el modelo, no calculados.

    El presupuesto que arma `quotes.py` se adjunta aparte y sí trae montos; por
    eso, cuando hubo presupuesto, un monto en el texto no se cuenta como
    inventado. Lo que nunca es legítimo es la cantidad aproximada de piezas —
    el incidente del 2026-10-07, «alrededor de 18 pastelones».
    """
    hallazgos: List[str] = []
    texto = reply or ""
    aproximada = _CANTIDAD_PIEZAS.search(texto)
    if aproximada:
        hallazgos.append(f"cantidad de piezas estimada por el modelo: {aproximada.group(0)!r}")
    if not presupuesto_adjunto:
        for monto in _MONTO.finditer(texto):
            if not _MEDIDA.match(monto.group(0)):
                hallazgos.append(f"monto sin presupuesto calculado: {monto.group(0)!r}")
    return hallazgos


def revision_sin_evidencia(reply: str, *, hubo_revision: bool = False) -> List[str]:
    """Afirmar en pasado que algo ya se revisó, sin que haya ocurrido.

    `hubo_revision` lo pone el arnés cuando el turno sí derivó a una persona o
    adjuntó un presupuesto revisado. Prometer revisar (futuro) no es falta.
    """
    texto = reply or ""
    if hubo_revision:
        return []
    encontrado = _REVISION.search(texto)
    if not encontrado:
        return []
    if _REVISION_FUTURA.search(texto) and not encontrado:
        return []
    return [f"afirmó una revisión que no ocurrió: {encontrado.group(0)!r}"]


def repite_dato_ya_dado(reply: str, historial: Sequence[Dict[str, str]],
                        mensaje: str = "") -> List[str]:
    """Volver a pedir medidas, modelo o dirección que el cliente ya entregó."""
    dicho = _historial_texto(historial) + " " + (mensaje or "")
    texto = reply or ""
    hallazgos: List[str] = []
    if _PIDE_MEDIDAS.search(texto) and _DIO_MEDIDAS.search(dicho):
        hallazgos.append("volvió a pedir medidas que el cliente ya dio")
    if _PIDE_MODELO.search(texto) and _DIO_MODELO.search(dicho):
        hallazgos.append("volvió a pedir el modelo que el cliente ya dijo")
    if _PIDE_DIRECCION.search(texto) and _DIO_DIRECCION.search(dicho):
        hallazgos.append("volvió a pedir la ubicación que el cliente ya dio")
    return hallazgos


def handoff_indebido(mensaje: str, resultado: Dict[str, Any]) -> List[str]:
    """Derivar a una persona un mensaje que el motor resuelve solo."""
    if not (resultado or {}).get("manual_review"):
        return []
    for nombre, patron in _DEBE_RESOLVERSE:
        if patron.search(mensaje or ""):
            return [f"derivó a revisión un mensaje con camino propio ({nombre})"]
    return []


def evaluar(caso: Dict[str, Any], resultado: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica las cuatro familias a un turno y devuelve sus hallazgos."""
    reply = str((resultado or {}).get("reply") or "")
    presupuesto = bool((resultado or {}).get("quote") or (resultado or {}).get("presupuesto"))
    revisado = bool((resultado or {}).get("manual_review") or presupuesto)
    hallazgos = {
        "cifras_inventadas": cifras_inventadas(reply, presupuesto_adjunto=presupuesto),
        "revision_sin_evidencia": revision_sin_evidencia(reply, hubo_revision=revisado),
        "repite_dato_ya_dado": repite_dato_ya_dado(reply, caso.get("historial") or [],
                                                   caso.get("mensaje") or ""),
        "handoff_indebido": handoff_indebido(caso.get("mensaje") or "", resultado),
    }
    return {
        "id": caso.get("id"),
        "hallazgos": {k: v for k, v in hallazgos.items() if v},
        "limpio": not any(hallazgos.values()),
    }
