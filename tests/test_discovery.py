"""Tests de la discovery web real **sin red**.

Un `ScriptedSource` sirve resultados de búsqueda y páginas HTML enlatadas, así
probamos la lógica de extracción/minería con lo que las PyMEs publican de verdad
(directorios listicle, emails ofuscados, contacto solo en /contacto, teléfonos
placeholder) sin depender de DuckDuckGo ni de ningún sitio vivo.
"""
from __future__ import annotations

import unittest

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


class DirectoryMiningTest(unittest.TestCase):
    """Un listicle no es un lead: se minan sus links a PyMEs reales."""

    LISTICLE = """
      <html><title>Las 10 mejores agencias de marketing en Santiago</title><body>
        <a href="https://pyme1.cl/servicios">Pyme Uno</a>
        <a href="https://pyme2.cl/">Pyme Dos</a>
        <a href="https://facebook.com/pyme1">FB</a>
        <a href="https://sortlist.com/otra-lista">Otro directorio</a>
      </body></html>"""
    PYME1 = '<html><title>Pyme Uno</title><body>escríbenos a hola@pyme1.cl</body></html>'
    PYME2 = '<html><title>Pyme Dos</title><body><a href="tel:+56972345678">llámanos</a></body></html>'

    def test_listicle_is_mined_not_delivered(self):
        src = _src(
            [("Las 10 mejores agencias de marketing en Santiago", "https://listas.cl/mejores-agencias")],
            {"https://listas.cl/mejores-agencias": self.LISTICLE,
             "https://pyme1.cl": self.PYME1, "https://pyme2.cl": self.PYME2},
            contact_fetches=0,
        )
        leads = src.search_leads("agencias marketing", max_items=5, channels=["email", "whatsapp"])

        domains = [l["domain"] for l in leads]
        self.assertNotIn("listas.cl", domains)             # el directorio no es un lead
        self.assertEqual(domains, ["pyme1.cl", "pyme2.cl"])  # sus links sí
        self.assertEqual(leads[0]["email"], "hola@pyme1.cl")
        self.assertEqual(leads[1]["phone"], "+56972345678")
        # social y otros directorios no entran a la cola
        self.assertNotIn("https://facebook.com", src.fetch_log)
        self.assertNotIn("https://sortlist.com", src.fetch_log)

    def test_known_aggregator_domain_is_directory_even_without_listicle_title(self):
        src = _src([], {})
        self.assertTrue(src._looks_directory("Sortlist", "https://www.sortlist.com/l/cl",
                                             "sortlist.com"))
        self.assertTrue(src._looks_directory("Top 30 agencias", "https://x.cl/top-30", "x.cl"))
        self.assertFalse(src._looks_directory("Onza Marketing", "https://onzamarketing.cl/",
                                              "onzamarketing.cl"))

    def test_ddg_ads_are_not_results(self):
        self.assertIsNone(DuckDuckGoSource._resolve(
            "https://duckduckgo.com/y.js?ad_domain=ebay.com&ad_provider=bingv7aa"))
        self.assertEqual(DuckDuckGoSource._resolve(
            "//duckduckgo.com/l/?uddg=https%3A%2F%2Fpyme.cl%2F"), "https://pyme.cl/")


class ContactExtractionTest(unittest.TestCase):
    """Señales de contacto en sitios PyME heterogéneos."""

    def test_contact_page_fallback(self):
        home = "<html><title>Pyme</title><body>bienvenidos</body></html>"
        contacto = '<body><a href="mailto:ventas@pyme.cl">ventas</a></body>'
        src = _src([("Pyme", "https://pyme.cl/")],
                   {"https://pyme.cl/": home, "https://pyme.cl/contacto": contacto})
        leads = src.search_leads("x", max_items=1, channels=["email"])
        self.assertEqual(leads[0]["email"], "ventas@pyme.cl")

    def test_mailto_beats_body_scan(self):
        page = ('<body>soporte de terceros: ayuda@plataforma.com '
                '<a href="mailto:hola@pyme.cl">hola</a></body>')
        self.assertEqual(_src([], {})._best_email(page, "pyme.cl"), "hola@pyme.cl")

    def test_obfuscated_email_is_recovered(self):
        src = _src([], {})
        self.assertEqual(src._best_email("<body>ventas (arroba) pyme (punto) cl</body>", "pyme.cl"),
                         "ventas@pyme.cl")
        self.assertEqual(src._best_email("<body>contacto [at] pyme.cl</body>", "pyme.cl"),
                         "contacto@pyme.cl")
        # un "at" inglés suelto NO inventa un email
        self.assertIsNone(src._best_email("<body>find us at pyme.cl</body>", "pyme.cl"))

    def test_form_placeholder_emails_rejected(self):
        src = _src([], {})
        self.assertIsNone(src._best_email("<body>escribe a usuario@dominio.com</body>", "pyme.cl"))
        self.assertIsNone(src._best_email("<body>nombre@ejemplo.cl</body>", "pyme.cl"))
        self.assertEqual(src._best_email("<body>ventas@pyme.cl</body>", "pyme.cl"), "ventas@pyme.cl")

    def test_short_first_chunk_keeps_full_name(self):
        src = _src([], {})
        self.assertEqual(src._clean_name("D - Marketing Chile", "d-marketingchile.cl"),
                         "D - Marketing Chile")
        self.assertEqual(src._clean_name("Onza Marketing | Agencia digital", "onzamarketing.cl"),
                         "Onza Marketing")

    def test_placeholder_phone_rejected(self):
        src = _src([], {})
        self.assertIsNone(src._first_phone('<a href="tel:999999999">tel</a>'))
        self.assertEqual(src._first_phone('<a href="tel:+56972345678">tel</a>'), "+56972345678")


class DecisionMakerEnrichmentTest(unittest.TestCase):
    """Extracción de nombre+rol del decisor — hallado en vivo (2026-07-13,
    auditando discovery.py contra un ICP de estudios contables) que un
    testimonio tipo "Nombre Rol, Otra Empresa Ltda." podía capturar el
    nombre de la empresa citada en vez de la persona."""

    def test_testimonial_with_other_company_name_is_rejected(self):
        src = _src([], {})
        text = ('Gepa y la confianza es total." Roberto Fuentes Director, '
                'Constructora Fuentes Ltda. "Excelente manejo de nuestras remuneraciones."')
        name, role = src._extract_person(text, company="Gepa")
        self.assertIsNone(name)
        self.assertIsNone(role)

    def test_real_decision_maker_is_still_found(self):
        src = _src([], {})
        text = "Conócenos — Marion Altamirano, Fundadora de ContablExpert."
        name, role = src._extract_person(text, company="ContablExpert")
        self.assertEqual(name, "Marion Altamirano")
        self.assertEqual(role, "Fundadora")

    def test_generic_business_words_still_rejected(self):
        src = _src([], {})
        text = "Nuestro equipo — Diseño Web, Gerente de todo el sitio."
        name, role = src._extract_person(text, company="Pyme")
        self.assertIsNone(name)

    def test_testimonial_naming_a_real_person_still_rejected_by_quote(self):
        # Mismo patrón, pero la empresa citada NO tiene ningún sufijo legal
        # ("Ltda", "Constructora", etc.) — solo la comilla de cierre delata que
        # es un testimonio de cliente, no la ficha del propio equipo.
        src = _src([], {})
        text = ('"El equipo es proactivo y siempre nos mantiene informados." '
                'Carla Moreno Socia, Clínica Dental Moreno & Asociados')
        name, role = src._extract_person(text, company="Gepa")
        self.assertIsNone(name)
        self.assertIsNone(role)

    def test_team_bio_without_quote_still_found(self):
        # Sin comilla de por medio (ficha de equipo real, no testimonio) el
        # patrón "Rol, Nombre" sigue funcionando como antes.
        src = _src([], {})
        text = "Nuestro equipo: Directora, Andrea Salinas — 10 años de experiencia."
        name, role = src._extract_person(text, company="Pyme")
        self.assertEqual(name, "Andrea Salinas")


if __name__ == "__main__":
    unittest.main()
