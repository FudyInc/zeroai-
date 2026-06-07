"""Discovery sources — where PROSPECTOR finds *real* candidate companies.

Like the LLM backends, the source is a swappable object behind one method,
`search_leads(query, max_items, channels)`. Today: `DuckDuckGoSource`, a no-key
web search (HTML endpoint) + page fetch + contact extraction, stdlib only.
Tomorrow a keyed provider (Brave/SerpAPI) drops in with the same signature and
PROSPECTOR doesn't change.

Web extraction is best-effort: many sites expose no email, so candidates often
arrive without a verified contact — exactly the kind of lead ZERO's qualified
gate is meant to filter.
"""
from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# `tel:` links are the most reliable phone signal; the text patterns are strict
# on purpose (a bare "1.42857143" from JS must not look like a phone).
_TEL_HREF_RE = re.compile(r'tel:\s*([+()\d][\d\s().\-]{6,}\d)', re.I)
_PHONE_TEXT_RE = re.compile(r"(?:\+?56[\s.\-]?)?9[\s.\-]?\d{4}[\s.\-]?\d{4}")  # Chilean mobile
_INTL_PHONE_RE = re.compile(r"\+\d{1,3}[\s.\-]?(?:\(?\d{1,4}\)?[\s.\-]?){2,4}\d")  # +CC ...
_RESULT_RE = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_SITE_NAME_RE = re.compile(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)

_BAD_EMAIL_HINTS = ("example.", "sentry", "wixpress", "@2x", "@3x", ".png", ".jpg", ".gif", ".webp")

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
}
_ENRICH_PATHS = ("nosotros", "equipo", "quienes-somos", "sobre-nosotros", "about", "team")

# Search engines, social, and aggregators aren't the company sites we want as leads.
_SKIP_DOMAINS = (
    "duckduckgo.com", "google.", "bing.com", "yahoo.com",
    "facebook.com", "instagram.com", "linkedin.com", "twitter.com", "x.com",
    "youtube.com", "tiktok.com", "wikipedia.org", "yelp.com", "pinterest.com",
    "amazon.", "mercadolibre.", "wordpress.com", "blogspot.com",
)


class DiscoverySource:
    """Interface: turn a query into normalized lead candidates."""

    def search_leads(self, query: str, max_items: int, channels: List[str]) -> List[Dict[str, Any]]:
        raise NotImplementedError


class DuckDuckGoSource(DiscoverySource):
    """No-key web discovery via DuckDuckGo's HTML endpoint."""

    SEARCH_URL = "https://html.duckduckgo.com/html/"

    def __init__(self, timeout: float = 8.0, max_fetch: Optional[int] = None,
                 enrich: bool = True, enrich_fetches: int = 3):
        self.timeout = timeout
        self.max_fetch = max_fetch
        self.enrich = enrich              # look up the decision-maker (name + role)
        self.enrich_fetches = enrich_fetches  # max extra about/team page fetches per company

    def search_leads(self, query: str, max_items: int, channels: List[str]) -> List[Dict[str, Any]]:
        budget = self.max_fetch or max_items
        results = self._search(query, n=max_items * 3)

        leads: List[Dict[str, Any]] = []
        seen: set = set()
        fetched = 0
        for title, url in results:
            if len(leads) >= max_items or fetched >= max(budget, max_items):
                break
            domain = self._domain(url)
            if not domain or domain in seen or any(b in domain for b in _SKIP_DOMAINS):
                continue
            seen.add(domain)
            fetched += 1

            page = self._get(url) or ""
            email = self._best_email(page, domain)
            phone = self._first_phone(page)
            company = self._company_name(page, title, domain)
            name, role = (None, None)
            if self.enrich:
                try:
                    name, role = self._enrich(domain, page, company)
                except Exception:
                    name, role = (None, None)
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
            })
        return leads

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
        found = [e for e in _EMAIL_RE.findall(page)
                 if not any(h in e.lower() for h in _BAD_EMAIL_HINTS)]
        if not found:
            return None
        # Prefer an address on the site's own domain.
        on_domain = [e for e in found if e.lower().endswith("@" + domain) or domain in e.lower()]
        return (on_domain or found)[0]

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
        return min_digits <= len(re.sub(r"\D", "", raw)) <= 12

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
