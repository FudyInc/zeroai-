"""Tests para el campo activity en Lead — extracción desde HTML."""
from __future__ import annotations

import unittest

from zero.contracts import Lead
from zero.discovery import DuckDuckGoSource


class ScriptedSource(DuckDuckGoSource):
    """DuckDuckGoSource con la red reemplazada por páginas enlatadas."""

    def __init__(self, results, pages, **kw):
        kw.setdefault("enrich", False)
        super().__init__(**kw)
        self._results = results          # [(title, url)]
        self._pages = pages              # {url: html}
        self.fetch_log = []

    def _search(self, query, n):
        return self._results[:n]

    def _get(self, url, data=None):
        self.fetch_log.append(url)
        return self._pages.get(url)


def _src(results, pages, **kw):
    return ScriptedSource(results, pages, **kw)


class ActivityExtractionTest(unittest.TestCase):
    """Extracción de actividad del negocio desde meta description y title."""

    def test_meta_description_preferred_over_title(self):
        """Meta description tiene prioridad sobre title."""
        page = """<html>
          <head>
            <title>Onza Marketing</title>
            <meta name="description" content="Agencia de marketing digital con soluciones
              de publicidad en redes sociales y posicionamiento web">
          </head>
        </html>"""
        activity = DuckDuckGoSource._activity(page, "Onza Marketing")
        self.assertIsNotNone(activity)
        self.assertIn("marketing digital", activity.lower())
        self.assertIn("publicidad", activity.lower())

    def test_title_used_when_no_description(self):
        """Si no hay meta description, se usa el title."""
        page = "<html><head><title>Soluciones de software para retail</title></head></html>"
        activity = DuckDuckGoSource._activity(page, "Soluciones de software para retail")
        self.assertEqual(activity, "Soluciones de software para retail")

    def test_no_activity_without_any_evidence(self):
        """Sin meta description ni title útil, devuelve None."""
        page = "<html><head><title></title></head></html>"
        activity = DuckDuckGoSource._activity(page, "")
        self.assertIsNone(activity)

    def test_generic_wordpress_placeholder_rejected(self):
        """Descripciones genéricas de plantillas se descartan."""
        page = """<html>
          <head>
            <meta name="description" content="Just another WordPress site">
          </head>
        </html>"""
        activity = DuckDuckGoSource._activity(page, "")
        self.assertIsNone(activity)

    def test_generic_spanish_placeholder_rejected(self):
        """Placeholders españoles genéricos se descartan."""
        page = """<html>
          <head>
            <meta name="description" content="Sitio en construcción">
          </head>
        </html>"""
        activity = DuckDuckGoSource._activity(page, "")
        self.assertIsNone(activity)

    def test_html_entities_unescaped(self):
        """Las entidades HTML se convierten."""
        page = """<html>
          <head>
            <meta name="description" content="Dise&ntilde;o de sitios web &amp; SEO">
          </head>
        </html>"""
        activity = DuckDuckGoSource._activity(page, "")
        self.assertIn("ñ", activity)
        self.assertIn("&", activity)

    def test_activity_trimmed_to_200_chars(self):
        """Descripciones largas se cortan a ~200 caracteres."""
        long_desc = "A" * 250
        page = f'<html><head><meta name="description" content="{long_desc}"></head></html>'
        activity = DuckDuckGoSource._activity(page, "")
        self.assertLessEqual(len(activity), 200)
        self.assertTrue(activity.endswith("…"))

    def test_multiple_spaces_collapsed(self):
        """Espacios múltiples se colapsan a uno."""
        page = """<html>
          <head>
            <meta name="description" content="Agencia    de    marketing   digital">
          </head>
        </html>"""
        activity = DuckDuckGoSource._activity(page, "")
        self.assertEqual(activity, "Agencia de marketing digital")

    def test_lead_with_activity_roundtrip(self):
        """Lead con activity se serializa y deserializa correctamente."""
        original = Lead(
            company="Onza Marketing",
            role="Gerente",
            channel="email",
            activity="Agencia de marketing digital"
        )
        d = original.to_dict()
        restored = Lead.from_dict(d)
        self.assertEqual(restored.activity, "Agencia de marketing digital")

    def test_lead_without_activity_compatible(self):
        """Lead sin activity (datos antiguos) sigue siendo válido."""
        # Simular un lead guardado sin el campo activity
        d = {
            "company": "Pyme Antigua",
            "role": "CEO",
            "channel": "email",
            "name": "Juan",
            "email": "juan@pyme.cl",
        }
        lead = Lead.from_dict(d)
        self.assertEqual(lead.company, "Pyme Antigua")
        self.assertIsNone(lead.activity)

    def test_activity_in_real_discovery_flow(self):
        """El campo activity viaja desde discovery hasta el lead."""
        home = """<html>
          <head>
            <title>CumbreData</title>
            <meta name="description" content="Análisis de datos y business intelligence para empresas">
          </head>
          <body>contacto: hola@cumbredata.io</body>
        </html>"""
        src = _src(
            [("CumbreData", "https://cumbredata.io/")],
            {"https://cumbredata.io/": home}
        )
        leads = src.search_leads("data analytics", max_items=1, channels=["email"])
        self.assertEqual(len(leads), 1)
        lead = leads[0]
        self.assertIsNotNone(lead.get("activity"))
        self.assertIn("datos", lead.get("activity", "").lower())


if __name__ == "__main__":
    unittest.main()
