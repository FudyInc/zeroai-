"""Tests de zero/activity.py — actividad del equipo (panel de Equipo).

Cubre la heurística de huecos (activo vs se fue) y la suma semanal. No prueba
"cuánto trabaja alguien de verdad" — eso es justamente el límite honesto que
el propio módulo documenta.
"""
import tempfile
import unittest
from pathlib import Path

from zero.activity import ActivityLog, _week_start


class TouchTest(unittest.TestCase):
    def setUp(self):
        self.log = ActivityLog(None)   # sin path -> no persiste, solo memoria

    def test_first_touch_never_counts(self):
        self.log.touch("diego@zeroai.cl", now=1000.0)
        self.assertEqual(self.log.week_hours("diego@zeroai.cl", as_of=1000.0), 0.0)

    def test_short_gap_counts_as_active(self):
        self.log.touch("diego@zeroai.cl", now=1000.0)
        self.log.touch("diego@zeroai.cl", now=1000.0 + 120)   # 2 min después
        self.assertAlmostEqual(self.log.week_hours("diego@zeroai.cl", as_of=1000.0 + 120), 2 / 60, places=2)

    def test_long_gap_does_not_count(self):
        self.log.touch("diego@zeroai.cl", now=1000.0)
        self.log.touch("diego@zeroai.cl", now=1000.0 + 3600)   # 1h después -> se fue
        self.assertEqual(self.log.week_hours("diego@zeroai.cl", as_of=1000.0 + 3600), 0.0)

    def test_accumulates_across_several_short_touches(self):
        t = 1000.0
        self.log.touch("diego@zeroai.cl", now=t)
        for _ in range(5):
            t += 60   # 1 min entre cada uno
            self.log.touch("diego@zeroai.cl", now=t)
        # 5 huecos de 1 min cada uno = 5 min activos
        self.assertAlmostEqual(self.log.week_hours("diego@zeroai.cl", as_of=t), 5 / 60, places=2)

    def test_tracks_people_independently(self):
        self.log.touch("diego@zeroai.cl", now=1000.0)
        self.log.touch("diego@zeroai.cl", now=1060.0)
        self.log.touch("maureen@zeroai.cl", now=1000.0)
        self.assertGreater(self.log.week_hours("diego@zeroai.cl", as_of=1060.0), 0.0)
        self.assertEqual(self.log.week_hours("maureen@zeroai.cl", as_of=1060.0), 0.0)

    def test_empty_or_missing_email_is_a_no_op(self):
        self.log.touch("", now=1000.0)
        self.log.touch(None, now=1000.0)   # nunca lanza
        self.assertEqual(self.log.days, {})


class WeekBoundaryTest(unittest.TestCase):
    def test_week_start_is_monday(self):
        # 2026-07-20 es lunes
        self.assertEqual(_week_start("2026-07-20"), "2026-07-20")
        self.assertEqual(_week_start("2026-07-23"), "2026-07-20")   # jueves misma semana
        self.assertEqual(_week_start("2026-07-19"), "2026-07-13")   # domingo, semana anterior

    def test_activity_from_last_week_is_not_counted_this_week(self):
        log = ActivityLog(None)
        log.touch("diego@zeroai.cl", now=1000.0)
        log.touch("diego@zeroai.cl", now=1030.0)
        # Fuerza el bucket a un día de la semana pasada a mano, simulando que
        # el tiempo activo se registró hace más de una semana.
        log.days = {"2026-07-13": {"diego@zeroai.cl": 30.0}}
        self.assertEqual(log.week_hours("diego@zeroai.cl", as_of=1_774_000_000), 0.0)


class PersistenceTest(unittest.TestCase):
    def test_save_and_reload_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "activity.json")
            log = ActivityLog(path)
            log.touch("diego@zeroai.cl", now=1000.0)
            log.touch("diego@zeroai.cl", now=1060.0)
            log.save()

            reloaded = ActivityLog(path)
            self.assertEqual(reloaded.days, log.days)
            self.assertGreater(reloaded.week_hours("diego@zeroai.cl", as_of=1060.0), 0.0)

    def test_missing_file_starts_empty_not_raise(self):
        log = ActivityLog("/tmp/esto-no-existe-nunca-zeroai-activity.json")
        self.assertEqual(log.days, {})


if __name__ == "__main__":
    unittest.main()
