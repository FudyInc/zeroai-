"""Agente de PoolEdge: el modelo conduce la conversación; el código ejecuta y protege.

Diego, 2026-11-20: «no hay que seguir un orden, hay que entender la conversación y
responder en base a eso». El flujo anterior respondía con pasos fijos antes de que
el modelo leyera el mensaje y lo recortaba a 1.600 caracteres de ficha y 6 turnos.
Aquí el modelo ve el chat completo —también lo que el equipo escribió a mano— y la
ficha completa, y devuelve una respuesta más las acciones que quiere.

El código conserva lo que no puede fallar:

- Las cifras del presupuesto las calcula el código y el borrador va al grupo
  interno; al cliente no le llega un presupuesto automático.
- La dirección, el mapa, el catálogo y la gama los pone el código, no el modelo.
- `revisar_respuesta` bloquea montos que no están en la lista, direcciones
  inventadas, plazos sin respaldo, nombres del cliente, avisos de «lo reviso»,
  menús numerados y la palabra «bot». Un bloqueo se corrige una vez; si persiste,
  el mensaje queda en Atención sin responder (silencio antes que error).

`responder` devuelve el mismo `res` que consumía el orquestador del flujo anterior,
así el envío, el grupo de revisión y las comprobaciones de toma manual no cambian.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from .config import LOSETASCHILE_AGENT, LOSETASCHILE_PAVER_PRICE_IDS
from .losetas_color import COLOR_CATALOG_IMAGE_PATH
from .losetas_polls import FACTORY_ADDRESS, FACTORY_MAP_URL
from .quotes import compute_quote, normalize_pricing
from .whatsapp_greeting import whatsapp_greeting

UBICACION = f"Nuestra fábrica está en {FACTORY_ADDRESS}.\nUbicación en Maps: {FACTORY_MAP_URL}"

BORDES = {
    "Borde recto con nariz 50x50": "borde-recto-nariz-50x50",
    "Borde ballena 50x40": "borde-ballena-50x40",
    "Borde ballena nariz 50x50": "borde-ballena-nariz-50x50",
}
ESQUINA = "esquina-piscina-50x50"
# El ballena 50x40 lleva su propia esquina (así cotiza Diego); los de 50x50, la de piscina.
ESQUINA_DE = {"borde-ballena-50x40": "esquina-borde-ballena-50x40",
              "borde-ballena-nariz-50x50": "esquina-ballena-nariz-50x50"}
# Ancho que ocupa el borde hacia afuera de la piscina, para ubicar la extensión.
ANCHO_BORDE = {"borde-recto-nariz-50x50": Decimal("0.5"), "borde-ballena-50x40": Decimal("0.4"),
               "borde-ballena-nariz-50x50": Decimal("0.5")}
EXTENSION = "extension-borde-piscina"
# Kg por pieza de la hoja PRECIOS PRODUCTOS del Excel de Diego (2026-11-22). Sin peso de
# alguna pieza del pedido, no se informa el total.
PESO_KG = {"borde-recto-nariz-50x50": 15, "borde-ballena-50x40": 13,
           "borde-ballena-nariz-50x50": 15, "esquina-piscina-50x50": 13,
           "esquina-borde-ballena-50x40": 12, EXTENSION: 13}
PASTELONES = sorted(LOSETASCHILE_PAVER_PRICE_IDS)

ESQUEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mensaje", "acciones"],
    "properties": {
        "mensaje": {"type": "string",
                    "description": "Texto para el cliente. Vacío si solo se deriva sin responder."},
        "acciones": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["tipo"],
                "properties": {
                    "tipo": {"type": "string", "enum": [
                        "catalogo_bordes", "catalogo_pastelones", "gama_colores", "ubicacion",
                        "presupuesto_bordes", "presupuesto_pastelones", "derivar"]},
                    "modelo": {"type": "string"},
                    "largo_m": {"type": "number"},
                    "ancho_m": {"type": "number"},
                    "forma": {"type": "string", "enum": ["rectangular", "otra"]},
                    "m2": {"type": "number"},
                    "corridas_extension": {"type": "integer",
                                           "description": "Corridas de extensión alrededor del borde; 0 si solo borde"},
                    "color": {"type": "string"},
                    "entrega": {"type": "string",
                                "description": "«retiro», o la dirección o el enlace de ubicación de despacho que dio el cliente"},
                    "motivo": {"type": "string"},
                },
            },
        },
    },
}

INSTRUCCIONES = """Eres parte del equipo de ventas de PoolEdge y atiendes su WhatsApp. PoolEdge es una
fábrica de bordes de piscina y pastelones de hormigón en La Pintana, Santiago, que vende directo
de fábrica.

Tu trabajo es entender la conversación y responder lo que el cliente necesita, como lo haría una
persona del equipo. No sigues un orden de preguntas: lees todo el chat, ves qué falta y actúas.

Cómo escribes (así atiende el dueño, Diego):
- Trato de usted, español de Chile, cercano y muy breve: frases cortas, una idea por párrafo,
  como se escribe en WhatsApp. «Perfecto», «estimado», «quedo atento» son su forma de hablar.
- Nada de frases de vendedor («Buena elección», «con gusto le ayudo»): directo al punto.
- No repitas lo que el cliente acaba de decir («Perfecto, rectangular de 6 x 3.», «Perfecto,
  solo el borde.»): suena a máquina. Si hace falta acusar recibo, basta un «Perfecto.» y
  sigue con lo que falta, en la misma burbuja.
- Nunca uses el nombre del cliente. Si corresponde saludar (inicio del chat o el cliente saludó),
  el saludo correcto ahora es «{saludo}»; no uses otro. A mitad de conversación no saludes.
- Ordena el mensaje en párrafos separados por una línea en blanco: primero el saludo (si
  corresponde) y la respuesta a lo que preguntó; luego la información (precios, horario,
  condiciones); al final, una sola pregunta para avanzar. Cada párrafo, una o dos frases.
- Cuando ofreces opciones (modelos, por ejemplo), ponlas una por línea con «• », en un
  párrafo aparte después de la pregunta. Sin números ni «responda con el número».
- No empieces cada mensaje con «Gracias»; agradece solo cuando el cliente da algo que lo
  amerite, y varía la forma.
- Nunca digas que eres un bot, un asistente virtual o una IA.
- No anuncies revisiones ni esperas: nada de «lo reviso», «le confirmo», «una persona del
  equipo», «quedó pendiente», «un momento». Si no puedes responder algo, usa la acción
  «derivar» y no lo menciones.
- Pide un solo dato por mensaje y nunca un dato que el chat ya tiene. Los clientes suelen mandar
  las medidas antes de que se las pidan.

Cómo lees el chat:
- «POOLEDGE:» son mensajes del equipo, a veces escritos a mano por el dueño. Lo que ahí se
  prometió o se dijo vale; no lo contradigas ni lo repitas.
- Si el cliente mandó varios mensajes seguidos, respóndelos juntos.
- Si el último mensaje de POOLEDGE ya respondió lo que el cliente pregunta, no repitas.
- Cada mensaje trae su fecha. Si el cliente vuelve después de horas o días con un saludo o
  «quiero más información», es una consulta nueva: respóndela como tal. Un pedido o presupuesto
  de antes ya lo tiene el equipo; no lo vuelvas a calcular.
- «mensaje» nunca va vacío cuando el cliente saluda, pregunta algo o pide información.

El orden que suele seguir Diego (guía, no guion: si el cliente ya dio un dato, no lo pidas):
producto (bordes o pastelones) → catálogo → modelo que le interesó → medidas → si es
rectangular o romana → si quiere solo el borde o también extensión → retiro o despacho (ubicación)
→ color (con la gama) → presupuesto.

Cómo responde Diego a lo típico:
- «¿De dónde son?»: «Somos de Santiago.» con la acción «ubicacion», y si no sabe dónde vive el
  cliente: «¿De qué comuna es usted, para ver si llegamos con nuestros despachos?».
- «¿Qué borde me recomienda?»: el más vendido es el recto con nariz; el ballena es más
  levantado y más fácil de instalar; el recto es liso en su superficie. La elección es del
  cliente.
- Extensión: si el cliente la menciona, o tiene pasto o tierra alrededor, pregunta si quiere
  solo el borde o también una corrida de extensión (con una corrida queda cerca de un metro de
  superficie con el borde). Pon las corridas en «corridas_extension» de presupuesto_bordes; el
  sistema calcula las piezas. Si pide una cantidad suelta de extensiones (no corridas), deriva.
- Piden algo que no vendemos (mantas térmicas, instalación): dilo simple y cuenta qué sí
  vendemos: bordes de piscina y pastelones, con retiro en fábrica o despacho.
- Escriben con errores («verdes de pisina», «Gtis»): entiende lo que quisieron decir.

Qué haces según lo que pide (son ejemplos, no un guion):
- El cliente solo saluda y el chat tiene datos de antes (medidas, modelo): saluda y pregunta si
  sigue con ese proyecto o en qué le puede ayudar; no des esos datos por confirmados.
- Llega solo un saludo o «quiero más información» de un anuncio: saluda, pregunta las medidas
  de la piscina y manda el catálogo de bordes (acción catalogo_bordes). Si ya habló de
  pastelones, el de pastelones.
- Pregunta dónde están o la dirección: acción «ubicacion». El sistema agrega al final la
  dirección y el mapa; tú no escribas la dirección ni digas «nuestra fábrica está en».
- Pregunta colores, o ya eligió modelo y falta el color: acción «gama_colores». La imagen
  sale con tu «mensaje» como texto: si falta el color, pregunta cuál prefiere.
- El mínimo de $200.000 para despacho menciónalo solo si el cliente pide despacho y el pedido
  es chico (pocas piezas). Si no pidió despacho, no le digas que su pedido es para retiro. Una
  piscina completa con bordes ya lo supera: no lo menciones.
- Si el chat ya muestra «POOLEDGE: Catálogo …» de ese producto, no lo mandes de nuevo salvo que
  el cliente lo pida.
- Ya hay producto, modelo y medidas de una piscina rectangular (bordes), o modelo y m²
  (pastelones), más el color y si retira o necesita despacho: acción presupuesto_bordes o
  presupuesto_pastelones con los datos. Úsala solo cuando el NUEVO MENSAJE entrega o cambia uno
  de esos datos, nunca para repetir un presupuesto que ya se hizo. El sistema calcula las piezas y el total y el equipo
  envía el presupuesto; tú no escribas cantidades ni totales. En «mensaje», una frase breve
  para que sepa qué sigue, por ejemplo «Perfecto, con esto le preparamos el presupuesto.».
- Si la piscina no es rectangular (romana, curva, en L): pide una foto y deriva.
- Si falta algo para el presupuesto, pídelo de forma natural.
- Si corrige cantidades de un presupuesto emitido, distingue cantidades finales de unidades
  adicionales. Si es ambiguo, pregunta «¿Cuántas unidades quiere en total?». Con la aclaración,
  deriva la enmienda del mismo pedido al equipo, sin generar otro presupuesto.
- Si elige retiro, deja de pedir dirección de despacho. Si necesita el peso para su vehículo
  o una transportista, usa el peso que figura en su cotización vigente. Si falta, deriva.
- Para transporte externo distingue el traslado hasta la agencia del flete de la transportista.
  Si el cliente ya tiene el peso y pregunta por el traslado a su agencia, pregunta qué empresa
  eligió si falta ese dato. No extrapoles cobros de otro pedido.
- Una fecha solicitada es una preferencia. Solo confirma una entrega si el equipo ya confirmó
  esa fecha para ese pedido. Ante una solicitud de confirmación sin respaldo, deriva.
- Si el cliente pide despacho y el chat no tiene dónde entregar, pídele en ese mismo mensaje
  su ubicación actual de WhatsApp o la dirección para ponerla en el GPS, como lo pide Diego:
  «¿Me puede enviar su ubicación actual de WhatsApp o la dirección, para ponerla en el GPS?».
  Sin eso no hay presupuesto con despacho.
- «[location] https://www.google.com/maps?q=…» en el chat es la ubicación que compartió el
  cliente: úsala como lugar de entrega (en «entrega», el enlace tal cual).
- En «modelo» usa solo un modelo que el cliente eligió con claridad. Si nombra uno que no está en
  la lista o es ambiguo, pregúntale cuál de los de la lista quiere.

Lo que nunca haces:
- No calculas cantidades de piezas, metros ni totales.
- No inventas precios, descuentos, stock, colores disponibles, plazos, fechas, garantía,
  cobertura o costo de despacho a un lugar específico, medios de pago, ni instrucciones de
  instalación. Solo usas lo que dice la ficha o la lista de precios, con sus mismas palabras.
- No ofreces instalación ni descuentos.
Si el cliente pide algo de eso y la ficha no lo trae, usa «derivar» con el motivo.

Responde solo con el JSON del esquema."""


_CHILE = ZoneInfo("America/Santiago")
_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _fecha(valor: Any) -> str:
    """«20/11 22:31» en hora de Chile; vacío si el turno no trae fecha."""
    try:
        momento = datetime.fromisoformat(str(valor or ""))
    except ValueError:
        return ""
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(_CHILE).strftime("%d/%m %H:%M")


def _turnos(history: List[Dict[str, Any]], limite: int) -> str:
    # Con fecha: así el modelo distingue un pedido de ayer de una consulta nueva.
    lineas = []
    for turn in history[-limite:]:
        texto = " ".join(str(turn.get("text") or "").split())
        if not texto:
            continue
        quien = "CLIENTE" if turn.get("role") == "lead" else "POOLEDGE"
        fecha = _fecha(turn.get("at"))
        lineas.append(f"[{fecha}] {quien}: {texto[:1500]}" if fecha else f"{quien}: {texto[:1500]}")
    return "\n".join(lineas)


def _lista_precios(pricing: Dict[str, Any]) -> str:
    return "\n".join(f"- {item.get('name') or item.get('id')}: ${round(item['unit_price']):,}".replace(",", ".")
                     for item in pricing.get("items", []) if item.get("unit_price"))


def sistema(knowledge: str, pricing: Dict[str, Any], saludo: str) -> str:
    return (INSTRUCCIONES.replace("{saludo}", saludo) +
            "\n\nMODELOS DE BORDE (usa exactamente uno de estos nombres en «modelo»):\n" +
            "\n".join(f"- {nombre}" for nombre in BORDES) +
            "\n\nMODELOS DE PASTELÓN (usa exactamente uno de estos nombres en «modelo»):\n" +
            "\n".join(f"- {nombre}" for nombre in PASTELONES) +
            "\n\nLISTA DE PRECIOS (CLP por unidad, IVA incluido si la ficha no dice otra cosa):\n" +
            _lista_precios(pricing) +
            "\n\nFICHA DEL NEGOCIO:\n" + (knowledge or "(sin ficha)"))


# --- revisión de la respuesta antes de enviarla -----------------------------------

_AVISOS = re.compile(
    r"\b(?:lo|la|le)\s+(?:reviso|revisamos|confirmo|confirmamos|consulto|averiguo)\b"
    r"|\bpersona\s+del\s+equipo\b|\bel\s+equipo\s+(?:le|te)\s+(?:confirma|escribe|contacta|responde)"
    r"|\bqued[oó]\s+pendiente\b|\bun\s+momento\b|\bvoy\s+a\s+revisar\b"
    r"|\brecib[ií]\s+(?:su|tu)\s+(?:mensaje|consulta)\b", re.IGNORECASE)
_BOT = re.compile(r"\b(?:bot|chatbot|asistente\s+virtual|inteligencia\s+artificial)\b", re.IGNORECASE)
_MENU = re.compile(r"(?m)^\s*\d\s*[.)-]\s+\S|responda\s+con\s+el\s+n[uú]mero", re.IGNORECASE)
_MONTO = re.compile(r"\$\s?(\d{1,3}(?:[.,]\d{3})+|\d+)")
_DIRECCION = re.compile(
    r"\b(?:av(?:enida)?\.?|calle|pasaje|camino|ruta)\s+[A-ZÁÉÍÓÚÑ][\wáéíóúñ]*(?:\s+[\wáéíóúñ]+){0,4}\s+\d{2,5}\b",
    re.IGNORECASE)
_PLAZO = re.compile(r"\b\d+\s*(?:a\s*\d+\s*)?(?:d[ií]as?|semanas?|horas?)\b", re.IGNORECASE)
_PALABRAS_CANTIDAD = re.compile(r"\b\d+\s*(?:bordes?|esquinas?|piezas?|pastelones?|unidades)\b",
                                re.IGNORECASE)


def revisar_respuesta(texto: str, *, knowledge: str, pricing: Dict[str, Any],
                      nombres: List[str]) -> List[str]:
    """Problemas que impiden enviar `texto`; vacío si puede salir."""
    problemas = []
    if not texto.strip():
        return problemas
    ficha = " ".join((knowledge or "").split()).casefold()
    if _AVISOS.search(texto):
        problemas.append("anuncia una revisión o espera; si no puede responder, use la acción derivar y no lo diga")
    if _BOT.search(texto):
        problemas.append("se presenta como bot o IA")
    if _MENU.search(texto):
        problemas.append("usa un menú numerado")
    precios = {round(item["unit_price"]) for item in pricing.get("items", []) if item.get("unit_price")}
    for match in _MONTO.finditer(texto):
        valor = int(re.sub(r"\D", "", match.group(1)))
        if valor not in precios and match.group(0).replace(" ", "") not in ficha.replace(" ", ""):
            problemas.append(f"el monto {match.group(0)} no está en la lista de precios ni en la ficha")
    for match in _DIRECCION.finditer(texto):
        if match.group(0).casefold() not in ficha and "granados" not in match.group(0).casefold():
            problemas.append(f"escribe una dirección ({match.group(0)}); use la acción ubicacion")
    for match in _PLAZO.finditer(texto):
        if " ".join(match.group(0).split()).casefold() not in ficha:
            problemas.append(f"promete un plazo ({match.group(0)}) que no está en la ficha")
    if _PALABRAS_CANTIDAD.search(texto):
        problemas.append("escribe una cantidad de piezas; las calcula el sistema con la acción de presupuesto")
    for nombre in nombres:
        nombre = (nombre or "").strip()
        if len(nombre) >= 3 and re.search(rf"\b{re.escape(nombre)}\b", texto, re.IGNORECASE):
            problemas.append("usa el nombre del cliente")
            break
    return problemas


# --- acciones --------------------------------------------------------------------

def _medida(valor: Any) -> Optional[Decimal]:
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, TypeError):
        return None
    return numero if 0 < numero <= 50 else None


def presupuesto_bordes(accion: Dict[str, Any], pricing: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Plan y presupuesto de productos con la misma regla del flujo anterior; None si falta algo."""
    border_id = BORDES.get(str(accion.get("modelo") or ""))
    largo, ancho = _medida(accion.get("largo_m")), _medida(accion.get("ancho_m"))
    if not border_id or not largo or not ancho or accion.get("forma") != "rectangular":
        return None
    notas = []
    redondeo = tuple((lado * 2).to_integral_value(rounding=ROUND_CEILING) / 2 for lado in (largo, ancho))
    if redondeo != (largo, ancho):
        notas.append(f"Medidas {largo} × {ancho} m redondeadas a {redondeo[0]} × {redondeo[1]} m "
                     "para el cálculo: revisar cortes.")
    rectas = int(2 * (redondeo[0] + redondeo[1]) * 2)
    corridas = accion.get("corridas_extension") or 0
    if not isinstance(corridas, int) or not 0 <= corridas <= 3:
        return None
    extensiones = piezas_extension(redondeo[0], redondeo[1], ANCHO_BORDE[border_id], corridas)
    plan = {"width": redondeo[1], "length": redondeo[0], "straight": rectas, "corners": 4,
            "border_id": border_id, "extension": extensiones, "review_notes": notas}
    lineas = [{"id": border_id, "qty": rectas}, {"id": ESQUINA_DE.get(border_id, ESQUINA), "qty": 4}]
    if extensiones:
        lineas.append({"id": EXTENSION, "qty": extensiones})
        notas.append(f"Extensión: {corridas} corrida(s) alrededor del borde, {extensiones} piezas "
                     "(perímetro exterior ÷ 0,5 + 4 esquinas por corrida): revisar.")
    peso = peso_total(lineas)
    if peso:
        notas.append(f"Peso estimado: {peso:,} kg.".replace(",", "."))
    quote = compute_quote(pricing, lineas)
    if not quote or quote.get("unmatched") or not quote.get("total"):
        return None
    quote["shipping_pending"] = True
    quote["delivery_detail"] = _entrega(accion)
    quote["review_notes"] = notas
    return {"plan": plan, "quote": quote}


def piezas_extension(largo: Decimal, ancho: Decimal, borde: Decimal, corridas: int) -> int:
    """Piezas 50x50 para `corridas` anillos alrededor del borde.

    Cada corrida rodea el rectángulo exterior de la anterior: perímetro ÷ 0,5 m más
    4 esquinas. Coincide con el pedido de 8,5 × 3 m en ballena que cotizó Diego (57).
    """
    total = 0
    for k in range(corridas):
        exterior = 2 * (largo + ancho) + 8 * (borde + Decimal("0.5") * k)
        total += int((exterior / Decimal("0.5")).to_integral_value(rounding=ROUND_CEILING)) + 4
    return total


def peso_total(lineas: List[Dict[str, Any]]) -> Optional[int]:
    """Kilos del pedido, solo si se conoce el peso de todas las piezas con peso propio."""
    total = 0
    for linea in lineas:
        if linea["id"] not in PESO_KG:
            return None
        total += PESO_KG[linea["id"]] * linea["qty"]
    return total


def presupuesto_pastelones(accion: Dict[str, Any], pricing: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    modelo = str(accion.get("modelo") or "")
    price_id = LOSETASCHILE_PAVER_PRICE_IDS.get(modelo)
    try:
        m2 = Decimal(str(accion.get("m2")))
    except (InvalidOperation, TypeError):
        return None
    if not price_id or not 0 < m2 <= 5000:
        return None
    unit = next((item["unit_price"] for item in pricing.get("items", [])
                 if item.get("id") == price_id), None)
    return {"model": modelo, "area_m2": format(m2.normalize(), "f"),
            "color": (accion.get("color") or None), "delivery_detail": _entrega(accion),
            "unit_price": unit, "price_id": price_id}


def _entrega(accion: Dict[str, Any]) -> Optional[str]:
    entrega = " ".join(str(accion.get("entrega") or "").split())
    if not entrega:
        return None
    if entrega.casefold().startswith("retiro"):
        return f"Retiro en fábrica: {FACTORY_ADDRESS}"
    return f"Despacho: {entrega[:200]}"


# --- llamada al modelo -----------------------------------------------------------

def _llamar_claude(system: str, user: str) -> Dict[str, Any]:
    """Una llamada a Claude con salida JSON; levanta si no hay respuesta usable."""
    import anthropic  # perezoso: solo en el camino real

    cfg = LOSETASCHILE_AGENT
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("Falta ANTHROPIC_API_KEY para el agente")
    client = anthropic.Anthropic(api_key=key, base_url="https://api.anthropic.com",
                                 timeout=float(cfg["timeout_s"]), max_retries=1)
    msg = client.messages.create(
        model=cfg["model"], max_tokens=int(cfg["max_tokens"]),
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": cfg["effort"],
                       "format": {"type": "json_schema", "schema": ESQUEMA}},
    )
    if getattr(msg, "stop_reason", None) in ("refusal", "max_tokens"):
        raise RuntimeError(f"Claude no terminó la respuesta ({msg.stop_reason})")
    usage = getattr(msg, "usage", None)
    if usage is not None:
        logging.info("agente PoolEdge: entrada %s, caché %s, salida %s",
                     getattr(usage, "input_tokens", 0), getattr(usage, "cache_read_input_tokens", 0),
                     getattr(usage, "output_tokens", 0))
    texto = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
    return json.loads(texto)


def responder(message: str, history: List[Dict[str, Any]], *, knowledge: str, pricing_raw: Any,
              nombres: List[str], llamar: Optional[Callable[[str, str], Dict[str, Any]]] = None,
              ahora: Optional[datetime] = None) -> Dict[str, Any]:
    """`res` para el orquestador: respuesta, medios, presupuesto o derivación."""
    llamar = llamar or _llamar_claude
    pricing = normalize_pricing(pricing_raw)
    system = sistema(knowledge, pricing, whatsapp_greeting(ahora or datetime.now(timezone.utc)))
    chat = _turnos(history, int(LOSETASCHILE_AGENT["turnos_historial"]))
    momento = (ahora or datetime.now(timezone.utc)).astimezone(_CHILE)
    # Con el día de la semana: «¿trabajan mañana?» un sábado se responde con el domingo.
    hoy = f"{_DIAS[momento.weekday()]} {momento.strftime('%d/%m %H:%M')}"
    user = (f"CHAT HASTA AHORA:\n{chat or '(es el primer mensaje)'}\n\n"
            f"NUEVO MENSAJE DEL CLIENTE ({hoy}):\n{message}")
    try:
        salida = llamar(system, user)
        problemas = revisar_respuesta(str(salida.get("mensaje") or ""), knowledge=knowledge,
                                      pricing=pricing, nombres=nombres)
        if problemas:
            salida = llamar(system, user + "\n\nTU RESPUESTA ANTERIOR NO SE PUEDE ENVIAR: " +
                            "; ".join(problemas) + ". Corrígela.")
            problemas = revisar_respuesta(str(salida.get("mensaje") or ""), knowledge=knowledge,
                                          pricing=pricing, nombres=nombres)
    except Exception as exc:  # el cliente no recibe nada; el equipo lo ve en Atención
        logging.warning("agente PoolEdge sin respuesta: %s", exc)
        return {"reply": "", "intent": "handoff",
                "review_reason": "El agente no pudo redactar una respuesta"}
    if problemas:
        return {"reply": "", "intent": "handoff",
                "review_reason": "Respuesta bloqueada: " + "; ".join(problemas)[:180]}
    return _a_res(salida, pricing, history, message)


COMPRA_MINIMA_REGIONES = 200_000  # ficha v10: compra mínima para despacho a regiones
_MINIMO = re.compile(r"compra\s+m[ií]nima|m[ií]nimo\s+de\s+compra", re.IGNORECASE)

_CATALOGO_ENVIADO = {"catalogo_bordes": "Catálogo Bordes de Piscina",
                     "catalogo_pastelones": "Catálogo Pastelones"}


def _a_res(salida: Dict[str, Any], pricing: Dict[str, Any],
           history: Optional[List[Dict[str, Any]]] = None, message: str = "") -> Dict[str, Any]:
    reply = str(salida.get("mensaje") or "").strip()
    acciones = [a for a in salida.get("acciones") or [] if isinstance(a, dict)]
    enviados = {str(t.get("text") or "").strip() for t in (history or [])[-40:]
                if t.get("role") != "lead"}
    pide_catalogo = re.search(r"cat[aá]logo", message or "", re.IGNORECASE)
    # El mismo catálogo dos veces en un chat aburre; se repite solo si el cliente lo pide.
    acciones = [a for a in acciones if pide_catalogo or
                _CATALOGO_ENVIADO.get(str(a.get("tipo"))) not in enviados]
    tipos = [str(a.get("tipo")) for a in acciones]
    res: Dict[str, Any] = {"intent": "general", "agent_led": True}
    derivar = next((a for a in acciones if a.get("tipo") == "derivar"), None)

    for accion in acciones:
        if accion.get("tipo") == "presupuesto_bordes":
            calculo = presupuesto_bordes(accion, pricing)
            if calculo is None:
                derivar = derivar or {"motivo": "Datos de presupuesto de bordes incompletos o no rectangular"}
                continue
            res.update(intent="pricing", quote=calculo["quote"],
                       selected_tone=(accion.get("color") or None))
        elif accion.get("tipo") == "presupuesto_pastelones":
            pedido = presupuesto_pastelones(accion, pricing)
            if pedido is None:
                derivar = derivar or {"motivo": "Datos de presupuesto de pastelones incompletos"}
                continue
            res.update(intent="pricing", paver_order=pedido)

    total = (res.get("quote") or {}).get("total") or 0
    if total >= COMPRA_MINIMA_REGIONES and _MINIMO.search(reply):
        # Diego, 2026-11-21: si el pedido ya supera el mínimo, decirlo sobra.
        reply = "\n\n".join(p for p in (
            " ".join(f for f in re.split(r"(?<=[.!?])\s+", parrafo) if not _MINIMO.search(f))
            for parrafo in reply.split("\n\n")) if p.strip()).strip()
    if "ubicacion" in tipos and FACTORY_ADDRESS not in reply:
        parrafos = [p for p in reply.split("\n\n") if p.strip()]
        # Como Diego: primero la ubicación y después la pregunta que sigue.
        cola = [parrafos.pop()] if parrafos and parrafos[-1].rstrip().endswith("?") else []
        reply = "\n\n".join(parrafos + [UBICACION] + cola)
    catalogo = ("bordes" if "catalogo_bordes" in tipos else
                "pastelones" if "catalogo_pastelones" in tipos else None)
    if catalogo:
        res["catalog_document"] = {"category": catalogo, "pricing": pricing}
    if "gama_colores" in tipos:
        res["media_asset"] = COLOR_CATALOG_IMAGE_PATH
    if catalogo and reply and not res.get("media_asset"):
        res["reply_after_document"] = True

    if derivar is not None:
        motivo = " ".join(str(derivar.get("motivo") or "Consulta para el equipo").split())[:180]
        if reply or res.get("quote") or res.get("paver_order") or catalogo:
            res["attention"] = motivo  # se responde lo que se puede y el equipo ve el resto
        else:
            return {"reply": "", "intent": "handoff", "review_reason": motivo, "agent_led": True}
    if not reply and (res.get("quote") or res.get("paver_order")):
        reply = "."  # el orquestador manda el borrador al grupo; al cliente no le llega texto
    if not reply and (catalogo or res.get("media_asset")):
        reply = "Le comparto el catálogo." if catalogo else "Le comparto la gama de colores."
    res["reply"] = reply
    return res
