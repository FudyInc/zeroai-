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
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_SEND_TYPES = ("whatsapp", "email")


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
    from .config import FUNCTION_ALLOWED_ACTION_TYPES, FUNCTION_MAX_ACTIONS_PER_RUN

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

    for action in actions:
        kind = str(action.get("type") or "").strip().lower()
        # Riel 2 — tipo permitido
        if kind not in FUNCTION_ALLOWED_ACTION_TYPES:
            reject(action, f"tipo de acción no permitido: {kind!r} "
                          f"(permitidos: {list(FUNCTION_ALLOWED_ACTION_TYPES)})")
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
