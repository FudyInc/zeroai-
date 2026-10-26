"""Módulo de atención: lo que el agente de WhatsApp no pudo resolver solo.

Cada caso queda en `memory.knowledge_gaps` (ver `SessionMemory.
add_knowledge_gap`). Desde el dashboard una persona del equipo lo cierra de
una de tres formas:

- **Respuesta**: la escribe una vez. Entra a la ficha del cliente y, además,
  el agente la repite tal cual cuando alguien vuelve a preguntar lo mismo
  (`learned_answer`), sin pasar por el modelo.
- **Sinónimo**: indica que esa frase significa una opción del flujo («los de
  la orilla» = «Bordes de piscina»). Desde ahí el agente la trata como esa
  opción (`learned_alias`).
- **Descartar**: no era una pregunta.

El agente aprende solo de lo que aprueba una persona, nunca de sus propias
respuestas: el historial tiene casos de cifras inventadas y revisiones que no
ocurrieron, y guardarlas las convertiría en doctrina.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional

from .memory import _gap_key

# Tope de la ficha; el mismo que aplica scripts/cargar_empresa.py.
LIMITE_FICHA = 4000
ENCABEZADO = "## Respuestas aprobadas"
FIJAS = "## Respuestas fijas"
# Qué tan parecida debe ser una pregunta nueva a una ya respondida para
# contestarla con esa respuesta. Alto a propósito: una respuesta aprendida
# aplicada a la pregunta equivocada es peor que pasar el caso a una persona.
SIMILITUD_MINIMA = 0.92


def seccion_respuestas(ficha: str) -> str:
    """El bloque de respuestas aprobadas que ya tiene la ficha."""
    if ENCABEZADO not in ficha:
        return ""
    return ficha.split(ENCABEZADO, 1)[1].strip()


def agregar_respuesta(ficha: str, pregunta: str, respuesta: str) -> str:
    """Devuelve la ficha con un par pregunta/respuesta más.

    Si la pregunta ya estaba, se reemplaza su respuesta en vez de duplicarla:
    una ficha con dos respuestas distintas a lo mismo le da al modelo una
    contradicción, que es peor que no tener ninguna.
    """
    entrada = f"- **{pregunta.strip()}** {respuesta.strip()}"
    base = ficha.rstrip()
    if ENCABEZADO not in base:
        return f"{base}\n\n{ENCABEZADO}\n{entrada}\n"
    cabeza, cola = base.split(ENCABEZADO, 1)
    lineas = [l for l in cola.strip().splitlines() if l.strip()]
    marca = f"- **{pregunta.strip()}**"
    lineas = [l for l in lineas if not l.startswith(marca)]
    lineas.append(entrada)
    return f"{cabeza.rstrip()}\n\n{ENCABEZADO}\n" + "\n".join(lineas) + "\n"


def fixed_answer(ficha: str, tema: str) -> Optional[str]:
    """El texto que el equipo dejó en la ficha para `tema`, tal cual.

    Va bajo `## Respuestas fijas`, en un `### <tema>` con el nombre del tema de
    LOSETASCHILE_TEMAS_SIN_INVENTAR (config). Se envía sin pasar por el modelo:
    datos bancarios y montos no se reescriben."""
    if not tema or FIJAS not in (ficha or ""):
        return None
    bloque = ficha.split(FIJAS, 1)[1].split("\n## ", 1)[0]
    for parte in bloque.split("\n### ")[1:]:
        titulo, _, cuerpo = parte.partition("\n")
        if titulo.strip().casefold() == tema.casefold() and cuerpo.strip():
            return cuerpo.strip()
    return None


def _gap(memory, client_id: str, clave: str) -> Optional[Dict[str, Any]]:
    return (memory.clients.get(client_id, {}).get("knowledge_gaps") or {}).get(clave)


def check_answer(memory, client_id: str, clave: str, respuesta: str) -> Optional[str]:
    """Lo que impediría guardar esta respuesta, antes de enviársela a nadie."""
    item = _gap(memory, client_id, clave)
    texto = " ".join(str(respuesta or "").split())
    if not item:
        return "Ese caso ya no existe."
    if not texto:
        return "Escribe la respuesta."
    if item.get("tipo") == "pedido":
        return None   # un pedido no se aprende: no toca la ficha
    nueva = agregar_respuesta(memory.get_client_knowledge(client_id),
                              item.get("pregunta", clave), texto)
    if len(nueva) > LIMITE_FICHA:
        return (f"La ficha quedaría en {len(nueva)} caracteres y el tope es {LIMITE_FICHA}. "
                "Acorta alguna respuesta aprobada antes de agregar esta.")
    return None


def teach_answer(memory, client_id: str, clave: str, respuesta: str) -> Optional[str]:
    """Cierra el caso con la respuesta. Devuelve un motivo si no se pudo.

    Una pregunta queda aprendida (ficha + respuesta exacta para la próxima vez).
    Un pedido solo se marca atendido: la cotización de un cliente nunca debe
    repetirse a otro."""
    error = check_answer(memory, client_id, clave, respuesta)
    if error:
        return error
    item = _gap(memory, client_id, clave)
    texto = " ".join(str(respuesta or "").split())
    if item.get("tipo") == "pedido":
        memory.attend_knowledge_gap(client_id, clave)
        return None
    memory.set_client_knowledge(client_id, agregar_respuesta(
        memory.get_client_knowledge(client_id), item.get("pregunta", clave), texto))
    memory.resolve_knowledge_gap(client_id, clave, texto)
    return None


def choice_options() -> List[Dict[str, Any]]:
    """Las opciones del flujo a las que se puede asociar un sinónimo."""
    from .losetas_polls import CHOICE_PROMPTS
    return [{"pregunta": question, "opciones": list(options)}
            for question, options in CHOICE_PROMPTS.values()]


def teach_alias(memory, client_id: str, clave: str, opcion: str) -> Optional[str]:
    """Enseña que la frase del caso significa `opcion`. Devuelve un motivo si no se pudo."""
    if not _gap(memory, client_id, clave):
        return "Ese caso ya no existe."
    validas = {o for grupo in choice_options() for o in grupo["opciones"]}
    if opcion not in validas:
        return "Elige una de las opciones del flujo."
    memory.alias_knowledge_gap(client_id, clave, opcion)
    return None


def _digits(clave: str) -> list:
    return re.findall(r"\d+", clave)


def _learned(memory, client_id: str, text: str, campo: str) -> Optional[str]:
    clave = _gap_key(text)
    # «2» or «40x40» alone are menu answers or sizes, never a taught question.
    if not clave or len(clave.split()) < 2 or not re.search(r"[a-z]{3}", clave):
        return None
    resueltas = [(k, v) for k, v in (memory.clients.get(client_id, {})
                                     .get("knowledge_gaps") or {}).items()
                 if (v or {}).get("estado") == "resuelta" and v.get(campo)]
    exacta = next((v[campo] for k, v in resueltas if k == clave), None)
    if exacta:
        return exacta
    # Near spellings count; different figures never do: the answer taught for
    # «20 m2» must not be given for «30 m2».
    parecidas = sorted(((difflib.SequenceMatcher(None, clave, k).ratio(), v[campo])
                        for k, v in resueltas
                        if _digits(k) == _digits(clave) and len(k.split()) >= 3),
                       reverse=True)
    if parecidas and parecidas[0][0] >= SIMILITUD_MINIMA:
        return parecidas[0][1]
    return None


def learned_answer(memory, client_id: str, text: str) -> Optional[str]:
    """La respuesta aprobada para esta pregunta, si una persona ya la enseñó."""
    return _learned(memory, client_id, text, "respuesta")


def learned_alias(memory, client_id: str, text: str) -> Optional[str]:
    """La opción del flujo que significa esta frase, si una persona la enseñó."""
    return _learned(memory, client_id, text, "equivale")
