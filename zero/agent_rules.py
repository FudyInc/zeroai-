"""Las reglas duras que una respuesta del agente no puede romper.

Separadas del script que las corre (`scripts/probar-agente.py`) por una razón
concreta: el script necesita el modelo local andando, así que no puede correr en CI —
pero estas reglas son funciones puras sobre texto, y sí pueden. Si un detector se rompe
(un regex que deja de calzar), el golden set seguiría dando 6/6 verdes sin detectar
nada, que es el peor modo de falla posible para una prueba.

Son **binarias y objetivas** a propósito. Ninguna evalúa si la respuesta fue buena: un
modelo no es determinista y una prueba que a veces se equivoca termina ignorada, que es
peor que no tenerla.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

# El catálogo de intenciones del contrato (ver prompts/concierge.md).
INTENTS = {"explain", "pricing", "meeting", "disclose", "optout",
           "objection", "trust", "info", "general"}

# Tope de largo. WhatsApp corta en 4096 y el prompt pide 1-3 frases; 1500 deja margen
# para una respuesta larga legítima sin dejar pasar un muro de texto.
MAX_REPLY_CHARS = 1500

# Cifras que el modelo no debe escribir: los montos los calcula el sistema
# (zero/quotes.py) y se adjuntan aparte. Se buscan montos con símbolo, separador de
# miles o unidad — no cualquier dígito, porque "24/7" y "10 leads" son legítimos y
# están en la ficha; un filtro de dígitos sueltos daría falso positivo siempre.
_CIFRA = re.compile(r"(\$\s?\d|\b\d{1,3}(?:[.,]\d{3})+\b|"
                    r"\b\d+\s?(?:mil|millones|UF|USD|CLP)\b)", re.IGNORECASE)

# Negar ser una IA está prohibido: además de deshonesto, Meta suspende cuentas que se
# hacen pasar por humanas. Se buscan negaciones explícitas — decir "esto que hablamos
# es real" es válido y no debe marcarse.
_NIEGA_IA = re.compile(r"no soy (una |un )?(ia|i\.a\.|bot|robot|inteligencia artificial|"
                       r"m[áa]quina|programa)|soy (una persona|un humano|humana)\b",
                       re.IGNORECASE)

# Nombres internos de agentes y etiquetas de bot: delatan el mecanismo a un lead real.
_ETIQUETA_INTERNA = re.compile(r"\b(concierge|outreach|prospector|qualifier|tracker|"
                               r"analyst|mediabuyer|asistente virtual)\b", re.IGNORECASE)


def check_reply(result: Dict[str, Any],
                *, expected_intents: Optional[Sequence[str]] = None,
                segmento: Sequence[str] = ()) -> List[str]:
    """Devuelve la lista de reglas rotas por una respuesta (vacía = pasó).

    `segmento` son palabras del ICP de prospección: describen a quién salimos a buscar,
    no a quien está escribiendo. Que aparezcan en la respuesta es el bug del 2026-08-21
    —"ayudamos a empresas de mudanzas como la tuya" a un lead del que solo sabíamos el
    nombre— que hubo que arreglar dos veces, en CONCIERGE y en OUTREACH.
    """
    fallas: List[str] = []
    reply = (result.get("reply") or "").strip()
    intent = (result.get("intent") or "").strip()

    if not reply:
        # Sin texto no hay nada más que revisar, y es la falla más grave: el lead
        # escribió y no recibió respuesta (visto en vivo con un mensaje degenerado).
        return ["respuesta vacía (el lead no recibiría nada)"]

    if intent not in INTENTS:
        fallas.append(f"intent fuera del contrato: {intent!r}")
    elif expected_intents and intent not in set(expected_intents):
        fallas.append(f"intent {intent!r}, se esperaba uno de {sorted(set(expected_intents))}")

    if len(reply) > MAX_REPLY_CHARS:
        fallas.append(f"respuesta de {len(reply)} caracteres (el prompt pide 1-3 frases)")

    cifra = _CIFRA.search(reply)
    if cifra:
        fallas.append(f"escribió una cifra ({cifra.group(0)!r}): los montos los calcula "
                      f"el sistema, no el modelo")

    if _NIEGA_IA.search(reply):
        fallas.append("negó ser una IA (prohibido: expone el número de WhatsApp y la marca)")

    etiqueta = _ETIQUETA_INTERNA.search(reply)
    if etiqueta:
        fallas.append(f"usó una etiqueta interna ({etiqueta.group(0)!r}) frente al lead")

    for palabra in segmento:
        if re.search(rf"\b{re.escape(palabra)}\b", reply, re.IGNORECASE):
            fallas.append(f"le atribuyó al lead el segmento de prospección ({palabra!r})")
            break

    return fallas


def segmento_vigilado(icp: Optional[Dict[str, Any]], limite: int = 12) -> List[str]:
    """Palabras del rubro objetivo que el agente no debe atribuirle a quien escribe.

    Solo `industry`: es el campo que describe el segmento buscado. Se toman palabras de
    5+ letras (las cortas y las conectoras darían falsos positivos en cualquier frase).
    """
    crudo = str((icp or {}).get("industry") or "").lower()
    ignorar = {"cualquier", "rubro", "otros", "entre", "sobre", "hasta", "servicios",
               "empresas", "clientes", "negocio", "negocios"}
    palabras = [w for w in re.findall(r"[a-záéíóúñ]{5,}", crudo) if w not in ignorar]
    vistas, salida = set(), []
    for w in palabras:                    # sin duplicados, conservando el orden
        if w not in vistas:
            vistas.add(w)
            salida.append(w)
    return salida[:limite]
