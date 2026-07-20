"""Actividad del equipo — cuánto tiempo cada persona estuvo de verdad usando
el dashboard, acumulado por día y por semana. Parte del panel de Equipo
(admin-only) que Diego pidió el 2026-07-20: ver trabajo pendiente y horas
conectadas por persona, con una meta de 20h/semana para empezar (solo CCO).

Aproximación honesta, NO un timesheet real — no hay nada que lo sea sin pedir
que alguien reporte su tiempo a mano:
  - Mide huecos entre requests autenticados de esa persona. Un hueco corto
    (<= ACTIVE_GAP_MINUTES, mismo criterio que "en línea" del panel) se cuenta
    como tiempo activo; uno largo no (se asume que se fue, no que trabajó
    sin tocar el dashboard durante ese rato).
  - Punto ciego conocido: trabajo hecho FUERA del dashboard (una llamada,
    WhatsApp desde el celular, una reunión) no se captura. Por eso el
    objetivo de 20h aplica solo a roles cuyo trabajo real ES el dashboard
    (CCO) — no a roles que pasan buena parte del tiempo en otro lado.
  - Punto ciego inverso: una pestaña abierta sin actividad real cuenta como
    "conectado" mientras el navegador siga pidiendo datos (queries de
    react-query). No es prueba de trabajo, es proxy de uso del dashboard.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .persistence import load_json, save_json

ACTIVE_GAP_MINUTES = 5.0   # mismo umbral que "en línea" en api.py::_ONLINE_WINDOW_SECONDS
WEEKLY_GOAL_HOURS = 20.0


def _day_key(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _week_start(day: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    monday = d - timedelta(days=d.weekday())
    return monday.strftime("%Y-%m-%d")


class ActivityLog:
    """`self.days`: {"YYYY-MM-DD": {email: minutos_activos}}. Guardado plano,
    igual criterio que crm.json/state.json (JSON local, con `.bak`)."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else None
        self.days: Dict[str, Dict[str, float]] = {}
        self._last_seen: Dict[str, float] = {}   # solo en memoria — para medir el próximo hueco
        if self.path and self.path.exists():
            self._load()

    def touch(self, email: str, now: Optional[float] = None) -> None:
        """Llamar en cada request autenticado de `email` (mismo punto que el
        tracker de "en línea" del panel de Equipo). Nunca lanza."""
        if not email:
            return
        now = now if now is not None else time.time()
        prev = self._last_seen.get(email)
        self._last_seen[email] = now
        if prev is None or now <= prev:
            return
        gap_minutes = (now - prev) / 60.0
        if gap_minutes > ACTIVE_GAP_MINUTES:
            return   # hueco largo -> se fue, no cuenta como activo
        day = _day_key(now)
        bucket = self.days.setdefault(day, {})
        bucket[email] = round(bucket.get(email, 0.0) + gap_minutes, 2)

    def week_hours(self, email: str, as_of: Optional[float] = None) -> float:
        as_of_day = _day_key(as_of if as_of is not None else time.time())
        start = _week_start(as_of_day)
        total_minutes = 0.0
        for day, bucket in self.days.items():
            if start <= day <= as_of_day:
                total_minutes += bucket.get(email, 0.0)
        return round(total_minutes / 60.0, 2)

    def save(self) -> None:
        if not self.path:
            return
        save_json(self.path, {"days": self.days})

    def _load(self) -> None:
        data = load_json(self.path)
        self.days = data.get("days", {}) if isinstance(data, dict) else {}
