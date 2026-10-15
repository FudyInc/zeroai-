#!/usr/bin/env python3
"""Arnés de la etapa 0: reproduce el set de evaluación contra el agente actual.

Mide, no cambia. No toca `num_ctx`, `think`, temperatura ni el servicio de
Ollama: la etapa 0 existe para dar una línea base contra la cual comparar esos
cambios después.

Qué garantiza el aislamiento:

- Memoria y CRM locales en un directorio temporal. Nunca Supabase: se construye
  `SessionMemory` directo, no `store.make_memory`, así que no hay forma de que
  una escritura llegue a la nube.
- `_deliver` queda reemplazado por un registrador. No se envía nada a nadie.
- Backend **local a secas**, sin `FallbackBackend`. En producción, si Ollama no
  responde contesta Claude pagado; acá eso sería gastar plata sin pedirlo, así
  que un fallo del local se reporta como fallo.

Reproduce con *teacher forcing*: cada caso se evalúa con el historial real que
lo precedió, no con lo que el agente fue respondiendo. Es lo correcto para esta
medición, porque el largo del prompt —y por tanto el truncado que se busca— lo
determina el historial real.

Uso:
    python3 scripts/evaluar_linea_base.py --set /tmp/set-evaluacion.json \\
        --salida docs/evaluacion/crudo-2026-10-15.jsonl --limite 20
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "rubrica_evaluacion", REPO / "scripts" / "rubrica_evaluacion.py")
rubrica = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rubrica)


class BackendMedido:
    """Envuelve el backend local y anota cuántos tokens evaluó Ollama.

    `LocalBackend.complete` devuelve solo el texto y descarta `usage`, que es
    justo el dato de la etapa 0. En vez de tocar el motor —prohibido en esta
    etapa— se repite acá la misma petición y se guarda lo que la respuesta
    informa. El payload lo arma el backend real, así que el prompt medido es
    idéntico al de producción.
    """

    def __init__(self, interno):
        self.interno = interno
        self.ultima: Dict[str, Any] = {}

    def complete(self, system: str, user: str, model: str, max_tokens: int = 4096) -> str:
        payload = self.interno._build_payload(system, user, max_tokens)
        cuerpo = json.dumps(payload).encode("utf-8")
        peticion = urllib.request.Request(
            f"{self.interno.base_url}/chat/completions", data=cuerpo,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.interno.api_key}"},
            method="POST")
        inicio = time.monotonic()
        with urllib.request.urlopen(peticion, timeout=self.interno.timeout) as resp:
            datos = json.loads(resp.read().decode("utf-8"))
        uso = datos.get("usage") or {}
        self.ultima = {
            "prompt_tokens": uso.get("prompt_tokens"),
            "completion_tokens": uso.get("completion_tokens"),
            "caracteres_system": len(system),
            "caracteres_user": len(user),
            "latencia_s": round(time.monotonic() - inicio, 2),
            "modelo": payload.get("model"),
        }
        try:
            return datos["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"respuesta inesperada del backend local: {datos!r}") from exc


def contexto_de_salida(salida: str, modelo: str) -> Optional[int]:
    """Lee la columna CONTEXT de `ollama ps`.

    Se ubica por el encabezado, no por el final de la línea: la fila termina en
    «4 minutes from now», así que buscar el último número devuelve la hora.
    """
    lineas = [l for l in (salida or "").splitlines() if l.strip()]
    if not lineas:
        return None
    encabezado = lineas[0]
    if "CONTEXT" not in encabezado:
        return None
    inicio = encabezado.index("CONTEXT")
    for linea in lineas[1:]:
        if not linea.startswith(modelo.split(":")[0]):
            continue
        encontrado = re.match(r"\s*(\d+)", linea[inicio:])
        if encontrado:
            return int(encontrado.group(1))
    return None


def contexto_cargado(modelo: str) -> Optional[int]:
    """El `num_ctx` con que Ollama tiene cargado el modelo ahora mismo."""
    try:
        salida = subprocess.run(["ollama", "ps"], capture_output=True, text=True,
                                timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return contexto_de_salida(salida, modelo)


def truncados_en_log(desde: str) -> int:
    """Cuántas veces Ollama registró un truncado de entrada desde una marca."""
    try:
        salida = subprocess.run(
            ["journalctl", "-u", "ollama", "--since", desde, "--no-pager"],
            capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return -1
    return len(re.findall(r"truncat", salida, re.IGNORECASE))


def construir_motor(tmp: Path, client_id: str, ficha: str, precios: Dict[str, Any],
                    perfil: Dict[str, Any]):
    """Un ZERO aislado con el mismo cerebro que atiende WhatsApp en producción."""
    from zero.agents import build_agents
    from zero.backends import LocalBackend
    from zero.config import WHATSAPP_ENGINE
    from zero.crm import CRM
    from zero.memory import SessionMemory
    from zero.orchestrator import Zero

    modelo = ((os.environ.get("WHATSAPP_MODEL") or "").strip() or
              (os.environ.get("LOCAL_MODEL") or "").strip() or WHATSAPP_ENGINE["model"])
    url = (os.environ.get("LOCAL_MODEL_URL") or "").strip() or WHATSAPP_ENGINE["base_url"]
    medido = BackendMedido(LocalBackend(model=modelo, base_url=url))

    memoria = SessionMemory(str(tmp / "state.json"))
    memoria.set_client_knowledge(client_id, ficha)
    if precios:
        memoria.set_client_pricing(client_id, precios)
    memoria.set_client_agent_profile(client_id, perfil)

    crm = CRM(None)
    agentes = build_agents(backend=medido, mock=False)
    agentes["CONCIERGE"].prompt_file = "concierge-whatsapp-local.md"
    zero = Zero(agentes, memory=memoria, crm=crm)

    enviados: List[Dict[str, Any]] = []

    def _registrar(client, key, to, msg, **kw):
        enviados.append({"to": to, "body": (msg or {}).get("body", "")})
        return {"status": "sent", "via": "arnes-sin-envio"}

    zero._deliver = _registrar          # nada sale de acá
    return zero, memoria, medido, modelo, enviados


def correr(casos: List[Dict[str, Any]], zero, memoria, medido, numero: str,
           ) -> List[Dict[str, Any]]:
    filas: List[Dict[str, Any]] = []
    for indice, caso in enumerate(casos, start=1):
        client_id = caso["client_id"]
        chat = f"{caso['chat']}@c.us"
        # Teacher forcing: el historial real, no lo que el agente fue diciendo.
        memoria.clients.setdefault(client_id, {}).setdefault("conversations", {})[
            caso["chat"]] = [dict(t) for t in caso.get("historial") or []]
        memoria.clients[client_id].pop("whatsapp_handoffs", None)
        medido.ultima = {}
        inicio = time.monotonic()
        error = ""
        try:
            resultado = zero.handle_inbound(caso["chat"], caso["mensaje"],
                                            to_phone_id=numero, whatsapp_chat_id=chat)
        except Exception as exc:                      # noqa: BLE001
            resultado, error = {}, f"{type(exc).__name__}: {exc}"
        fila = {
            "id": caso["id"],
            "client_id": client_id,
            "turnos_previos": caso.get("turnos_previos", 0),
            "etiquetas": caso.get("etiquetas", []),
            "mensaje": caso["mensaje"],
            "reply": str((resultado or {}).get("reply") or ""),
            "intent": (resultado or {}).get("intent"),
            "manual_review": bool((resultado or {}).get("manual_review")),
            "matched": bool((resultado or {}).get("matched")),
            "error": error,
            "latencia_s": round(time.monotonic() - inicio, 2),
            "uso": dict(medido.ultima),
        }
        fila["rubrica"] = rubrica.evaluar(caso, resultado or {})
        filas.append(fila)
        marca = "!" if (error or not fila["rubrica"]["limpio"]) else "."
        print(marca, end="", flush=True)
        if indice % 50 == 0:
            print(f" {indice}/{len(casos)}", flush=True)
    print(flush=True)
    return filas


def resumir(filas: List[Dict[str, Any]], num_ctx: Optional[int],
            truncados: int) -> Dict[str, Any]:
    total = len(filas)
    tokens = sorted(f["uso"].get("prompt_tokens") or 0 for f in filas
                    if (f["uso"].get("prompt_tokens") or 0) > 0)
    latencias = sorted(f["latencia_s"] for f in filas)

    def percentil(valores: List[float], p: float) -> float:
        if not valores:
            return 0.0
        return valores[min(len(valores) - 1, int(round((len(valores) - 1) * p)))]

    familias: Dict[str, int] = {}
    for fila in filas:
        for familia in (fila["rubrica"].get("hallazgos") or {}):
            familias[familia] = familias.get(familia, 0) + 1

    rozan = [t for t in tokens if num_ctx and t >= num_ctx * 0.9]
    return {
        "casos": total,
        "errores": sum(1 for f in filas if f["error"]),
        "limpios": sum(1 for f in filas if f["rubrica"]["limpio"] and not f["error"]),
        "handoff": sum(1 for f in filas if f["manual_review"]),
        "hallazgos_por_familia": familias,
        "latencia_p50": percentil(latencias, 0.50),
        "latencia_p95": percentil(latencias, 0.95),
        "prompt_tokens_min": tokens[0] if tokens else None,
        "prompt_tokens_p50": percentil([float(t) for t in tokens], 0.50) if tokens else None,
        "prompt_tokens_max": tokens[-1] if tokens else None,
        "num_ctx_cargado": num_ctx,
        "turnos_rozando_el_limite": len(rozan),
        "truncados_en_log_de_ollama": truncados,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", dest="conjunto", required=True)
    parser.add_argument("--salida", required=True, help="JSONL con una fila por turno")
    parser.add_argument("--resumen", default="", help="JSON con los agregados")
    parser.add_argument("--cliente", default="losetaschile")
    parser.add_argument("--numero", default="56964537891", help="receptor que enruta a la empresa")
    parser.add_argument("--desde", type=int, default=0, help="índice inicial, para correr por tandas")
    parser.add_argument("--limite", type=int, default=0, help="cuántos casos correr (0 = todos)")
    parser.add_argument("--raiz-ficha", default="/home/diego/zeroai",
                        help="checkout desde el que leer ficha y precios, en solo lectura")
    args = parser.parse_args(argv)

    with open(args.conjunto, encoding="utf-8") as fuente:
        conjunto = json.load(fuente)
    casos = [c for c in conjunto["casos"] if c["client_id"] == args.cliente]
    casos = casos[args.desde:]
    if args.limite:
        casos = casos[:args.limite]
    if not casos:
        print("no hay casos para esa selección", file=sys.stderr)
        return 1

    # Ficha y precios reales, leídos una vez y nunca escritos.
    sys.path.insert(0, args.raiz_ficha)
    cwd = os.getcwd()
    os.chdir(args.raiz_ficha)
    try:
        from zero.store import make_memory
        produccion = make_memory("state.json")
        ficha = produccion.get_client_knowledge(args.cliente)
        precios = produccion.get_client_pricing(args.cliente)
        perfil = dict(produccion.get_client_agent_profile(args.cliente) or {})
    finally:
        os.chdir(cwd)
    perfil.setdefault("whatsapp_number", args.numero)
    perfil["response_mode"] = "automatic"

    marca = time.strftime("%Y-%m-%d %H:%M:%S")
    with tempfile.TemporaryDirectory(prefix="linea-base-") as tmp:
        zero, memoria, medido, modelo, _ = construir_motor(
            Path(tmp), args.cliente, ficha, precios, perfil)
        print(f"modelo: {modelo} · casos: {len(casos)} · ficha: {len(ficha)} caracteres")
        filas = correr(casos, zero, memoria, medido, args.numero)

    resumen = resumir(filas, contexto_cargado(modelo), truncados_en_log(marca))
    Path(args.salida).parent.mkdir(parents=True, exist_ok=True)
    with open(args.salida, "w", encoding="utf-8") as destino:
        for fila in filas:
            destino.write(json.dumps(fila, ensure_ascii=False) + "\n")
    if args.resumen:
        with open(args.resumen, "w", encoding="utf-8") as destino:
            json.dump(resumen, destino, indent=1, ensure_ascii=False)
            destino.write("\n")
    print(json.dumps(resumen, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
