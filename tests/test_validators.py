"""Tests de zero/validators.py — ramas no cubiertas por test_core.

test_core ya prueba validate_email/phone/batch básicos. Aquí se cubren las
ramas que faltan y que sostienen la promesa de "leads confiables":
  - validate_contact (identidad name→company, canal ausente, doble require)
  - reglas ENTERPRISE (must_have_tld / valid_tlds, min_digits 9, name min_len 3)
  - validate_name y el fallback de tier desconocido a GROWTH.
"""
import unittest

from zero.validators import ValidatorRules as V
from zero.config import validator_tier, DEFAULT_VALIDATOR_TIER

GROWTH = validator_tier("GROWTH")
ENT = validator_tier("ENTERPRISE")


def _lead(**kw):
    base = {"name": "Ana", "company": "Acme", "email": "ana@acme.cl", "phone": "+56 9 1234 5678"}
    base.update(kw)
    return base


class TestTierResolution(unittest.TestCase):
    def test_tier_desconocido_cae_a_growth(self):
        self.assertEqual(validator_tier("STARTER"), validator_tier(DEFAULT_VALIDATOR_TIER))

    def test_enterprise_es_distinto(self):
        self.assertNotEqual(ENT["phone"]["min_digits"], GROWTH["phone"]["min_digits"])


class TestValidateName(unittest.TestCase):
    def test_vacio_con_require_falla(self):
        self.assertFalse(V.validate_name("", GROWTH["name"]))
        self.assertFalse(V.validate_name(None, GROWTH["name"]))

    def test_vacio_sin_require_pasa(self):
        self.assertTrue(V.validate_name("", {"require": False, "min_len": 1}))

    def test_enterprise_exige_min_len_3(self):
        self.assertFalse(V.validate_name("Al", ENT["name"]))
        self.assertTrue(V.validate_name("Ana", ENT["name"]))


class TestValidateEmailTier(unittest.TestCase):
    def test_growth_no_exige_tld(self):
        self.assertTrue(V.validate_email("ceo@startup.io", GROWTH["email"]))

    def test_enterprise_exige_tld_valido(self):
        self.assertFalse(V.validate_email("ceo@startup.io", ENT["email"]))  # .io no está
        self.assertTrue(V.validate_email("ceo@startup.cl", ENT["email"]))

    def test_enterprise_min_len(self):
        # min_len 6: "a@b.cl" == 6 ok, más corto falla el patrón/longitud
        self.assertFalse(V.validate_email("a@b.c", ENT["email"]))

    def test_email_vacio_con_require_falla(self):
        self.assertFalse(V.validate_email("", GROWTH["email"]))


class TestValidatePhoneTier(unittest.TestCase):
    def test_enterprise_exige_9_digitos(self):
        self.assertFalse(V.validate_phone("1234567", ENT["phone"]))   # 7 dígitos
        self.assertTrue(V.validate_phone("+56 9 1234 5678", ENT["phone"]))

    def test_vacio_sin_require_pasa(self):
        self.assertTrue(V.validate_phone("", GROWTH["phone"]))  # GROWTH phone no require


class TestValidateContact(unittest.TestCase):
    def test_lead_completo_growth_pasa(self):
        self.assertTrue(V.validate_contact(_lead(), "GROWTH"))

    def test_identidad_cae_a_company(self):
        # sin name, usa company como identidad
        self.assertTrue(V.validate_contact(_lead(name=None), "GROWTH"))

    def test_sin_name_ni_company_falla(self):
        self.assertFalse(V.validate_contact(_lead(name=None, company=None), "GROWTH"))

    def test_sin_ningun_canal_falla(self):
        self.assertFalse(V.validate_contact(_lead(email=None, phone=None), "GROWTH"))

    def test_email_corrupto_falla(self):
        self.assertFalse(V.validate_contact(_lead(email="usuario@", phone=None), "GROWTH"))

    def test_growth_pasa_solo_con_email(self):
        self.assertTrue(V.validate_contact(_lead(phone=None), "GROWTH"))

    def test_enterprise_exige_ambos_canales(self):
        # ENTERPRISE marca email y phone como require → faltar uno invalida
        self.assertFalse(V.validate_contact(_lead(phone=None), "ENTERPRISE"))
        self.assertFalse(V.validate_contact(_lead(email=None), "ENTERPRISE"))

    def test_enterprise_completo_valido_pasa(self):
        self.assertTrue(V.validate_contact(
            _lead(name="Ana", email="ana@acme.cl", phone="+56 9 1234 5678"), "ENTERPRISE"))

    def test_enterprise_tld_invalido_falla(self):
        self.assertFalse(V.validate_contact(
            _lead(email="ana@acme.io", phone="+56 9 1234 5678"), "ENTERPRISE"))


class TestValidateBatch(unittest.TestCase):
    def test_preserva_forma_y_filtra(self):
        leads = [_lead(), _lead(email="usuario@", phone=None)]
        out = V.validate_batch(leads, "GROWTH")
        self.assertEqual(len(out), 1)
        self.assertIs(out[0], leads[0])  # no altera la forma del lead


if __name__ == "__main__":
    unittest.main()
