"""Edge-case tests for the JSON contract's defensive parsing.

`AgentResponse.from_dict` is the boundary where a real (messy) model reply gets
normalized into the contract. The mock path always speaks clean JSON, so these
drift cases only surface in `--live`/`--local` — exactly where a crash is most
expensive. This file pins the documented defensive behavior so a refactor can't
quietly break it.

Run: python3 -m unittest tests.test_contracts -v
"""
from __future__ import annotations

import unittest

from zero.contracts import AgentResponse, Lead, _as_int


class AgentResponseParsingTest(unittest.TestCase):
    """from_dict must survive every shape a live model realistically emits."""

    def test_bare_list_result_is_wrapped_as_leads(self):
        # Model returns {"result": [...]} instead of {"result": {"leads": [...]}}.
        resp = AgentResponse.from_dict({"result": [{"company": "A"}]})
        self.assertEqual(resp.result, {"leads": [{"company": "A"}]})
        self.assertTrue(resp.ok)

    def test_non_dict_input_becomes_error(self):
        resp = AgentResponse.from_dict("not an object")
        self.assertEqual(resp.status, "error")
        self.assertEqual(resp.result, {})
        self.assertEqual(resp.notes, "respuesta no es un objeto")

    def test_non_dict_input_keeps_fallback_ids(self):
        resp = AgentResponse.from_dict(None, task_id="t9", agent="QUALIFIER")
        self.assertEqual(resp.task_id, "t9")
        self.assertEqual(resp.agent, "QUALIFIER")

    def test_missing_envelope_lifts_known_keys_from_body(self):
        # No "result" key, but the payload carries known fields directly — this
        # IS exactly CONCIERGE's real schema (prompts/concierge.md): a flat
        # {"reply", "intent"}, no "result" wrapper. Found live (2026-07-13)
        # that "intent" used to get silently dropped here (missing from
        # _RESULT_KEYS), breaking the pending-offer flow with the real model
        # even though every test passed (the mock path never goes through
        # from_dict, so this blind spot only showed up live).
        resp = AgentResponse.from_dict({"reply": "hola", "intent": "pricing"})
        self.assertEqual(resp.result, {"reply": "hola", "intent": "pricing"})
        self.assertTrue(resp.ok)

    def test_lifts_multiple_known_keys(self):
        resp = AgentResponse.from_dict({"subject": "Hola", "body": "texto"})
        self.assertEqual(resp.result, {"subject": "Hola", "body": "texto"})

    def test_garbage_result_type_falls_back_to_empty(self):
        # result is neither dict nor list and nothing liftable in the body.
        resp = AgentResponse.from_dict({"result": "oops"})
        self.assertEqual(resp.result, {})
        self.assertEqual(resp.status, "error")  # inferred: no result

    def test_invalid_status_with_result_infers_done(self):
        resp = AgentResponse.from_dict({"status": "weird", "result": {"leads": [1]}})
        self.assertEqual(resp.status, "done")

    def test_missing_status_no_result_infers_error(self):
        resp = AgentResponse.from_dict({})
        self.assertEqual(resp.status, "error")
        self.assertFalse(resp.ok)

    def test_explicit_valid_status_is_preserved(self):
        # A model may legitimately report partial/error; we must not overwrite it.
        resp = AgentResponse.from_dict({"status": "partial", "result": {"leads": [1]}})
        self.assertEqual(resp.status, "partial")
        self.assertFalse(resp.ok)

    def test_explicit_done_with_empty_result_is_trusted(self):
        # Valid status is never re-inferred, even when the result is empty.
        resp = AgentResponse.from_dict({"status": "done"})
        self.assertEqual(resp.status, "done")

    def test_non_empty_dict_result_is_used_as_is(self):
        # A real envelope must not trigger the lift fallback.
        resp = AgentResponse.from_dict({"result": {"rates": {"open": 0.4}}, "messages": ["x"]})
        self.assertEqual(resp.result, {"rates": {"open": 0.4}})
        self.assertNotIn("messages", resp.result)

    def test_ids_prefer_body_over_fallback(self):
        resp = AgentResponse.from_dict(
            {"task_id": "real", "agent": "OUTREACH", "result": {"x": 1}},
            task_id="fallback", agent="WRONG",
        )
        self.assertEqual(resp.task_id, "real")
        self.assertEqual(resp.agent, "OUTREACH")


class LeadKeyTest(unittest.TestCase):
    """key() is the de-dup / recontact identity — must be stable and lowercased."""

    def test_email_wins_and_is_lowercased(self):
        lead = Lead.from_dict({"company": "A", "role": "CEO", "email": "X@Y.com"})
        self.assertEqual(lead.key(), "x@y.com")

    def test_phone_used_when_no_email(self):
        lead = Lead.from_dict({"company": "A", "role": "CEO", "phone": "+569"})
        self.assertEqual(lead.key(), "+569")

    def test_company_role_fallback_when_no_contact(self):
        lead = Lead.from_dict({"company": "Acme", "role": "CEO"})
        self.assertEqual(lead.key(), "acme|ceo")

    def test_same_email_different_casing_collides(self):
        a = Lead.from_dict({"company": "A", "role": "CEO", "email": "Ana@x.com"})
        b = Lead.from_dict({"company": "B", "role": "CTO", "email": "ana@X.com"})
        self.assertEqual(a.key(), b.key())


class AsIntCoercionTest(unittest.TestCase):
    """_as_int keeps the gate's numeric comparison crash-proof on messy scores."""

    def test_stringified_and_float_scores(self):
        self.assertEqual(_as_int("85"), 85)
        self.assertEqual(_as_int(85.0), 85)
        self.assertEqual(_as_int("85.9"), 85)

    def test_unparseable_is_none(self):
        self.assertIsNone(_as_int("alto"))
        self.assertIsNone(_as_int(None))
        self.assertIsNone(_as_int([5]))


class LeadYCrmHablanDelMismoLeadTest(unittest.TestCase):
    """El contrato (`contracts.Lead`) y lo que el CRM persiste (`crm._FIELDS`) no
    pueden divergir: un campo que el CRM guarda pero el contrato no conoce se
    pierde en silencio la primera vez que ese lead pasa por el pipeline
    (orchestrator hace Lead.from_dict sobre cada uno).

    Pasó con `segment`: lo escribía el formulario público, el CRM lo guardaba, y
    Lead.from_dict lo dejaba en None. No se notaba porque el endpoint escribe el
    dict directo al CRM — se habría notado el día que un lead de la landing
    recorriera el pipeline, que es exactamente para lo que se captura.
    """

    def test_el_crm_no_persiste_campos_que_el_contrato_ignora(self):
        import dataclasses

        from zero.crm import _FIELDS
        del_contrato = {f.name for f in dataclasses.fields(Lead)}
        self.assertEqual(sorted(set(_FIELDS) - del_contrato), [])

    def test_el_contrato_no_declara_campos_que_el_crm_descarta(self):
        """El espejo del test de arriba, y la mitad que faltaba.

        Pasó con `industry`: discovery lo detectaba, contracts.Lead lo transportaba,
        y `upsert()` lo descartaba en silencio porque no estaba en `_FIELDS` — el
        lead llegaba al CRM sin el rubro, que es justo para lo que se capturaba. La
        suite seguía verde porque solo se comprobaba la dirección contraria.
        """
        import dataclasses

        from zero.crm import _FIELDS
        del_contrato = {f.name for f in dataclasses.fields(Lead)}
        self.assertEqual(sorted(del_contrato - set(_FIELDS)), [])

    def test_segment_sobrevive_el_viaje_por_el_contrato(self):
        lead = Lead.from_dict({"company": "X", "email": "a@b.cl", "segment": "pyme"})
        self.assertEqual(lead.to_dict()["segment"], "pyme")

    def test_los_campos_del_formulario_publico_sobreviven(self):
        """activity/source/segment son los tres que trae la landing."""
        d = {"company": "X", "email": "a@b.cl", "activity": "pinturas",
             "source": "waitlist", "segment": "pyme"}
        vuelta = Lead.from_dict(d).to_dict()
        for campo, valor in d.items():
            self.assertEqual(vuelta[campo], valor, campo)


if __name__ == "__main__":
    unittest.main()
