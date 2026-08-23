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
            text: str = "", via: str = "") -> Dict[str, Any]:
    """Forma única de respuesta — igual en mock y en real, para no dar falsa confianza."""
    return {"alert": True, "status": status, "to": to, "reason": reason,
            "text": text, "via": via}


def _owner_email() -> str:
    """A qué correo avisar: `OWNER_EMAIL_TO`, o el propio remitente SMTP.

    Caer al remitente es deliberado: un aviso que se manda a sí mismo llega igual a
    la bandeja del dueño y no exige configurar nada nuevo. Sin SMTP tampoco hay
    respaldo, y eso se reporta en vez de fallar en silencio."""
    return ((os.environ.get("OWNER_EMAIL_TO") or "").strip()
            or (os.environ.get("SMTP_FROM") or "").strip()
            or (os.environ.get("SMTP_USER") or "").strip())


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

    if outbox is None:
        try:
            from .channels import make_outbox
            outbox = make_outbox()
        except Exception as e:   # noqa: BLE001 — avisar nunca puede romper al que avisa
            return _result("error", reason=str(e), text=text)

    # Se manda por TODOS los canales configurados, no por uno con respaldo.
    #
    # La razón es que "envío exitoso" no significa "mensaje entregado": el POST a
    # Twilio (y a Meta) responde `queued`/`accepted`, y el fallo real llega después,
    # asíncrono. Comprobado el 2026-08-22 en la consola de Twilio — tres avisos con
    # `status: sent` de nuestro lado y `failed / 63015` del suyo, porque el número
    # había salido del sandbox (caduca cada 72 horas). Un respaldo que se activa solo
    # cuando el primer canal "falla" nunca se habría activado.
    #
    # Un aviso es la única pieza cuyo fallo nadie más nota, porque justamente avisa
    # cuando nadie está mirando. Frente a eso, un correo duplicado cuando ambos
    # canales funcionan es un precio ridículamente bajo — y el SMTP ya está conectado,
    # así que no agrega servicio ni cuenta nueva.
    intentos, salio, destino_ok, via_ok = [], False, None, []
    for canal, destino in (("whatsapp", (os.environ.get("OWNER_WHATSAPP_TO") or "").strip()),
                           ("email", _owner_email())):
        if not destino:
            intentos.append(f"{canal}: sin destinatario")
            continue
        try:
            msg = {"channel": canal, "to": destino, "body": text}
            if canal == "email":
                msg["subject"] = "ZeroAI — aviso del sistema"
            res = outbox.send(msg) or {}
        except Exception as e:   # noqa: BLE001
            intentos.append(f"{canal}: {e}")
            continue
        if res.get("status") != "error":
            salio, destino_ok = True, destino_ok or destino
            via_ok.append(canal)
        else:
            intentos.append(f"{canal}: {res.get('error') or 'error'}")

    if salio:
        # La ventana se marca solo cuando algo salió. Si todo falla, el próximo evento
        # debe poder reintentar en vez de quedar callado 30 minutos.
        _last_sent[kind] = stamp
        return _result("sent", to=destino_ok, text=text, via="+".join(via_ok),
                       reason=" | ".join(intentos))

    # Ningún canal salió. Sin destinatarios es "skipped" (la config por defecto, no un
    # fallo); con destinatarios que fallaron es "error" y hay que verlo.
    fallo_real = any(": sin destinatario" not in i for i in intentos)
    return _result("error" if fallo_real else "skipped",
                   reason=" | ".join(intentos), text=text)
