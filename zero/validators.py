"""Contact validators — reject corrupt leads before they reach the CRM.

A discovered "lead" is only as good as its contact info: an email without an
`@`, a placeholder like `usuario@ejemplo.com`, a 4-digit "phone", or an empty
name all slip past discovery's best-effort extraction and turn into noise that
degrades the "leads confiables" promise (see CLAUDE.md).

Design:
  - Tier-aware: GROWTH (liberal) vs ENTERPRISE (strict) — thresholds live in
    `zero.config.VALIDATOR_TIERS`, this module only applies them.
  - stdlib-only, deterministic: same input -> same output, easy to call
    directly from tests (`ValidatorRules.validate_email("x@y.cl")`).
  - Reuses the email/phone primitives already proven in `zero.discovery`
    (`_EMAIL_RE`, `_BAD_EMAIL_HINTS`, `DuckDuckGoSource._valid_phone`) instead
    of growing a second set of regexes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import DEFAULT_VALIDATOR_TIER, validator_tier


class ValidatorRules:
    """Stateless rule checks. Each `validate_*` field method takes the value
    plus an optional tier-specific `rules` dict (defaults to GROWTH's rules
    for that field, so the methods are directly callable in tests/mocks)."""

    @staticmethod
    def validate_email(email: Optional[str], rules: Optional[Dict[str, Any]] = None) -> bool:
        from .discovery import _BAD_EMAIL_HINTS, _EMAIL_RE  # local import: avoid cycle with discovery.py

        rules = rules or validator_tier(DEFAULT_VALIDATOR_TIER)["email"]
        if not email or not email.strip():
            return not rules.get("require", True)
        e = email.strip()
        if len(e) < rules.get("min_len", 0):
            return False
        if not _EMAIL_RE.fullmatch(e):
            return False
        if any(h in e.lower() for h in _BAD_EMAIL_HINTS):  # "usuario@", "ejemplo@test", ...
            return False
        if rules.get("must_have_tld"):
            valid_tlds = rules.get("valid_tlds") or []
            if not any(e.lower().endswith(tld.lower()) for tld in valid_tlds):
                return False
        return True

    @staticmethod
    def validate_phone(phone: Optional[str], rules: Optional[Dict[str, Any]] = None) -> bool:
        from .discovery import DuckDuckGoSource  # local import: avoid cycle with discovery.py

        rules = rules or validator_tier(DEFAULT_VALIDATOR_TIER)["phone"]
        if not phone or not phone.strip():
            return not rules.get("require", False)
        return DuckDuckGoSource._valid_phone(phone, min_digits=rules.get("min_digits", 7))

    @staticmethod
    def validate_name(name: Optional[str], rules: Optional[Dict[str, Any]] = None) -> bool:
        rules = rules or validator_tier(DEFAULT_VALIDATOR_TIER)["name"]
        if not name or not name.strip():
            return not rules.get("require", True)
        return len(name.strip()) >= rules.get("min_len", 1)

    @staticmethod
    def validate_contact(lead: Dict[str, Any], tier: str = DEFAULT_VALIDATOR_TIER) -> bool:
        """A lead is valid when its name passes and its contact info isn't
        corrupt. `name` falls back to `company` — discovery often can't
        enrich a decision-maker's name, but the company name always exists
        and is the contact's primary identity in that case.

        `require` on a field means "if present, must be well-formed"; a lead
        with *no* contact info at all is always invalid, and if *both*
        channels are marked `require` (ENTERPRISE), both must be present."""
        rules = validator_tier(tier)
        identity = lead.get("name") or lead.get("company")
        if not ValidatorRules.validate_name(identity, rules["name"]):
            return False

        email, phone = lead.get("email"), lead.get("phone")
        if not email and not phone:
            return False  # no contact channel at all -> useless lead

        email_rules, phone_rules = rules["email"], rules["phone"]
        if email and not ValidatorRules.validate_email(email, email_rules):
            return False
        if phone and not ValidatorRules.validate_phone(phone, phone_rules):
            return False
        if email_rules.get("require") and phone_rules.get("require") and not (email and phone):
            return False  # tier demands both channels present (ENTERPRISE)
        return True

    @staticmethod
    def validate_batch(leads: List[Dict[str, Any]], tier: str = DEFAULT_VALIDATOR_TIER) -> List[Dict[str, Any]]:
        """Filter `leads` down to the ones that pass `validate_contact` for
        `tier`. Lead shape is never changed — invalid leads are just dropped."""
        return [lead for lead in leads if ValidatorRules.validate_contact(lead, tier)]
