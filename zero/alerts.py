"""Avisos al dueño cuando algo que cuesta plata se enciende solo.

Frontera al exterior, así que sigue la disciplina del repo: **mock por defecto**.
Sin `OWNER_WHATSAPP_TO` en el entorno, o sin `OUTBOX_LIVE=1`, no sale nada real —
pero la forma del resultado es idéntica, así que el código que llama no distingue.

Transporte: el MISMO WhatsApp que ya usa el producto (Outbox → Twilio/Meta). No se
agrega dependencia, cuenta ni servicio nuevo: el aviso llega al celular por el
canal que ya está probado y andando.

Antirrebote: un motor local caído no genera un aviso por mensaje. Se avisa una vez
por ventana (`ALERT_THROTTLE_MINUTES`), porque 200 notificaciones seguidas no
informan más que una — solo vuelven el teléfono inusable justo cuando hay que
prestar atención.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

# Último aviso enviado, por tipo. En memoria a propósito: el backend es un proceso
# largo (systemd, Restart=always), así que la ventana sobrevive lo que tiene que
# sobrevivir. Un reinicio permite un aviso extra, que es el lado correcto en el que
# equivocarse — mejor un aviso de más que perder el primero de una caída nueva.
_last_sent: Dict[str, float] = {}


def _result(status: str, *, to: Optional[str] = None, reason: str = "",
            text: str = "") -> Dict[str, Any]:
    """Forma única de respuesta — igual en mock y en real, para no dar falsa confianza."""
    return {"alert": True, "status": status, "to": to, "reason": reason, "text": text}


def reset_throttle() -> None:
    """Limpia la ventana de antirrebote. Para los tests; en producción no se usa."""
    _last_sent.clear()


def notify_owner(text: str, *, kind: str = "generic",
                 throttle_minutes: Optional[float] = None,
                 outbox: Optional[Any] = None,
                 now: Optional[float] = None) -> Dict[str, Any]:
    """Manda `text` al WhatsApp del dueño. Nunca levanta: un aviso que falla no
    puede tumbar lo que estaba avisando.

    `kind` separa las ventanas de antirrebote (dos problemas distintos se avisan
    los dos, aunque caigan juntos). `outbox` y `now` se inyectan en los tests.
    """
    from .config import ALERT_THROTTLE_MINUTES

    window = (ALERT_THROTTLE_MINUTES if throttle_minutes is None else throttle_minutes) * 60.0
    stamp = time.time() if now is None else now

    last = _last_sent.get(kind)
    if last is not None and window > 0 and (stamp - last) < window:
        return _result("throttled", reason=f"ya se avisó hace {int(stamp - last)}s", text=text)

    to = (os.environ.get("OWNER_WHATSAPP_TO") or "").strip()
    if not to:
        # No es un error: es la configuración por defecto. Sin número, no hay a quién avisar.
        return _result("skipped", reason="OWNER_WHATSAPP_TO no configurado", text=text)

    try:
        if outbox is None:
            from .channels import make_outbox
            outbox = make_outbox()
        res = outbox.send({"channel": "whatsapp", "to": to, "body": text})
    except Exception as e:   # noqa: BLE001 — avisar nunca puede romper al que avisa
        return _result("error", to=to, reason=str(e), text=text)

    # Solo se marca la ventana si el envío no falló: si falló, el próximo mensaje
    # debe poder reintentar el aviso en vez de quedar silenciado por 30 minutos.
    if (res or {}).get("status") != "error":
        _last_sent[kind] = stamp
    return _result((res or {}).get("status", "sent"), to=to, text=text)
