"""Discovery sources — where PROSPECTOR finds *real* candidate companies.

Like the LLM backends, the source is a swappable object behind one method,
`search_leads(query, max_items, channels)`. Today: `DuckDuckGoSource`, a no-key
web search (HTML endpoint) + page fetch + contact extraction, stdlib only.
Tomorrow a keyed provider (Brave/SerpAPI) drops in with the same signature and
PROSPECTOR doesn't change.

Web extraction is best-effort: many sites expose no email, so candidates often
arrive without a verified contact — exactly the kind of lead ZERO's qualified
gate is meant to filter. Coverage tricks for heterogeneous SME sites: listicle/
directory results ("Las 10 mejores agencias…") are mined for the real company
links they contain instead of delivered as leads, and when a homepage exposes
no contact at all the /contacto page is tried before giving up.
"""
from __future__ import annotations

import html
import re
import sys
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from .config import DEFAULT_VALIDATOR_TIER

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# mailto: is to email what tel: is to phone — the strongest signal on a page.
_MAILTO_RE = re.compile(r'mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})', re.I)
# `tel:` links are the most reliable phone signal; the text patterns are strict
# on purpose (a bare "1.42857143" from JS must not look like a phone).
_TEL_HREF_RE = re.compile(r'tel:\s*([+()\d][\d\s().\-]{6,}\d)', re.I)
_PHONE_TEXT_RE = re.compile(r"(?:\+?56[\s.\-]?)?9[\s.\-]?\d{4}[\s.\-]?\d{4}")  # Chilean mobile
_INTL_PHONE_RE = re.compile(r"\+\d{1,3}[\s.\-]?(?:\(?\d{1,4}\)?[\s.\-]?){2,4}\d")  # +CC ...
_RESULT_RE = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_SITE_NAME_RE = re.compile(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_META_DESC_RE = re.compile(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']', re.I)

_BAD_EMAIL_HINTS = ("example.", "sentry", "wixpress", "@2x", "@3x", ".png", ".jpg", ".gif", ".webp",
                    # placeholders de formularios ("usuario@dominio.com"), no contactos
                    "usuario@", "nombre@", "ejemplo", "tucorreo", "tudominio",
                    "youremail", "yourdomain",
                    # Encontrado en vivo (2026-08-22): el lead "Abc" entró al CRM de
                    # zeroai como CALIFICADO (score 70) con el correo
                    # `tumail@dominio.xx` — un placeholder de plantilla web. La lista
                    # tenía "tucorreo"/"tudominio" pero no estas variantes, así que
                    # pasó el validador y quedó con un borrador listo para enviarse a
                    # una dirección que no existe. Un lead falso no solo se pierde:
                    # ocupa un cupo del gate y ensucia la tasa de respuesta real.
                    #
                    # "@dominio." y "@tuempresa." llevan arroba Y punto a propósito: sin
                    # la arroba se descartaría `contacto@midominio.cl`, y sin el punto,
                    # `ventas@tuempresafeliz.cl`. Ambos son negocios reales — un filtro
                    # que se pasa de listo borra leads legítimos, que es peor que dejar
                    # entrar uno falso (el falso lo pesca la primera respuesta rebotada;
                    # el legítimo borrado no se entera nadie).
                    "tumail", "tuemail", "tunombre@", "sucorreo", "sudominio",
                    "@dominio.", "@tudominio", "@tuempresa.", "yourname@", "yourmail")

# Industry detection keywords: map industries to phrases found on web pages.
# Used to enrich leads with industry/rubro information.
_INDUSTRY_KEYWORDS = {
    "fintech": ["banco", "pago", "cripto", "tarjeta", "financiero", "préstamo",
                "inversión", "wallet", "transacción", "fintech", "transferencia",
                "criptomoneda", "mercado de valores", "bróker"],
    "retail": ["tienda", "store", "shop", "comercio", "venta", "retail", "ecommerce",
               "compra", "cliente", "producto", "catálogo", "boutique"],
    "saas": ["software", "aplicación", "app", "plataforma", "sistema", "saas", "cloud",
             "herramienta", "servicio digital", "solución web", "suscripción"],
    "healthcare": ["salud", "médico", "clínica", "hospital", "doctor", "enfermería",
                   "farmacia", "healthcare", "telemedicina", "paciente", "médica"],
    "education": ["educación", "colegio", "universidad", "curso", "formación",
                  "escuela", "académico", "capacitación", "learning", "taller"],
    "manufacturing": ["manufactura", "fábrica", "producción", "industrial", "maquinaria",
                      "fabricación", "factory", "línea de producción"],
    "real_estate": ["inmuebles", "propiedad", "real estate", "terreno", "vivienda",
                    "construcción", "proyecto inmobiliario", "casas", "departamentos"],
    "logistics": ["logística", "transporte", "envío", "almacén", "distribución",
                  "courier", "carga", "fleet"],
    "marketing": ["agencia", "marketing", "publicidad", "advertising", "campaña",
                  "digital", "branding", "comunicación", "redes sociales"],
    "consulting": ["consultoría", "asesoría", "consulting", "asesor", "consultor"],
}

# Decision-maker enrichment: a role keyword near a person name on an about/team
# page. Order matters — list specific titles before generic ones so the longer
# match wins at a given position.
_ROLES = [
    "CEO", "CTO", "COO", "CMO", "CFO", "CRO",
    "Co-Founder", "Cofounder", "Co-fundador", "Cofundador", "Founder", "Fundadora", "Fundador",
    "Gerente General", "Gerente Comercial", "Gerente de Ventas", "Gerente de Marketing", "Gerente",
    "Director Comercial", "Director Ejecutivo", "Director General", "Directora", "Director",
    "Head of Growth", "Head of Sales", "Head of Marketing", "Head of",
    "Country Manager", "Sales Manager", "Marketing Manager",
    "Jefe de Ventas", "Jefe Comercial",
    "Vicepresidente", "Presidente", "Socio", "Socia", "Owner", "Dueño", "Propietario",
]
_ROLE_RE = re.compile(r"\b(" + "|".join(re.escape(r) for r in _ROLES) + r")\b", re.I)
_ROLE_CANON = {r.lower(): r for r in _ROLES}
_NAME = r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){1,2}"
_SEP = r"[,\-–—:|·()]+"
# A name must sit right next to the role, joined by a delimiter — "Name — Role"
# or "Role: Name". This adjacency kills most false positives from a loose window.
_NAME_BEFORE_RE = re.compile(r"(" + _NAME + r")\s*" + _SEP + r"\s*$")
_NAME_AFTER_RE = re.compile(r"^\s*" + _SEP + r"\s*(" + _NAME + r")")
# Capitalized words that are not names — keeps "Marketing Digital" / "Diseño Web" out.
_NOT_NAME = {
    "marketing", "digital", "agencia", "chile", "santiago", "ventas", "servicios", "comercial",
    "contacto", "nosotros", "empresa", "equipo", "clientes", "proyectos", "blog", "inicio",
    "home", "email", "whatsapp", "teléfono", "telefono", "dirección", "direccion", "google",
    "gerente", "director", "directora", "fundador", "founder", "manager", "socio", "head",
    "diseño", "web", "desarrollo", "redes", "sociales", "social", "media", "sitio", "páginas",
    "paginas", "posicionamiento", "publicidad", "estrategia", "gestión", "gestion", "online",
    "creativa", "creativo", "branding", "consultora", "consultoria", "soluciones", "tecnología",
    "contador", "contadora", "auditor", "auditora", "contable", "contables", "abogado", "abogada",
    "ingeniero", "ingeniera", "consultor", "asesor", "asesora", "profesional", "profesionales",
    # Sufijos/palabras de razón social — sin esto, un testimonio tipo "Roberto
    # Fuentes Director, Constructora Fuentes Ltda." captura el NOMBRE DE OTRA
    # EMPRESA citada como si fuera la persona (hallado en vivo, 2026-07-13,
    # auditando discovery.py contra "estudios contables Santiago").
    "ltda", "ltda.", "limitada", "spa", "eirl", "cia", "cía", "compañía", "compania",
    "constructora", "inmobiliaria", "corp", "corp.", "hnos", "hermanos", "sociedad",
}
_ENRICH_PATHS = ("nosotros", "equipo", "quienes-somos", "sobre-nosotros", "about", "team")
# SME sites often expose contact info only on the contact page, not the homepage.
_CONTACT_PATHS = ("contacto", "contact", "contactenos", "contactanos")

# Generic placeholder descriptions to skip — full matches only, case-insensitive.
_GENERIC_DESCRIPTIONS = (
    "just another", "another wordpress", "sitio en construcción",
    "en construcción", "coming soon", "site under construction",
)


def _is_generic_description(text: str) -> bool:
    """Check if a description is a generic placeholder."""
    text_lower = text.lower()
    for generic in _GENERIC_DESCRIPTIONS:
        if generic in text_lower:
            return True
    return False


def _clean_activity(text: str) -> str:
    """Clean and normalize activity description: unescape HTML, trim whitespace, limit length."""
    cleaned = html.unescape(text).strip()
    # Collapse multiple spaces.
    cleaned = re.sub(r"\s+", " ", cleaned)
    # Limit to ~200 chars.
    if len(cleaned) > 200:
        cleaned = cleaned[:197] + "…"
    return cleaned

# Search engines, social, and aggregators aren't the company sites we want as leads.
_SKIP_DOMAINS = (
    "duckduckgo.com", "google.", "bing.com", "yahoo.com",
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "wikipedia.org", "yelp.com", "pinterest.com",
    "amazon.", "mercadolibre.", "wordpress.com", "blogspot.com",
    "wa.me", "api.whatsapp.com", "goo.gl", "bit.ly", "t.me", "maps.google",
)

# Directory/listicle pages ("Las 10 mejores agencias…") are not leads themselves,
# but they LINK to dozens of real SME sites — so we mine them instead of skipping
# (or worse, delivering the directory as a "lead").
_DIRECTORY_DOMAINS = (
    "sortlist.com", "clutch.co", "linkatomic.com", "goodfirms.co", "designrush.com",
    "semrush.com", "trustpilot.com", "paginasamarillas.", "amarillas.", "cylex",
)
_LISTICLE_RE = re.compile(
    r"(?:\b|[-/_])(las?[-\s]?\d+|los[-\s]?\d+|top[-\s]?\d+|\d+[-\s]mejores|mejores"
    r"|ranking|directorio|listado)(?:\b|[-/_])", re.I)
_HREF_RE = re.compile(r'<a[^>]+href=["\'](https?://[^"\'#?]+)', re.I)


class DiscoverySource:
    """Interface: turn a query into normalized lead candidates."""

    def search_leads(self, query: str, max_items: int, channels: List[str]) -> List[Dict[str, Any]]:
        raise NotImplementedError


class DuckDuckGoSource(DiscoverySource):
    """No-key web discovery via DuckDuckGo's HTML endpoint."""

    SEARCH_URL = "https://html.duckduckgo.com/html/"

    def __init__(self, timeout: float = 8.0, max_fetch: Optional[int] = None,
                 enrich: bool = True, enrich_fetches: int = 3,
                 contact_fetches: int = 2, mine_directories: int = 3, mine_links: int = 10):
        self.timeout = timeout
        self.max_fetch = max_fetch
        self.enrich = enrich              # look up the decision-maker (name + role)
        self.enrich_fetches = enrich_fetches  # max extra about/team page fetches per company
        self.contact_fetches = contact_fetches    # max contact-page fetches per company
        self.mine_directories = mine_directories  # max listicle pages mined per search
        self.mine_links = mine_links              # max SME links taken from each one

    def search_leads(self, query: str, max_items: int, channels: List[str],
                      tier: str = DEFAULT_VALIDATOR_TIER) -> List[Dict[str, Any]]:
        # Directories cost fetches but yield no lead directly, so the default
        # budget leaves headroom beyond one fetch per lead.
        budget = self.max_fetch or max_items * 2
        queue = list(self._search(query, n=max_items * 3))

        leads: List[Dict[str, Any]] = []
        seen: set = set()
        fetched = mined = 0
        while queue and len(leads) < max_items and fetched < max(budget, max_items):
            title, url = queue.pop(0)
            domain = self._domain(url)
            if not domain or domain in seen or any(b in domain for b in _SKIP_DOMAINS):
                continue
            seen.add(domain)
            fetched += 1

            page = self._get(url) or ""
            if self._looks_directory(title, url, domain):
                if mined < self.mine_directories:
                    mined += 1
                    for u in self._mine_directory(page, domain)[:self.mine_links]:
                        queue.append((self._domain(u), u))
                continue
            email = self._best_email(page, domain)
            phone = self._first_phone(page)
            if not email and not phone:
                email, phone = self._contact_lookup(domain)
            company = self._company_name(page, title, domain)
            name, role = (None, None)
            if self.enrich:
                try:
                    name, role = self._enrich(domain, page, company)
                except Exception:
                    name, role = (None, None)
            activity = self._activity(page, title)
            industry = self._detect_industry(page, activity or "", title, domain)
            leads.append({
                "company": company,
                "domain": domain,
                "name": name,
                "role": role,                 # filled only when we found real evidence
                "email": email,
                "phone": phone,
                "channel": self._pick_channel(channels, email, phone),
                "source": "duckduckgo",
                "url": url,
                "activity": activity,
                "industry": industry,
            })

        from .validators import ValidatorRules  # local import: avoid cycle with validators.py
        raw = len(leads)
        leads = ValidatorRules.validate_batch(leads, tier)
        pct = round(100 * len(leads) / raw) if raw else 100
        print(f"DuckDuckGoSource: {raw} raw → {len(leads)} valid ({pct}%)", file=sys.stderr)
        return leads

    # --- directory mining ------------------------------------------------------
    @staticmethod
    def _looks_directory(title: str, url: str, domain: str) -> bool:
        if any(d in domain for d in _DIRECTORY_DOMAINS):
            return True
        return bool(_LISTICLE_RE.search(f"{title} {url}"))

    def _mine_directory(self, page: str, own_domain: str) -> List[str]:
        """Pull the external company links out of a listicle/directory page —
        each one is an SME candidate worth visiting as if it were a result."""
        out: List[str] = []
        seen: set = set()
        for u in _HREF_RE.findall(page or ""):
            d = self._domain(u)
            if (not d or d == own_domain or d in seen
                    or any(b in d for b in _SKIP_DOMAINS)
                    or any(b in d for b in _DIRECTORY_DOMAINS)):
                continue
            seen.add(d)
            out.append(f"https://{d}")   # the homepage, not whatever deep link they used
        return out

    def _contact_lookup(self, domain: str) -> Tuple[Optional[str], Optional[str]]:
        """Homepage had no contact at all — try the contact page before giving up."""
        for i, path in enumerate(_CONTACT_PATHS):
            if i >= self.contact_fetches:
                break
            page = self._get(f"https://{domain}/{path}")
            if not page:
                continue
            email = self._best_email(page, domain)
            phone = self._first_phone(page)
            if email or phone:
                return email, phone
        return None, None

    # --- decision-maker enrichment -------------------------------------------
    def _enrich(self, domain: str, homepage: str, company: str) -> Tuple[Optional[str], Optional[str]]:
        """Find a (name, role) decision-maker from the homepage, then about/team pages."""
        name, role = self._extract_person(homepage, company)
        if name and role:
            return name, role
        for i, path in enumerate(_ENRICH_PATHS):
            if i >= self.enrich_fetches:
                break
            page = self._get(f"https://{domain}/{path}")
            if not page:
                continue
            name, role = self._extract_person(page, company)
            if name and role:
                return name, role
        return None, None

    def _extract_person(self, page: str, company: str = "") -> Tuple[Optional[str], Optional[str]]:
        text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page or "")))
        root = (company.split() or [""])[0].lower()
        for m in _ROLE_RE.finditer(text):
            role = _ROLE_CANON.get(m.group(1).lower(), m.group(1))
            before = _NAME_BEFORE_RE.search(text[max(0, m.start() - 50): m.start()])
            after = _NAME_AFTER_RE.search(text[m.end(): m.end() + 50])
            if not before and after:
                # Sin nombre inmediatamente antes del rol pero sí después con un
                # separador ("Rol, Empresa") suele ser un testimonio de cliente
                # ("...excelente servicio." Nombre Rol, Otra Empresa Ltda.), no un
                # bio del propio equipo — cita a OTRA persona/empresa, no al dueño
                # del sitio. Una comilla de cierre justo antes es la señal barata
                # de que estamos dentro de una cita, no de una ficha de equipo.
                # Hallado en vivo (2026-07-13) contra 2 sitios reales de estudios
                # contables — sin este filtro se le atribuía a la empresa el
                # nombre de OTRA empresa citada en el testimonio.
                lookback = text[max(0, m.start() - 60): m.start()]
                if any(q in lookback for q in '"\'“”‘’'):
                    continue
            cand = (before or after)
            if not cand:
                continue
            name = self._clean_person(cand.group(1), root)
            if name:
                return name, role
        return None, None

    @staticmethod
    def _clean_person(raw: str, company_root: str) -> Optional[str]:
        parts = raw.split()
        # Drop a leading company word that glued itself to the name ("Onza Julio Sotelo").
        if len(parts) >= 3 and parts[0].lower() == company_root:
            parts = parts[1:]
        if not (2 <= len(parts) <= 3):
            return None
        if any(w.lower() in _NOT_NAME for w in parts):
            return None
        return " ".join(parts)

    # --- search --------------------------------------------------------------
    def _search(self, query: str, n: int) -> List[Tuple[str, str]]:
        body = urllib.parse.urlencode({"q": query}).encode()
        page = self._get(self.SEARCH_URL, data=body) or ""
        out: List[Tuple[str, str]] = []
        for m in _RESULT_RE.finditer(page):
            href, raw_title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
            real = self._resolve(href)
            if real:
                out.append((html.unescape(raw_title).strip(), real))
            if len(out) >= n:
                break
        return out

    @staticmethod
    def _resolve(href: str) -> Optional[str]:
        if href.startswith("//"):
            href = "https:" + href
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs:                       # DDG redirect wrapper
            return qs["uddg"][0]
        if "duckduckgo.com" in parsed.netloc:  # an ad (y.js) — not a result
            return None
        return href if parsed.scheme.startswith("http") else None

    # --- fetch + extract -----------------------------------------------------
    def _get(self, url: str, data: Optional[bytes] = None) -> Optional[str]:
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": _UA})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                charset = resp.headers.get_content_charset() or "utf-8"
                return resp.read(1_500_000).decode(charset, errors="replace")
        except Exception:
            return None

    def _best_email(self, page: str, domain: str) -> Optional[str]:
        # Strongest first: explicit mailto links, then plain text, then text with
        # common obfuscations undone ("ventas (arroba) pyme (punto) cl").
        found = self._clean_emails(_MAILTO_RE.findall(page))
        if not found:
            found = self._clean_emails(_EMAIL_RE.findall(page))
        if not found:
            text = re.sub(r"<[^>]+>", " ", page)
            found = self._clean_emails(_EMAIL_RE.findall(self._deobfuscate(text)))
        if not found:
            return None
        # Prefer an address on the site's own domain.
        on_domain = [e for e in found if e.lower().endswith("@" + domain) or domain in e.lower()]
        return (on_domain or found)[0]

    @staticmethod
    def _clean_emails(found: List[str]) -> List[str]:
        return [e for e in found if not any(h in e.lower() for h in _BAD_EMAIL_HINTS)]

    @staticmethod
    def _deobfuscate(text: str) -> str:
        """Rewrite common email obfuscations into plain form. The bracketed `at`
        form is required (a bare English "at" would invent addresses); the
        Spanish words are unambiguous enough on their own."""
        t = re.sub(r"\s*[\[\(\{]\s*(?:at|arroba)\s*[\]\)\}]\s*|\s+arroba\s+", "@", text, flags=re.I)
        return re.sub(r"\s*[\[\(\{]\s*(?:dot|punto)\s*[\]\)\}]\s*|\s+punto\s+", ".", t, flags=re.I)

    def _first_phone(self, page: str) -> Optional[str]:
        # 1) Most reliable: an explicit tel: link.
        for m in _TEL_HREF_RE.findall(page):
            if self._valid_phone(m, min_digits=8):
                return m.strip()
        # 2) Strict patterns in visible text (Chilean mobile, then +CC intl).
        text = re.sub(r"<[^>]+>", " ", page)
        for rx in (_PHONE_TEXT_RE, _INTL_PHONE_RE):
            for m in rx.findall(text):
                if self._valid_phone(m, min_digits=9):
                    return m.strip()
        return None

    @staticmethod
    def _valid_phone(raw: str, min_digits: int) -> bool:
        if raw.strip().startswith("+0"):     # no country code starts with 0 → placeholder/garbage
            return False
        digits = re.sub(r"\D", "", raw)
        if len(set(digits)) <= 1:            # 999999999 → placeholder, not a phone
            return False
        return min_digits <= len(digits) <= 12

    @staticmethod
    def _activity(page: str, title: str) -> Optional[str]:
        """Extract business activity from meta description or page title.
        Returns None if no evidence or generic placeholder found."""
        # Try meta description first (most reliable).
        m = _META_DESC_RE.search(page)
        desc = m.group(1) if m else None
        if desc and not _is_generic_description(desc):
            return _clean_activity(desc)
        # Fallback to page title if no meta description.
        if title and not _is_generic_description(title):
            return _clean_activity(title)
        return None

    @staticmethod
    def _detect_industry(page: str, activity: str, title: str, domain: str) -> Optional[str]:
        """Detect industry/rubro from page content, activity, title, and domain.
        Returns the matched industry name or None."""
        text = (activity + " " + title + " " + domain).lower()
        for industry, keywords in _INDUSTRY_KEYWORDS.items():
            for keyword in keywords:
                if keyword.lower() in text:
                    return industry
        return None

    def _company_name(self, page: str, title: str, domain: str) -> str:
        m = _SITE_NAME_RE.search(page)
        raw = m.group(1) if m else title
        return self._clean_name(raw, domain)

    @staticmethod
    def _clean_name(raw: Optional[str], domain: str) -> str:
        if not raw:
            return domain
        # Names/titles are often "Company — tagline | Section"; keep the first chunk.
        first = re.split(r"\s*[\|\-–—:·]\s*", html.unescape(raw).strip())[0].strip()
        if len(first) < 3:   # "D - Marketing Chile" → the dash was part of the name
            first = html.unescape(raw).strip()
        return (first[:60] or domain)

    # --- helpers -------------------------------------------------------------
    @staticmethod
    def _domain(url: str) -> str:
        net = urllib.parse.urlparse(url).netloc.lower()
        return net[4:] if net.startswith("www.") else net

    @staticmethod
    def _pick_channel(channels: List[str], email: Optional[str], phone: Optional[str]) -> str:
        allowed = channels or ["email"]
        if email and "email" in allowed:
            return "email"
        if phone:
            for c in ("whatsapp", "cold_call"):
                if c in allowed:
                    return c
        return allowed[0]
