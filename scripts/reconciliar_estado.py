#!/usr/bin/env python3
"""Fusiona el estado de la nube (Supabase `app_state`) con el `state.json` local.

Para cuando Supabase vuelve después de una caída larga: durante ella todo se guardó en
`state.json` (zero/estado_retenido.py deja un marcador para que el backend no vuelva
solo a la nube). Ninguno de los dos lados está completo: el local no tenía lo último de
la nube antes del corte, y la nube no tiene lo escrito durante la caída. Hay que fusionar.

    python3 scripts/reconciliar_estado.py              # DRY-RUN: muestra, no escribe nada
    python3 scripts/reconciliar_estado.py --aplicar    # respalda, escribe nube + local, libera el marcador
    python3 scripts/reconciliar_estado.py --aplicar --si
    python3 scripts/reconciliar_estado.py --retener-desde 2026-11-25T21:55:00-03:00   # solo crea el marcador
    python3 scripts/reconciliar_estado.py --local clients.acme.icp   # fuerza LOCAL en ese conflicto

Códigos de salida: 0 ok · 1 error o cancelado (nada a medias: el marcador sigue) ·
2 la nube aún no responde (no se toca nada).

REGLAS DE FUSIÓN, por clave del snapshot (`SessionMemory.snapshot()`):

  actions            Lista de eventos. Unión sin duplicados (el evento entero es la
                     identidad), ordenada por `ts`.
  used_emails        Unión sin duplicados, orden de aparición (nube primero).
  contacted          lead -> instante. Gana el instante más reciente.
  contacted_by_client  client -> lead -> instante. Igual: gana el más reciente.
  sequences          Identidad (client_id, lead_key, started). Si ambos lados la tienen y
                     difieren: gana la cerrada sobre la abierta, y entre iguales la de
                     mayor `step`; empate con contenido distinto = conflicto (nube). Si
                     tras unir un mismo lead queda con más de una abierta, sobrevive la
                     de `started` más antiguo y las demás se cierran con
                     closed_reason="fusion_duplicada" (dos abiertas = seguimiento doble).
  pending_offers     "client|lead" -> {kind, ts}. Presente en un solo lado: se conserva.
                     En ambos y distinta: gana la de `ts` más reciente.
  agent_status       agent -> último estado. Sin marca de tiempo: si difiere = conflicto
                     (nube).
  vendors, functions id -> dict. Unión por id; dentro de cada id, campo a campo; un campo
                     que difiere = conflicto (nube).
  clients            id -> ficha. Unión por id; luego campo a campo según el campo:
    conversations      lead -> turnos. Unión de turnos {role,text,at} sin duplicados,
                       ordenada por `at`, con el tope MAX_TURNS_STORED de memory.py.
    knowledge_gaps     clave -> hueco. Gana el lado con el evento más reciente (ultima,
                       resuelta_en, atendida_en, descartada_en) como base; los campos que
                       solo tiene el otro se conservan; `veces` = el mayor, `primera` = la
                       más antigua, `esperando` = unión por chat_id (vacío si el ganador
                       está resuelto/atendido/descartado). Sin marca o empate = conflicto.
    whatsapp_handoffs  lead -> pausa. Un solo lado: se conserva (más seguro: el agente
                       callado). En ambos y distinta: gana la de `at` más reciente.
    lead_notes         lead -> notas. Unión; nota que difiere = conflicto (nube).
    knowledge / knowledge_version / knowledge_versions
                       Unión de versiones por (número, texto). Se ordenan por `guardada`
                       y la vigente es la más reciente; si un número se repite con otro
                       texto (o queda fuera de orden) esa versión se renumera hacia
                       adelante, así la próxima edición no pisa ninguna. Tope
                       MAX_KNOWLEDGE_VERSIONS (config.py), nunca cae la vigente.
    tier, stage, icp, meta, pricing, cases, agent_profile, vendor_id y cualquier otro:
                       No tienen marca de tiempo, no hay forma de decidir: si difieren =
                       conflicto. Por defecto se conserva la NUBE (el valor previo al
                       corte); `--local RUTA` fuerza el local para esa ruta.
  clave desconocida  No se entiende: se lista como conflicto y no se toca (se conserva
                     lo que haya en la nube; si solo existe en local, no se agrega).

Un lado que NO tiene algo no se interpreta como borrado: lo ausente se rellena con lo
del otro lado. Es la limitación honesta de fusionar sin historial de borrados (p. ej. una
oferta pendiente cumplida y limpiada en local reaparece si la nube aún la tenía; el
resumen cuenta cuántas entradas solo-nube se conservaron para que se revise).

El criterio "nube para lo previo al corte, local para lo posterior" usa el `desde` del
marcador y solo puede aplicarse donde hay marca de tiempo (huecos, pausas, ofertas).

Solo stdlib.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zero import estado_retenido  # noqa: E402
from zero._env import load_env  # noqa: E402
from zero._supabase import SupabaseError, sb_request  # noqa: E402
from zero.config import (ESTADO_CONFIRMACION, ESTADO_RESPALDO_PREFIJO,  # noqa: E402
                         ESTADO_RESPALDOS_DIR, MAX_KNOWLEDGE_VERSIONS)
from zero.memory import SessionMemory, _parse  # noqa: E402
from zero.persistence import load_json, save_json  # noqa: E402

load_env()

TABLE = "app_state"
ROW_ID = "agency"
_FALTA = object()          # "este lado no tiene la clave" (distinto de None)


class NubeNoDisponible(RuntimeError):
    """La nube no respondió o no está configurada: no se toca nada."""


# --- utilidades -------------------------------------------------------------------
def _c(x: Any) -> str:
    return json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)


def _t(valor: Any) -> Optional[datetime]:
    try:
        return _parse(str(valor)) if valor else None
    except (TypeError, ValueError):
        return None


def _corto(x: Any, n: int = 80) -> str:
    s = "(falta)" if x is _FALTA else _c(x)
    return s if len(s) <= n else s[: n - 1] + "…"


class Fusion:
    """Acumula estadísticas y conflictos mientras se fusiona."""

    def __init__(self, desde: Optional[str] = None, locales: Tuple[str, ...] = ()):
        self.desde = _t(desde)
        self.locales = set(locales)
        self.stats: Dict[str, Dict[str, int]] = {}
        self.conflictos: List[Dict[str, Any]] = []

    def contar(self, clave: str, tipo: str, n: int = 1) -> None:
        fila = self.stats.setdefault(clave, {"de_local": 0, "solo_nube": 0, "iguales": 0,
                                             "fusionados": 0})
        fila[tipo] += n

    def nota(self, ruta: str, nube: Any, local: Any, resolucion: str) -> None:
        self.conflictos.append({"ruta": ruta, "nube": nube, "local": local,
                                "resolucion": resolucion})

    def conflicto(self, clave: str, ruta: str, nube: Any, local: Any) -> Any:
        """Sin forma de decidir: nube por defecto, local si se pidió para esa ruta."""
        usa_local = ruta in self.locales
        self.nota(ruta, nube, local, "local (forzado)" if usa_local else "nube")
        self.contar(clave, "fusionados")
        return local if usa_local else nube

    def posterior(self, ts: Any) -> bool:
        """¿Lo creado en `ts` es posterior al corte? Sin corte conocido, no."""
        t = _t(ts)
        return bool(t and self.desde and t >= self.desde)


# --- reglas genéricas ---------------------------------------------------------------
def _escalar(f: Fusion, clave: str, ruta: str, n: Any, l: Any) -> Any:
    if n is _FALTA:
        f.contar(clave, "de_local")
        return l
    if l is _FALTA:
        f.contar(clave, "solo_nube")
        return n
    if _c(n) == _c(l):
        f.contar(clave, "iguales")
        return n
    return f.conflicto(clave, ruta, n, l)


def _mapa(f: Fusion, clave: str, ruta: str, n: Any, l: Any,
          item: Callable[[Fusion, str, str, Any, Any], Any]) -> Any:
    """dict por id: unión de ids; los ids en ambos lados los resuelve `item`."""
    if not isinstance(n, dict) or not isinstance(l, dict):
        return _escalar(f, clave, ruta, n, l)
    out: Dict[str, Any] = {}
    for k in list(n) + [k for k in l if k not in n]:
        nv, lv = n.get(k, _FALTA), l.get(k, _FALTA)
        out[k] = item(f, clave, f"{ruta}.{k}", nv, lv) if (nv is not _FALTA and lv is not _FALTA) \
            else _escalar(f, clave, f"{ruta}.{k}", nv, lv)
    return copy.deepcopy(out)


def _plano(f: Fusion, clave: str, ruta: str, n: Any, l: Any) -> Any:
    """dict de campos sueltos: campo a campo, lo que difiere es conflicto."""
    if not isinstance(n, dict) or not isinstance(l, dict):
        return _escalar(f, clave, ruta, n, l)
    return {k: _escalar(f, clave, f"{ruta}.{k}", n.get(k, _FALTA), l.get(k, _FALTA))
            for k in list(n) + [k for k in l if k not in n]}


def _con_marca(campo: str) -> Callable[..., Any]:
    """Item con una marca de tiempo propia: gana la más reciente."""
    def regla(f: Fusion, clave: str, ruta: str, n: Any, l: Any) -> Any:
        if _c(n) == _c(l):
            f.contar(clave, "iguales")
            return n
        if not isinstance(n, dict) or not isinstance(l, dict):
            return f.conflicto(clave, ruta, n, l)
        tn, tl = _t(n.get(campo)), _t(l.get(campo))
        if tn and tl and tn != tl:
            f.contar(clave, "fusionados")
            return l if tl > tn else n
        if tl and not tn and f.posterior(l.get(campo)):
            f.contar(clave, "fusionados")
            return l
        return f.conflicto(clave, ruta, n, l)
    return regla


def _eventos(f: Fusion, clave: str, ruta: str, n: Any, l: Any,
             campos_ts: Tuple[str, ...] = ("ts", "at")) -> Any:
    """Lista de eventos: unión sin duplicados, ordenada por tiempo (estable)."""
    if not isinstance(n, list) or not isinstance(l, list):
        return _escalar(f, clave, ruta, n, l)
    en_n, en_l = {_c(e) for e in n}, {_c(e) for e in l}
    f.contar(clave, "iguales", len(en_n & en_l))
    f.contar(clave, "solo_nube", len(en_n - en_l))
    f.contar(clave, "de_local", len(en_l - en_n))
    nuevos = [e for e in l if _c(e) not in en_n]

    def cuando(e: Any) -> datetime:
        for campo in campos_ts:
            t = _t(e.get(campo)) if isinstance(e, dict) else None
            if t:
                return t
        return datetime.min.replace(tzinfo=timezone.utc)

    unicos, vistos2 = [], set()
    for e in n + nuevos:
        if _c(e) not in vistos2:
            vistos2.add(_c(e))
            unicos.append(e)
    return copy.deepcopy(sorted(unicos, key=cuando))


# --- reglas por clave -----------------------------------------------------------------
def _uniones_lista(f: Fusion, clave: str, ruta: str, n: Any, l: Any) -> Any:
    if not isinstance(n, list) or not isinstance(l, list):
        return _escalar(f, clave, ruta, n, l)
    f.contar(clave, "iguales", len([x for x in l if x in n]))
    f.contar(clave, "de_local", len([x for x in l if x not in n]))
    f.contar(clave, "solo_nube", len([x for x in n if x not in l]))
    return n + [x for x in l if x not in n]


def _mas_reciente(f: Fusion, clave: str, ruta: str, n: Any, l: Any) -> Any:
    tn, tl = _t(n), _t(l)
    if _c(n) == _c(l):
        f.contar(clave, "iguales")
        return n
    if tn and tl:
        f.contar(clave, "fusionados")
        return l if tl > tn else n
    return f.conflicto(clave, ruta, n, l)


def _contacted(f: Fusion, clave: str, ruta: str, n: Any, l: Any) -> Any:
    if not isinstance(n, dict) or not isinstance(l, dict):
        return _escalar(f, clave, ruta, n, l)
    return {k: (_mas_reciente(f, clave, f"{ruta}.{k}", n[k], l[k]) if k in n and k in l
                else _escalar(f, clave, f"{ruta}.{k}", n.get(k, _FALTA), l.get(k, _FALTA)))
            for k in list(n) + [k for k in l if k not in n]}


def _contacted_por_cliente(f: Fusion, clave: str, ruta: str, n: Any, l: Any) -> Any:
    return _mapa(f, clave, ruta, n, l, _contacted)


def _secuencias(f: Fusion, clave: str, ruta: str, n: Any, l: Any) -> Any:
    if not isinstance(n, list) or not isinstance(l, list):
        return _escalar(f, clave, ruta, n, l)

    def ident(s: Dict[str, Any]) -> Tuple[Any, Any, Any]:
        return (s.get("client_id"), s.get("lead_key"), s.get("started"))

    def rango(s: Dict[str, Any]) -> Tuple[bool, int]:
        return (s.get("status") == "closed", int(s.get("step") or 0))

    por_id = {ident(s): copy.deepcopy(s) for s in n}
    orden = list(por_id)
    for s in l:
        i = ident(s)
        if i not in por_id:
            por_id[i] = copy.deepcopy(s)
            orden.append(i)
            f.contar(clave, "de_local")
        elif _c(por_id[i]) == _c(s):
            f.contar(clave, "iguales")
        elif rango(s) != rango(por_id[i]):
            f.contar(clave, "fusionados")
            if rango(s) > rango(por_id[i]):
                por_id[i] = copy.deepcopy(s)
        else:
            por_id[i] = f.conflicto(clave, f"{ruta}.{i[0]}|{i[1]}|{i[2]}", por_id[i], s)
    en_l = {ident(s) for s in l}
    f.contar(clave, "solo_nube", len([i for i in por_id if i not in en_l]))
    out = [por_id[i] for i in orden]
    # Invariante de open_sequence: una sola abierta por (cliente, lead).
    abiertas: Dict[Tuple[Any, Any], List[Dict[str, Any]]] = {}
    for s in out:
        if s.get("status") == "open":
            abiertas.setdefault((s.get("client_id"), s.get("lead_key")), []).append(s)
    for (cliente, lead), grupo in abiertas.items():
        if len(grupo) < 2:
            continue
        grupo.sort(key=lambda s: _t(s.get("started")) or datetime.max.replace(tzinfo=timezone.utc))
        for extra in grupo[1:]:
            f.nota(f"{ruta}.{cliente}|{lead}|{extra.get('started')}", grupo[0], extra,
                   "cerrada (duplicada): sobrevive la abierta más antigua")
            extra.update(status="closed", next_due=None, closed_reason="fusion_duplicada")
    return out


def _conversacion(f: Fusion, clave: str, ruta: str, n: Any, l: Any) -> Any:
    if not isinstance(n, list) or not isinstance(l, list):
        return _escalar(f, clave, ruta, n, l)
    unidos = _eventos(f, clave, ruta, n, l, campos_ts=("at",))
    return unidos[-SessionMemory.MAX_TURNS_STORED:]


def _hueco(f: Fusion, clave: str, ruta: str, n: Any, l: Any) -> Any:
    if _c(n) == _c(l):
        f.contar(clave, "iguales")
        return n
    if not isinstance(n, dict) or not isinstance(l, dict):
        return f.conflicto(clave, ruta, n, l)

    def ultimo(h: Dict[str, Any]) -> Optional[datetime]:
        marcas = [_t(h.get(c)) for c in ("ultima", "resuelta_en", "atendida_en", "descartada_en")]
        marcas = [m for m in marcas if m]
        return max(marcas) if marcas else None

    un, ul = ultimo(n), ultimo(l)
    if un is None and ul is None or un == ul:
        return f.conflicto(clave, ruta, n, l)
    gana, pierde = (l, n) if (ul and (un is None or ul > un)) else (n, l)
    out = {**pierde, **gana}
    out["veces"] = max(int(n.get("veces") or 1), int(l.get("veces") or 1))
    primeras = [p for p in (n.get("primera"), l.get("primera")) if _t(p)]
    if primeras:
        out["primera"] = min(primeras, key=_t)
    if out.get("estado") in ("resuelta", "atendida", "descartada"):
        out["esperando"] = []
    else:
        esp: Dict[str, Dict[str, Any]] = {}
        for e in (n.get("esperando") or []) + (l.get("esperando") or []):
            previo = esp.get(e.get("chat_id"))
            if previo is None or (_t(e.get("at")) or datetime.min.replace(tzinfo=timezone.utc)) >= \
                    (_t(previo.get("at")) or datetime.min.replace(tzinfo=timezone.utc)):
                esp[e.get("chat_id")] = e
        out["esperando"] = sorted(esp.values(), key=lambda e: _t(e.get("at")) or
                                  datetime.min.replace(tzinfo=timezone.utc))
    f.contar(clave, "fusionados")
    return out


def _versiones_de(ficha: Dict[str, Any]) -> List[Dict[str, Any]]:
    versiones = [dict(v) for v in ficha.get("knowledge_versions") or []]
    actual = (ficha.get("knowledge") or "").strip()
    if not versiones and actual:   # ficha anterior al historial (como _ensure_knowledge_versions)
        versiones = [{"version": int(ficha.get("knowledge_version") or 1), "knowledge": actual,
                      "chars": len(actual), "guardada": "", "motivo": "ficha anterior al historial"}]
    return versiones


def _conocimiento(f: Fusion, clave: str, ruta: str, n: Dict[str, Any],
                  l: Dict[str, Any]) -> Dict[str, Any]:
    """knowledge + knowledge_version + knowledge_versions de una ficha, juntos."""
    vn, vl = _versiones_de(n), _versiones_de(l)
    if not vn and not vl:
        return {c: n.get(c, l.get(c)) for c in _CAMPOS_CONOCIMIENTO if c in n or c in l}
    en_n = {(v.get("version"), v.get("knowledge")) for v in vn}
    en_l = {(v.get("version"), v.get("knowledge")) for v in vl}
    f.contar(clave, "iguales", len(en_n & en_l))
    f.contar(clave, "solo_nube", len(en_n - en_l))
    f.contar(clave, "de_local", len(en_l - en_n))
    todas = vn + [v for v in vl if (v.get("version"), v.get("knowledge")) not in en_n]
    origen = {id(v): ("nl" if (v.get("version"), v.get("knowledge")) in en_l else "n") for v in vn}
    origen.update({id(v): "l" for v in vl if id(v) not in origen})
    minimo = datetime.min.replace(tzinfo=timezone.utc)
    todas.sort(key=lambda v: (_t(v.get("guardada")) or minimo, int(v.get("version") or 0)))
    previo = 0
    for v in todas:
        numero = int(v.get("version") or 0)
        if numero <= previo:
            f.nota(f"{ruta}.knowledge_versions.v{numero}", _FALTA, v.get("knowledge"),
                   f"ambas se conservan; renumerada a v{previo + 1}")
            v["version"] = previo + 1
            numero = previo + 1
        previo = numero
    vigente = todas[-1]
    # Sin marca de tiempo que desempate (o igual en ambos lados) con textos distintos de
    # cada lado: no hay forma de saber cuál es la vigente. Gana la NUBE; `--local` invierte.
    tope = _t(vigente.get("guardada"))
    empatadas = [v for v in todas if _t(v.get("guardada")) == tope]
    if len({v.get("knowledge") for v in empatadas}) > 1 and \
            any(origen[id(v)] == "n" for v in empatadas) and any(origen[id(v)] == "l" for v in empatadas):
        ruta_k = f"{ruta}.knowledge"
        lado = "l" if ruta_k in f.locales else "n"
        ganadora = max((v for v in empatadas if lado in origen[id(v)]), key=lambda v: v["version"])
        f.nota(ruta_k, next(v["knowledge"] for v in empatadas if origen[id(v)] == "n"),
               next(v["knowledge"] for v in empatadas if origen[id(v)] == "l"),
               "local (forzado)" if lado == "l" else "nube")
        f.contar(clave, "fusionados")
        if ganadora is not vigente:   # queda vigente como versión nueva; el resto sigue en el historial
            vigente = {**ganadora, "version": vigente["version"] + 1,
                       "motivo": f"fusión: se conserva la vigente de {'local' if lado == 'l' else 'nube'}"}
            todas.append(vigente)
    sobran = len(todas) - max(1, MAX_KNOWLEDGE_VERSIONS)
    if sobran > 0:
        del todas[:sobran]
    return {"knowledge": vigente.get("knowledge") or "", "knowledge_version": vigente["version"],
            "knowledge_versions": todas}


_CAMPOS_CONOCIMIENTO = ("knowledge", "knowledge_version", "knowledge_versions")


def _ficha(f: Fusion, clave: str, ruta: str, n: Any, l: Any) -> Any:
    if not isinstance(n, dict) or not isinstance(l, dict):
        return _escalar(f, clave, ruta, n, l)
    reglas = {
        "conversations": lambda r, a, b: _mapa(f, clave, r, a, b, _conversacion),
        "knowledge_gaps": lambda r, a, b: _mapa(f, clave, r, a, b, _hueco),
        "whatsapp_handoffs": lambda r, a, b: _mapa(f, clave, r, a, b, _con_marca("at")),
        "lead_notes": lambda r, a, b: _mapa(f, clave, r, a, b, _plano),
    }
    out: Dict[str, Any] = {}
    for campo in list(n) + [c for c in l if c not in n]:
        if campo in _CAMPOS_CONOCIMIENTO:
            continue
        a, b = n.get(campo, _FALTA), l.get(campo, _FALTA)
        r = f"{ruta}.{campo}"
        out[campo] = reglas[campo](r, a, b) if campo in reglas and a is not _FALTA and b is not _FALTA \
            else _escalar(f, clave, r, a, b)
    out.update(_conocimiento(f, clave, ruta, n, l))
    return out


_REGLAS = {
    "clients": lambda f, c, r, n, l: _mapa(f, c, r, n, l, _ficha),
    "agent_status": lambda f, c, r, n, l: _plano(f, c, r, n, l),
    "sequences": _secuencias,
    "contacted": _contacted,
    "contacted_by_client": _contacted_por_cliente,
    "actions": _eventos,
    "used_emails": _uniones_lista,
    "pending_offers": lambda f, c, r, n, l: _mapa(f, c, r, n, l, _con_marca("ts")),
    "vendors": lambda f, c, r, n, l: _mapa(f, c, r, n, l, _plano),
    "functions": lambda f, c, r, n, l: _mapa(f, c, r, n, l, _plano),
}


def fusionar(nube: Dict[str, Any], local: Dict[str, Any], desde: Optional[str] = None,
             locales: Tuple[str, ...] = ()) -> Tuple[Dict[str, Any], Fusion]:
    """Devuelve (estado fusionado, Fusion con estadísticas y conflictos)."""
    f = Fusion(desde, locales)
    out: Dict[str, Any] = copy.deepcopy(nube)   # lo que la nube tenga y no entendamos, se conserva
    for clave in list(nube) + [k for k in local if k not in nube]:
        n, l = nube.get(clave, _FALTA), local.get(clave, _FALTA)
        regla = _REGLAS.get(clave)
        if regla is None:
            f.nota(clave, n, l, "clave desconocida: no se toca" + (" (no se agrega)" if n is _FALTA else ""))
            continue
        if n is _FALTA or l is _FALTA:
            out[clave] = copy.deepcopy(_escalar(f, clave, clave, n, l))
        else:
            out[clave] = regla(f, clave, clave, n, l)
    return out, f


# --- nube -----------------------------------------------------------------------------
def _credenciales() -> Tuple[str, str]:
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not (url and key):
        raise NubeNoDisponible("faltan SUPABASE_URL / SUPABASE_KEY")
    return url.rstrip("/"), key


def _pedir(method: str, path: str, body: Any = None, prefer: Optional[str] = None) -> Any:
    url, key = _credenciales()
    try:
        return sb_request(url, key, method, path, body=body, prefer=prefer)
    except (SupabaseError, OSError, ValueError) as e:
        raise NubeNoDisponible(str(e)) from e


def leer_nube() -> Tuple[Dict[str, Any], Optional[str]]:
    """Lectura fresca: va directo a la fila por HTTP, sin pasar por la caché de SupabaseMemory."""
    filas = _pedir("GET", f"{TABLE}?id=eq.{ROW_ID}&select=data,updated") or []
    if not filas:
        return {}, None
    return filas[0].get("data") or {}, filas[0].get("updated")


def escribir_nube(data: Dict[str, Any], version_leida: Optional[str]) -> None:
    """Upsert de la fila entera. Falla si alguien la cambió desde que se leyó."""
    filas = _pedir("GET", f"{TABLE}?id=eq.{ROW_ID}&select=updated") or []
    actual = filas[0].get("updated") if filas else None
    if actual != version_leida:
        raise RuntimeError("la fila de la nube cambió mientras se calculaba la fusión; reintenta")
    # Igual que SupabaseMemory.save(): el trigger de supabase_schema.sql pone el `updated`
    # real; el sello local solo cuenta si no hay trigger.
    _pedir("POST", f"{TABLE}?on_conflict=id&select=updated",
           body=[{"id": ROW_ID, "data": data, "updated": datetime.now(timezone.utc).isoformat()}],
           prefer="resolution=merge-duplicates,return=representation")
    releida, _ = leer_nube()
    if _c(releida) != _c(data):
        raise RuntimeError("la nube no quedó igual a la fusión después de escribir")


# --- respaldo + salida ------------------------------------------------------------------
def respaldar(nube: Dict[str, Any], local: Dict[str, Any]) -> Path:
    base = Path(ESTADO_RESPALDOS_DIR).expanduser()
    carpeta = base / (ESTADO_RESPALDO_PREFIJO + datetime.now().strftime("%Y%m%d-%H%M%S"))
    carpeta.mkdir(parents=True, mode=0o700)
    for nombre, datos in (("nube.json", nube), ("local.json", local)):
        fd = os.open(carpeta / nombre, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=2)
        os.chmod(carpeta / nombre, 0o600)
    return carpeta


def resumen(f: Fusion) -> str:
    lineas = [f"{'clave':<22}{'de local':>9}{'solo nube':>10}{'iguales':>9}{'fusion.':>9}{'conflic.':>9}"]
    for clave in sorted(set(f.stats) | {c["ruta"].split(".")[0] for c in f.conflictos}):
        s = f.stats.get(clave, {})
        nc = sum(1 for c in f.conflictos if c["ruta"].split(".")[0] == clave)
        lineas.append(f"{clave:<22}{s.get('de_local', 0):>9}{s.get('solo_nube', 0):>10}"
                      f"{s.get('iguales', 0):>9}{s.get('fusionados', 0):>9}{nc:>9}")
    if f.conflictos:
        lineas.append("")
        lineas.append(f"CONFLICTOS ({len(f.conflictos)}):")
        for c in f.conflictos:
            lineas.append(f"  {c['ruta']}  -> {c['resolucion']}\n"
                          f"      nube : {_corto(c['nube'])}\n      local: {_corto(c['local'])}")
    return "\n".join(lineas)


def a_revisar(nube: Dict[str, Any], local: Dict[str, Any], desde: Optional[str]) -> List[str]:
    """Pausas de WhatsApp y ofertas pendientes que están SOLO en la nube y son anteriores al
    corte: pudieron liberarse o cumplirse en local durante la caída (la fusión no distingue
    un borrado de una ausencia, así que se conservan y se piden a ojo)."""
    corte = _t(desde)

    def previo(ts: Any) -> bool:
        t = _t(ts)
        return True if corte is None or t is None else t < corte

    filas = []
    for cid, ficha in (nube.get("clients") or {}).items():
        locales = ((local.get("clients") or {}).get(cid) or {}).get("whatsapp_handoffs") or {}
        for lead, pausa in ((ficha or {}).get("whatsapp_handoffs") or {}).items():
            if lead not in locales and previo((pausa or {}).get("at")):
                filas.append(f"pausa de WhatsApp  clients.{cid}.whatsapp_handoffs.{lead}  "
                             f"(at {(pausa or {}).get('at')}): {_corto(pausa)}")
    locales = local.get("pending_offers") or {}
    for clave, oferta in (nube.get("pending_offers") or {}).items():
        if clave not in locales and previo((oferta or {}).get("ts")):
            filas.append(f"oferta pendiente   pending_offers.{clave}  (ts {(oferta or {}).get('ts')}): "
                         f"{_corto(oferta)}")
    return filas


def _firma(path: Path) -> Tuple[str, int]:
    """(hash, mtime_ns) de state.json: detecta que el backend lo escribió mientras tanto."""
    st = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), st.st_mtime_ns


def _retener_desde(valor: str, forzar: bool) -> int:
    if _t(valor) is None:
        print(f"--retener-desde: '{valor}' no es una fecha ISO válida.", file=sys.stderr)
        return 1
    destino = estado_retenido.ruta()
    if destino is None:
        print("El interruptor está desactivado (ZERO_ESTADO_RETENIDO_PATH vacío).", file=sys.stderr)
        return 1
    previo = estado_retenido.leer()
    if previo is not None and not forzar:
        print(f"Ya hay marcador en {destino.resolve()} desde {previo.get('desde')}; no se pisa "
              "(usa --forzar para reemplazarlo).")
        return 0
    if previo is not None:
        estado_retenido.liberar()
    if not estado_retenido.marcar("retención inicial manual (--retener-desde)", desde=valor,
                                  notificar=False):
        print(f"No pude escribir el marcador en {destino}.", file=sys.stderr)
        return 1
    print(f"Marcador creado en {destino.resolve()} con desde={valor}. No se tocó nada más.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Fusiona el estado de la nube con state.json local.")
    ap.add_argument("--aplicar", action="store_true", help="escribe la fusión (por defecto, dry-run)")
    ap.add_argument("--si", action="store_true", help="no pedir confirmación interactiva")
    ap.add_argument("--state", default=os.environ.get("STATE_PATH", "state.json"))
    ap.add_argument("--local", action="append", default=[], metavar="RUTA",
                    help="en un conflicto de esa ruta (p. ej. clients.acme.icp) conservar el LOCAL")
    ap.add_argument("--retener-desde", metavar="ISO",
                    help="solo crea el marcador con ese `desde` (idempotente) y sale")
    ap.add_argument("--forzar", action="store_true",
                    help="reemplaza un marcador existente (--retener-desde) o aplica sin marcador")
    args = ap.parse_args(argv)

    if args.retener_desde:
        return _retener_desde(args.retener_desde, args.forzar)

    estado = Path(args.state)
    print(f"Marcador : {estado_retenido.ruta() and estado_retenido.ruta().resolve()}\n"
          f"state.json: {estado.resolve()}\n")
    try:
        nube, version = leer_nube()
    except NubeNoDisponible as e:
        print(f"La nube aún no responde ({e}). No se tocó nada.", file=sys.stderr)
        return 2
    if not estado.exists():
        print(f"No existe {estado}: no hay nada local que fusionar.", file=sys.stderr)
        return 1
    try:
        firma = _firma(estado)
        local = load_json(estado)
    except (RuntimeError, OSError) as e:
        print(f"{estado} ilegible ({e}); no se toca nada.", file=sys.stderr)
        return 1

    marca = estado_retenido.leer()
    if args.aplicar and marca is None and not args.forzar:
        print("No hay marcador de estado retenido: no hay nada que reconciliar. "
              "Si de verdad quieres fusionar igual, usa --forzar.", file=sys.stderr)
        return 1
    desde = (marca or {}).get("desde")
    fusion, f = fusionar(nube, local, desde, tuple(args.local))
    print(f"Estado retenido desde: {desde or '(sin marcador)'}\n")
    print(resumen(f))
    revisar = a_revisar(nube, local, desde)
    if revisar:
        print(f"\nREVISAR ({len(revisar)}): solo existen en la nube y son anteriores al corte; "
              "podrían haberse liberado/cumplido en local durante la caída:")
        for fila in revisar:
            print(f"  {fila}")
    if not args.aplicar:
        print("\nDRY-RUN: no se escribió nada. Para aplicar: --aplicar")
        return 0

    if not args.si:
        try:
            respuesta = input(f"\nEscribe {ESTADO_CONFIRMACION} para aplicar la fusión: ")
        except EOFError:
            respuesta = ""
        if respuesta.strip() != ESTADO_CONFIRMACION:
            print("Cancelado: no se escribió nada.", file=sys.stderr)
            return 1

    def local_intacto() -> None:
        if _firma(estado) != firma:
            raise RuntimeError(f"{estado} cambió mientras se calculaba la fusión (el backend "
                               "escribió); reintenta, la fusión es idempotente")

    try:
        carpeta = respaldar(nube, local)
        print(f"\nRespaldo de ambas fuentes en {carpeta}")
        local_intacto()
        escribir_nube(fusion, version)
        local_intacto()
        save_json(estado, fusion)
        estado_retenido.liberar()
    except NubeNoDisponible as e:
        print(f"La nube dejó de responder ({e}). Marcador intacto.", file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as e:
        print(f"Falló la aplicación ({e}). Marcador intacto; el respaldo sigue en disco.",
              file=sys.stderr)
        return 1
    print(f"Listo: nube y {estado} fusionados; marcador liberado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
