"""Acciones que una función programada PIDE — validadas y ejecutadas afuera.

El punto de todo este módulo: que una función pueda *hacer* cosas (mandar un
WhatsApp, mover un lead de etapa) sin romper la garantía de seguridad del
sandbox. La regla es una sola:

    el código sandboxeado NUNCA actúa — solo DEVUELVE lo que quiere que pase.

Una función corre con `--network=none` y sin credenciales (zero/sandbox.py).
Si para mandar un WhatsApp le diéramos red y el token, cualquier código pegado
en el panel podría exfiltrar el CRM completo o las keys. En vez de eso, la
función deja las acciones en su `result`, como datos:

    result = {"actions": [
        {"type": "whatsapp", "lead": "ceo@acme.cl", "body": "hola..."},
        {"type": "stage", "lead": "+56911112222", "stage": "contacted"},
        {"type": "note", "lead": "ceo@acme.cl", "text": "sin respuesta 7 días"},
    ]}

...y este módulo —que corre del lado confiable, fuera de Docker— las valida
contra la política de `config.py` y recién ahí las ejecuta reusando el Outbox y
el CRM de siempre. Nada de esto le da al sandbox una sola capacidad nueva.

Los rieles que se aplican SIEMPRE, en orden:
  1. Tope de cantidad (FUNCTION_MAX_ACTIONS_PER_RUN) — un bucle con bug no se
     convierte en un envío masivo accidental.
  2. Tipo permitido (FUNCTION_ALLOWED_ACTION_TYPES).
  3. El lead tiene que existir Y pertenecer al cliente de la función — una
     función de un cliente jamás puede tocar los leads de otro.
  4. Un lead con opt-out (BLOCK_TAG) nunca recibe mensajes.
Nada de esto lanza: una acción inválida se rechaza con motivo y queda en el
reporte, sin frenar a las demás ni tumbar la corrida.

--- trabajos de agente (2026-08-04) -------------------------------------------
Además de tocar leads uno por uno, una función puede pedir que corran los
AGENTES — es lo que convierte al panel en una empresa que trabaja sola:

    result = {"actions": [
        {"type": "pipeline", "query": "agencias en Santiago", "count": 5},
        {"type": "followups"},
    ]}

Misma regla de siempre (el sandbox pide, este lado ejecuta), pero con rieles
propios porque un trabajo de agente no se parece en nada a mover una etapa:
  - Es por CLIENTE, no por lead: se resuelve ANTES del lookup de lead.
  - Tope aparte y mucho más bajo (FUNCTION_MAX_JOBS_PER_RUN): cada uno sale a
    la web, llama al modelo y tarda minutos.
  - Tope duro de leads por corrida (FUNCTION_JOB_MAX_COUNT), por encima de lo
    que pida la función — nadie mira una corrida de las 07:00.
  - NUNCA envía (FUNCTION_JOBS_AUTO_SEND=False): lo redactado queda en borrador
    esperando aprobación humana.
  - Se NIEGA a correr con agentes en mock: sintetizaría leads falsos y los
    escribiría en el CRM real, indistinguibles de trabajo de verdad.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_SEND_TYPES = ("whatsapp", "email")


def run_job(action: Dict[str, Any], client_id: str, zero: Any) -> str:
    """Corre UN trabajo de agente pedido por una función y devuelve el detalle
    para el reporte. Client-scoped, no lead-scoped: acá no se resuelve ningún
    lead (por eso se llama antes del lookup en apply_actions).

    Siempre en modo revisión (FUNCTION_JOBS_AUTO_SEND): lo que redacte queda en
    borrador esperando aprobación humana. Es la diferencia entre una empresa
    que trabaja sola y una que además manda sola — lo primero es el objetivo,
    lo segundo es un riesgo que nadie está mirando a las 07:00."""
    from .config import FUNCTION_JOB_MAX_COUNT, FUNCTION_JOBS_AUTO_SEND

    # Con agentes en mock, run_pipeline sintetiza leads deterministas y los
    # escribe en el CRM real — basura indistinguible de trabajo hecho, y nadie
    # mirando a las 07:00. Mejor no correr y decir por qué.
    if getattr(zero, "_engine_mode", None) == "mock":
        raise ValueError("no hay motor real disponible (ni modelo local ni API) — "
                         "un trabajo de agente en mock inventaría leads")

    kind = str(action.get("type") or "").strip().lower()

    if kind == "followups":
        out = zero.run_followups(client_id, as_of=action.get("as_of"),
                                 auto_send=FUNCTION_JOBS_AUTO_SEND)
        avanzados = out.get("advanced") or out.get("processed") or 0
        return f"seguimientos: {avanzados}"

    # pipeline — necesita a qué buscar. El tier sale del cliente registrado
    # (memory) y solo se acepta del action como último recurso: es política de
    # negocio, no algo que deba redefinir cada función suelta.
    query = str(action.get("query") or "").strip()
    if not query:
        raise ValueError("el trabajo 'pipeline' necesita 'query' (qué buscar)")
    count = action.get("count") or 5
    try:
        count = max(1, min(int(count), FUNCTION_JOB_MAX_COUNT))
    except (TypeError, ValueError):
        raise ValueError(f"'count' inválido: {action.get('count')!r}")

    # El tier sale del cliente ya registrado en la memoria del orquestador.
    memory = getattr(zero, "memory", None)
    tier = None
    if memory is not None:
        tier = ((getattr(memory, "clients", {}) or {}).get(client_id) or {}).get("tier")
    tier = tier or action.get("tier")
    if not tier:
        raise ValueError(f"no sé el tier de {client_id!r} — regístralo antes de automatizarlo")

    out = zero.run_pipeline(client_id, tier, query, count=count,
                            auto_send=FUNCTION_JOBS_AUTO_SEND)
    entregados = len(out.get("delivered") or out.get("qualified") or [])
    return f"pipeline: {entregados} calificados de {count} intentos"


def extract_actions(result: Any) -> List[Dict[str, Any]]:
    """Las acciones pedidas en el `result` de una función, o [] si no pidió
    ninguna. Tolerante a propósito: el `result` de una función es lo que quiso
    devolver quien la escribió (un número, un texto, una lista, lo que sea) —
    solo un dict con una lista en "actions" cuenta como pedido de acciones;
    cualquier otra cosa es un resultado normal, no un error."""
    if not isinstance(result, dict):
        return []
    actions = result.get("actions")
    if not isinstance(actions, list):
        return []
    return [a for a in actions if isinstance(a, dict)]


def _resolve_lead(action: Dict[str, Any], client_id: str, crm: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(registro del lead, motivo de rechazo). El lead se identifica por email o
    teléfono — `ctx.leads` a propósito NO expone la `key` interna del CRM (ver
    zero/functions.py), así que ese es el único identificador que la función
    conoce.

    El chequeo que importa: `find_by_contact` busca en TODOS los clientes, así
    que hay que confirmar que el lead encontrado pertenece al cliente de la
    función. Sin esto, una función del cliente A podría mandarle mensajes a los
    leads del cliente B con solo poner su email."""
    contact = str(action.get("lead") or "").strip()
    if not contact:
        return None, "sin 'lead' (email o teléfono del destinatario)"
    rec = crm.find_by_contact(phone=contact, email=contact)
    if rec is None:
        return None, f"no hay ningún lead con ese contacto: {contact!r}"
    if rec.get("client_id") != client_id:
        return None, (f"ese lead pertenece a otro cliente — una función de "
                      f"{client_id!r} no puede tocar leads de {rec.get('client_id')!r}")
    return rec, None


def apply_actions(result: Any, fn: Dict[str, Any], crm: Any,
                  zero: Any = None) -> Dict[str, Any]:
    """Valida y ejecuta las acciones que pidió una función. Devuelve el reporte:

        {"requested": int, "applied": int,
         "results":  [{"type", "lead", "detail"}],
         "rejected": [{"action", "reason"}]}

    `zero` es el orquestador (duck-typed, sin importarlo — mismo criterio que
    zero/vendors.py::clients_count_for para evitar el import circular). Se usa
    solo para los envíos: `zero._deliver` ya resuelve las credenciales del
    vendedor asignado, el nombre del remitente y el registro en el historial —
    reusarlo evita tener dos caminos de envío que se desalineen. Sin `zero`,
    las acciones de envío se rechazan con motivo claro (las de CRM sí corren).
    """
    from .config import (FUNCTION_ALLOWED_ACTION_TYPES, FUNCTION_ALLOWED_JOB_TYPES,
                         FUNCTION_MAX_ACTIONS_PER_RUN, FUNCTION_MAX_JOBS_PER_RUN)

    actions = extract_actions(result)
    report: Dict[str, Any] = {"requested": len(actions), "applied": 0,
                             "results": [], "rejected": []}
    if not actions:
        return report

    client_id = (fn.get("lookup_scope") or {}).get("client_id")
    if not client_id:
        report["rejected"] = [{"action": a, "reason": "la función no tiene lookup_scope.client_id"}
                             for a in actions]
        return report

    def reject(action: Dict[str, Any], reason: str) -> None:
        report["rejected"].append({"action": action, "reason": reason})

    # Riel 1 — tope de cantidad. Lo que pasa del tope se rechaza ENTERO y queda
    # visible; nunca se ejecuta "la mitad" en silencio.
    if len(actions) > FUNCTION_MAX_ACTIONS_PER_RUN:
        for a in actions[FUNCTION_MAX_ACTIONS_PER_RUN:]:
            reject(a, f"pasa el tope de {FUNCTION_MAX_ACTIONS_PER_RUN} acciones por corrida")
        actions = actions[:FUNCTION_MAX_ACTIONS_PER_RUN]

    jobs_done = 0
    for action in actions:
        kind = str(action.get("type") or "").strip().lower()

        # Trabajos de agente: por CLIENTE, no por lead — se resuelven acá,
        # antes del lookup de lead (que no aplica) y con su propio tope, mucho
        # más bajo que el de las acciones normales porque cada uno sale a la
        # web, llama al modelo y tarda minutos.
        if kind in FUNCTION_ALLOWED_JOB_TYPES:
            if zero is None:
                reject(action, "trabajo de agente no disponible en este contexto (sin orquestador)")
                continue
            if jobs_done >= FUNCTION_MAX_JOBS_PER_RUN:
                reject(action, f"pasa el tope de {FUNCTION_MAX_JOBS_PER_RUN} "
                              f"trabajo(s) de agente por corrida")
                continue
            try:
                detail = run_job(action, client_id, zero)
            except ValueError as e:
                reject(action, str(e))
                continue
            except Exception as e:   # noqa: BLE001 — un trabajo roto no tumba los demás
                reject(action, f"falló al ejecutar: {e}")
                continue
            jobs_done += 1
            report["applied"] += 1
            report["results"].append({"type": kind, "lead": None, "detail": detail})
            continue

        # Riel 2 — tipo permitido
        if kind not in FUNCTION_ALLOWED_ACTION_TYPES:
            reject(action, f"tipo de acción no permitido: {kind!r} (permitidos: "
                          f"{list(FUNCTION_ALLOWED_ACTION_TYPES) + list(FUNCTION_ALLOWED_JOB_TYPES)})")
            continue
        # Riel 3 — el lead existe y es de este cliente
        rec, why = _resolve_lead(action, client_id, crm)
        if rec is None:
            reject(action, why or "lead no resuelto")
            continue
        key = rec["key"]
        # Riel 4 — opt-out: un lead que pidió no ser contactado nunca recibe
        # mensajes (mover de etapa o dejar una nota sí es válido: son registro
        # interno, no contacto).
        if kind in _SEND_TYPES and crm.is_blocked(client_id, key):
            reject(action, "ese lead pidió no ser contactado (opt-out)")
            continue

        try:
            if kind in _SEND_TYPES:
                if zero is None:
                    reject(action, "envío no disponible en este contexto (sin orquestador)")
                    continue
                body = str(action.get("body") or "").strip()
                if not body:
                    reject(action, "mensaje vacío")
                    continue
                to = rec.get("email") if kind == "email" else (rec.get("phone") or rec.get("email"))
                res = zero._deliver(client_id, key, to, {
                    "channel": kind,
                    "subject": action.get("subject") if kind == "email" else None,
                    "body": body,
                })
                detail = f"{res.get('status')}/{res.get('via')}"
            elif kind == "stage":
                stage = str(action.get("stage") or "").strip()
                rec2 = crm.set_stage(client_id, key, stage, detail="función programada")
                if rec2 is None:
                    reject(action, "el lead desapareció al aplicar la etapa")
                    continue
                detail = f"→ {stage}"
            else:   # note
                text = str(action.get("text") or "").strip()
                if not text:
                    reject(action, "nota vacía")
                    continue
                crm.log(client_id, key, "function_note", text[:200])
                detail = text[:80]
        except ValueError as e:      # etapa inválida (CRM_STAGES) — motivo claro
            reject(action, str(e))
            continue
        except Exception as e:       # noqa: BLE001 — una acción rota no tumba las demás
            reject(action, f"falló al ejecutar: {e}")
            continue

        report["applied"] += 1
        report["results"].append({"type": kind, "lead": key, "detail": detail})

    return report
