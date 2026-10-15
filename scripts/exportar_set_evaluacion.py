#!/usr/bin/env python3
"""Exporta el historial real como set de evaluación anonimizado (etapa 0).

Lee el almacén de memoria **en solo lectura** y nunca guarda: el almacén activo
es producción y vive en Supabase. La salida es un JSON con un caso por turno
entrante, que es la unidad de medida de la etapa 0 — hay 5 conversaciones, no
las 30-50 que pedía el informe, pero 163 turnos del cliente, y el truncado de
contexto depende del largo del prompt, así que el turno es la unidad correcta.

La anonimización es **mejor esfuerzo y hay que revisarla a mano** antes de
commitear nada. Sustituye lo que sabe identificar —teléfonos, correos, nombres
conocidos del CRM y presentaciones «soy X»— y después marca lo que quedó
sospechoso para que una persona lo mire. No se commitea el crudo.

Uso:
    python3 scripts/exportar_set_evaluacion.py --salida /tmp/set.json
    python3 scripts/exportar_set_evaluacion.py --estado /ruta/state.json --salida ...
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, Iterable, List, Tuple

# Un teléfono chileno con o sin +56, y cualquier ristra larga de dígitos que
# pueda serlo. Se recorta a 7 para no perder un número escrito con espacios.
_TELEFONO = re.compile(r"(?:\+?56)?[\s.-]?9?[\s.-]?(?:\d[\s.-]?){7,13}\d")
# Un ID de chat (`56912345678@c.us`) calza con la forma de un correo, así que
# el correo tiene que excluir esos dominios o se los come.
_CORREO = re.compile(r"\b[\w.+-]+@(?!c\.us\b|lid\b|s\.whatsapp\.net\b)[\w-]+\.[\w.-]+\b")
_CHAT_ID = re.compile(r"\b(\d{8,20})@(c\.us|lid|s\.whatsapp\.net)\b")
# Los seudónimos ya sustituidos no se vuelven a tocar: hacerlo los colapsaría
# todos al número de reserva y dos contactos distintos pasarían a ser el mismo.
_SEUDONIMO = re.compile(r"^56900000\d{3}$")

# El historial real trae credenciales pegadas: en la primera corrida apareció
# una URL de GitHub con `mcp_token=eyJ...`, un JWT completo, dentro de un
# mensaje. Un set de evaluación con un secreto adentro es peor que no tenerlo,
# así que esto va antes que cualquier otra sustitución.
_PARAM_SECRETO = re.compile(
    r"([?&](?:[\w-]*(?:token|key|secret|password|passwd|pwd|auth|session|sig)[\w-]*)=)"
    r"[^&\s]+", re.IGNORECASE)
_JWT = re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}(?:\.[\w-]+)?")
# Una ristra opaca larga en una URL: lo que queda cuando no tiene nombre de
# parámetro reconocible.
_OPACO = re.compile(r"\b[A-Za-z0-9_-]{40,}\b")

# Una URL arbitraria identifica aunque no lleve token: en el historial real
# quedó el usuario de GitHub de alguien dentro de la ruta. Solo sobreviven los
# dominios que el agente usa a diario; del resto basta saber que hubo un
# enlace. Las coordenadas de una ubicación son una dirección y se redactan.
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_DOMINIOS_PERMITIDOS = ("wa.me", "web.whatsapp.com", "www.google.com/maps", "google.com/maps")
_COORDENADAS = re.compile(r"q=-?\d+\.\d+,-?\d+\.\d+")
_PRESENTACION = re.compile(
    r"\b(?:soy|me\s+llamo|mi\s+nombre\s+es|habla|aquí)\s+"
    r"([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,20}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,20})?)")
# Calles chilenas: «Los Granados 029», «Av. Vicuña Mackenna 1234», «Pasaje X 45».
_DIRECCION = re.compile(
    r"\b(?:calle|avenida|av\.?|pasaje|psje\.?|camino|ruta|villa|población|pobl\.?)\s+"
    r"[A-Za-zÁÉÍÓÚÑáéíóúñ0-9.\s]{3,40}?\s*\d{1,6}\b", re.IGNORECASE)

# Lo que queda sospechoso tras sustituir: un nombre propio suelto que no sea
# principio de oración. No se borra —se marca— porque borrarlo a ciegas
# destruiría mensajes legítimos («Laja Española», «La Pintana» es el origen del
# flete, no un domicilio de cliente).
_POSIBLE_NOMBRE = re.compile(r"(?<![.!?¿¡]\s)(?<!^)\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,20}\b")

_INCIDENTES = {
    "pastelones-cantidad-inventada": re.compile(r"pastelon", re.I),
    "revision-sin-evidencia": re.compile(r"\bya\s+revis", re.I),
    "catalogo": re.compile(r"cat[aá]logo|cagalogo", re.I),
    "medidas-piscina": re.compile(r"\b(?:mide|medidas?)\b", re.I),
    "despacho": re.compile(r"\bdespach|\bflete", re.I),
    "ubicacion-o-adjunto": re.compile(r"^\[[a-z_]+\]", re.I),
}


def _seudonimo_telefono(indice: int) -> str:
    """Un número que no existe: el rango 56 9 0000 00xx no está asignado."""
    return f"56900000{indice:03d}"


def construir_mapa(conversaciones: Dict[str, List[Dict[str, Any]]],
                   nombres_conocidos: Iterable[str]) -> Dict[str, str]:
    """Sustituciones estables: el mismo dato real da siempre el mismo seudónimo."""
    mapa: Dict[str, str] = {}
    for indice, clave in enumerate(sorted(conversaciones), start=1):
        digitos = re.sub(r"\D", "", str(clave))
        if digitos:
            mapa[digitos] = _seudonimo_telefono(indice)
    for indice, nombre in enumerate(sorted({n.strip() for n in nombres_conocidos if n and n.strip()}),
                                    start=1):
        mapa[nombre.strip()] = f"CLIENTE{indice:02d}"
    return mapa


def anonimizar(texto: str, mapa: Dict[str, str]) -> Tuple[str, List[str]]:
    """Devuelve el texto sustituido y lo que quedó por revisar a mano."""
    if not texto:
        return "", []
    # Los secretos primero y sin excepciones: si algo se escapa acá, queda en
    # el repo para siempre.
    fuera = _PARAM_SECRETO.sub(r"\1SECRETO-REDACTADO", texto)
    fuera = _JWT.sub("SECRETO-REDACTADO", fuera)
    fuera = _OPACO.sub("SECRETO-REDACTADO", fuera)

    def _url(m: re.Match) -> str:
        enlace = m.group(0)
        if any(dominio in enlace.lower() for dominio in _DOMINIOS_PERMITIDOS):
            return _COORDENADAS.sub("q=COORDENADAS", enlace)
        return "https://ENLACE-REDACTADO"
    fuera = _URL.sub(_url, fuera)
    # Primero lo conocido, de más largo a más corto: si un nombre contiene a
    # otro, gana el completo.
    for real in sorted(mapa, key=len, reverse=True):
        if real:
            fuera = re.sub(re.escape(real), mapa[real], fuera, flags=re.IGNORECASE)
    def _chat(m: re.Match) -> str:
        digitos = m.group(1)
        if _SEUDONIMO.match(digitos):
            return m.group(0)
        return f"{mapa.get(digitos, '56900000000')}@{m.group(2)}"
    fuera = _CHAT_ID.sub(_chat, fuera)
    fuera = _CORREO.sub("CORREO@ejemplo.cl", fuera)
    fuera = _DIRECCION.sub("DIRECCION", fuera)
    fuera = _PRESENTACION.sub(lambda m: m.group(0).replace(m.group(1), "CLIENTE"), fuera)
    # Los teléfonos al final: antes podría comerse las medidas («6 x 3»), así
    # que solo se sustituye lo que tenga al menos 8 dígitos reales.
    def _tel(m: re.Match) -> str:
        digitos = re.sub(r"\D", "", m.group(0))
        if len(digitos) < 8 or _SEUDONIMO.match(digitos):
            return m.group(0)
        return mapa.get(digitos, "56900000000")
    fuera = _TELEFONO.sub(_tel, fuera)

    pendientes = [n for n in _POSIBLE_NOMBRE.findall(fuera)
                  if not n.startswith("CLIENTE") and n not in ("Catálogo", "Precio")]
    return fuera, sorted(set(pendientes))


def etiquetar(texto: str) -> List[str]:
    return sorted(k for k, rx in _INCIDENTES.items() if rx.search(texto or ""))


def nombres_de_crm(registros: Iterable[Dict[str, Any]]) -> List[str]:
    """Nombres y empresas del CRM: la fuente autorizada de quién es quién.

    Sin esto el mapa queda vacío y los nombres reales sobreviven al export —
    pasó en la primera corrida, con «Diego» y dos apellidos intactos.
    """
    fuera: List[str] = []
    for registro in registros or []:
        if not isinstance(registro, dict):
            continue
        for campo in ("name", "company", "contact"):
            valor = str(registro.get(campo) or "").strip()
            # Las partes sueltas también: el historial dice «Diego», no el nombre completo.
            if len(valor) >= 3:
                fuera.append(valor)
                fuera.extend(p for p in valor.split() if len(p) >= 3)
    return fuera


def construir_casos(clientes: Dict[str, Any],
                    nombres_por_cliente: Dict[str, List[str]] | None = None,
                    ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Un caso por turno del cliente, con el historial previo que lo precede."""
    casos: List[Dict[str, Any]] = []
    por_revisar: List[str] = []
    for client_id, datos in sorted((clientes or {}).items()):
        conversaciones = (datos or {}).get("conversations") or {}
        if not conversaciones:
            continue
        nombres = list((nombres_por_cliente or {}).get(client_id) or [])
        # El puente guarda acá el nombre del perfil de WhatsApp de cada contacto.
        nombres.extend(str(v) for v in ((datos or {}).get("whatsapp_display_names") or {}).values())
        mapa = construir_mapa(conversaciones, nombres)
        for clave, turnos in sorted(conversaciones.items()):
            historial: List[Dict[str, str]] = []
            for posicion, turno in enumerate(turnos or []):
                rol = turno.get("role") or ""
                texto, pendientes = anonimizar(str(turno.get("text") or ""), mapa)
                por_revisar.extend(pendientes)
                if rol == "lead" and texto.strip():
                    casos.append({
                        "id": f"{client_id}-{str(clave)[-6:]}-{posicion:03d}",
                        "client_id": client_id,
                        "chat": mapa.get(re.sub(r"\D", "", str(clave)), "56900000000"),
                        "posicion": posicion,
                        "turnos_previos": len(historial),
                        "mensaje": texto,
                        "historial": list(historial),
                        "etiquetas": etiquetar(texto),
                    })
                historial.append({"role": rol, "text": texto})
    return casos, sorted(set(por_revisar))


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--salida", required=True, help="archivo JSON de salida")
    parser.add_argument("--estado", default="", help="state.json local; por defecto el almacén configurado")
    parser.add_argument("--raiz", default="/home/diego/zeroai",
                        help="checkout desde el que importar zero/ y leer el almacén")
    args = parser.parse_args(argv)

    sys.path.insert(0, args.raiz)
    os.chdir(args.raiz)
    if args.estado:
        from zero.memory import SessionMemory
        memoria = SessionMemory(args.estado)
        crm = None
    else:
        from zero.store import make_crm, make_memory
        memoria = make_memory("state.json")
        crm = make_crm("crm.json")

    nombres: Dict[str, List[str]] = {}
    for client_id in sorted((memoria.clients or {})):
        if crm is None:
            continue
        try:                                    # el CRM se lee, nunca se guarda
            nombres[client_id] = nombres_de_crm(crm.list(client_id))
        except Exception as exc:                # noqa: BLE001 - informar y seguir
            print(f"  aviso: no se pudo leer el CRM de {client_id}: {exc}", file=sys.stderr)

    casos, por_revisar = construir_casos(memoria.clients or {}, nombres)
    salida = {
        "version": 1,
        "unidad": "turno entrante",
        "origen": type(memoria).__name__,
        "casos": casos,
        "por_revisar_a_mano": por_revisar,
    }
    with open(args.salida, "w", encoding="utf-8") as destino:
        json.dump(salida, destino, indent=1, ensure_ascii=False)
        destino.write("\n")

    print(f"{len(casos)} casos escritos en {args.salida}")
    conteo: Dict[str, int] = {}
    for caso in casos:
        for etiqueta in caso["etiquetas"]:
            conteo[etiqueta] = conteo.get(etiqueta, 0) + 1
    for etiqueta, veces in sorted(conteo.items(), key=lambda kv: -kv[1]):
        print(f"  {etiqueta:32} {veces}")
    if por_revisar:
        print(f"\n{len(por_revisar)} palabras por revisar a mano antes de commitear:")
        print("  " + ", ".join(por_revisar[:40]))
        print("  La anonimización es mejor esfuerzo: revísalas antes de versionar el set.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
