"""Time-aware WhatsApp greetings for businesses operating in Chile."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .config import (WHATSAPP_AFTERNOON_START_HOUR, WHATSAPP_EVENING_START_HOUR,
                     WHATSAPP_MORNING_START_HOUR, WHATSAPP_TIME_ZONE)


_TIME_GREETING = r"(?:buenos\s+d[ií]as|buen\s+d[ií]a|buenas\s+tardes|buenas\s+noches)"
_COMPOUND_GREETING = re.compile(
    rf"^\s*(?P<bang>[¡!]?)\s*hola\b\s*[,!.¡]?\s*"
    rf"(?:(?P<name>[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{{2,30}})\s*[,!.]\s*)?"
    rf"{_TIME_GREETING}\b(?P<punct>[!.,]?)",
    re.IGNORECASE,
)
_OPENING_GREETING = re.compile(
    rf"^\s*([¡!]?)\s*(?:hola|{_TIME_GREETING})\b",
    re.IGNORECASE,
)


def whatsapp_greeting(at: datetime | None = None) -> str:
    """Return the correct salutation for the current time in Chile."""
    moment = at if at is not None else datetime.now(timezone.utc)
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("La hora de prueba debe incluir zona horaria")
    hour = moment.astimezone(ZoneInfo(WHATSAPP_TIME_ZONE)).hour
    if WHATSAPP_MORNING_START_HOUR <= hour < WHATSAPP_AFTERNOON_START_HOUR:
        return "Buenos días"
    if WHATSAPP_AFTERNOON_START_HOUR <= hour < WHATSAPP_EVENING_START_HOUR:
        return "Buenas tardes"
    return "Buenas noches"


def align_opening_greeting(reply: str, greeting: str) -> str:
    """Correct only an opening salutation, preserving the rest of the reply."""
    compound = _COMPOUND_GREETING.match(reply)
    if compound:
        name = ", " + compound.group("name") if compound.group("name") else ""
        rest = reply[compound.end():]
        if compound.group("bang"):
            rest = rest.strip()
            if rest and compound.group("punct") in ".,":
                rest = rest[0].upper() + rest[1:]
            return f"¡{greeting}{name}!" + (" " + rest if rest else "")
        return greeting + name + compound.group("punct") + rest
    return _OPENING_GREETING.sub(
        lambda match: ("¡" if match.group(1) else "") + greeting,
        reply, count=1,
    )
