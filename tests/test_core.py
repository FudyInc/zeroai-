"""Core safety net — the invariants ZERO must never break.

Stdlib unittest, no deps, all in mock. Run from the project root:

    python3 -m unittest discover -s tests -t .

These tests lock in the *logic* (gate, discovery delivery, scoring, CRM stages,
the whole pipeline). They don't judge lead quality — that's the real model's job.
"""
from __future__ import annotations

import unittest

from zero.agents import build_agents
from zero.config import MIN_ICP_SCORE, RECONTACT_BLACKOUT_DAYS
from zero.contracts import Constraints, Lead, TaskPayload
from zero.crm import CRM
from zero.memory import SessionMemory, _now
from zero.orchestrator import Zero


def _lead(**kw):
    base = dict(company="Acme", role="CEO", channel="email",
                email="ceo@acme.cl", domain="acme.cl", score=MIN_ICP_SCORE + 10)
    base.update(kw)
    return Lead(**base)


class GateTest(unittest.TestCase):
    """The qualified-lead gate — the heart of 'confiable'."""

    def setUp(self):
        self.z = Zero(build_agents(mock=True), memory=SessionMemory(None))

    def test_good_lead_passes(self):
        ok, fails = self.z.validate_lead(_lead(), exclusions=[])
        self.assertTrue(ok, fails)

    def test_no_contact_fails(self):
        ok, fails = self.z.validate_lead(_lead(email=None, phone=None), exclusions=[])
        self.assertFalse(ok)
        self.assertTrue(any("contacto" in f for f in fails))

    def test_low_score_fails(self):
        ok, fails = self.z.validate_lead(_lead(score=MIN_ICP_SCORE - 1), exclusions=[])
        self.assertFalse(ok)

    def test_score_at_threshold_passes(self):
        ok, _ = self.z.validate_lead(_lead(score=MIN_ICP_SCORE), exclusions=[])
        self.assertTrue(ok)

    def test_exclusion_fails(self):
        ok, fails = self.z.validate_lead(_lead(domain="acme.cl"), exclusions=["acme.cl"])
        self.assertFalse(ok)
        self.assertTrue(any("exclusión" in f for f in fails))

    def test_recent_contact_fails(self):
        lead = _lead()
        self.z.memory.contacted[lead.key()] = _now()   # contacted just now
        ok, fails = self.z.validate_lead(lead, exclusions=[])
        self.assertFalse(ok)
        self.assertTrue(any(str(RECONTACT_BLACKOUT_DAYS) in f for f in fails))


class ProspectorTest(unittest.TestCase):
    """Discovery must deliver the requested count and never repeat a company."""

    def _run(self, cap):
        p = build_agents(mock=True)["PROSPECTOR"]
        task = TaskPayload(agent="PROSPECTOR", client_id="demo", client_tier="SCALE",
                           instructions="x", data={"query": "retail Chile"},
                           constraints=Constraints(max_items=cap, channels=["email", "whatsapp"]))
        return p.run(task)

    def test_delivers_requested_count(self):
        self.assertEqual(len(self._run(8).result["leads"]), 8)

    def test_no_duplicate_companies(self):
        companies = [l["company"] for l in self._run(8).result["leads"]]
        self.assertEqual(len(companies), len(set(companies)))

    def test_partial_when_pool_exhausted(self):
        resp = self._run(500)                  # far beyond the fixture pool
        self.assertEqual(resp.status, "partial")
        self.assertLess(len(resp.result["leads"]), 500)   # bounded, didn't hang


class QualifierTest(unittest.TestCase):
    def _score(self, leads):
        q = build_agents(mock=True)["QUALIFIER"]
        task = TaskPayload(agent="QUALIFIER", client_id="demo", client_tier="SCALE",
                           instructions="x", data={"leads": leads, "scoring": "advanced"},
                           constraints=Constraints())
        return q.run(task).result["leads"]

    def test_scores_in_range_and_deterministic(self):
        leads = [{"company": "Acme", "role": "CEO"}]
        a = self._score(leads)[0]["score"]
        b = self._score(leads)[0]["score"]
        self.assertEqual(a, b)                 # same input → same score
        self.assertTrue(0 <= a <= 100)

    def test_sorted_desc_with_reasons(self):
        leads = [{"company": f"C{i}", "role": "CEO"} for i in range(6)]
        scored = self._score(leads)
        self.assertEqual([l["score"] for l in scored],
                         sorted((l["score"] for l in scored), reverse=True))
        self.assertTrue(all(l["icp_reasons"] for l in scored))


class OutreachTest(unittest.TestCase):
    """First-touch copy must scale with the client's tier."""

    def _msg(self, tier):
        o = build_agents(mock=True)["OUTREACH"]
        task = TaskPayload(agent="OUTREACH", client_id="c", client_tier=tier,
                           instructions="x",
                           data={"leads": [{"company": "Acme", "role": "CEO",
                                            "name": "Ana", "channel": "email"}]},
                           constraints=Constraints(channels=["email"]))
        return o.run(task).result["messages"][0]["body"]

    def test_enterprise_more_personalized_than_starter(self):
        starter, enterprise = self._msg("STARTER"), self._msg("ENTERPRISE")
        self.assertNotEqual(starter, enterprise)
        self.assertGreater(len(enterprise), len(starter))   # richer copy
        self.assertIn("piloto", enterprise)                 # tier-specific touch


class CRMTest(unittest.TestCase):
    def setUp(self):
        self.crm = CRM(None)
        self.lead = {"company": "Acme", "role": "CEO", "email": "ceo@acme.cl", "score": 80}
        self.key = "ceo@acme.cl"

    def test_upsert_creates_and_dedupes(self):
        self.crm.upsert("c", self.lead, stage="qualified")
        self.crm.upsert("c", self.lead, stage="qualified")   # same lead again
        self.assertEqual(len(self.crm.list("c")), 1)

    def test_history_tracks_stage_changes(self):
        self.crm.upsert("c", self.lead, stage="qualified")
        self.crm.set_stage("c", self.key, "contacted")
        rec = self.crm.get("c", self.key)
        self.assertEqual(rec["stage"], "contacted")
        self.assertTrue(any(h["event"] == "stage" for h in rec["history"]))

    def test_advance_is_forward_only(self):
        self.crm.upsert("c", self.lead, stage="qualified")
        self.crm.set_stage("c", self.key, "won")        # manual, jumps ahead
        self.crm.advance("c", self.key, "qualified")    # auto re-run must NOT regress
        self.assertEqual(self.crm.get("c", self.key)["stage"], "won")

    def test_manual_set_stage_can_move_anywhere(self):
        self.crm.upsert("c", self.lead, stage="won")
        self.crm.set_stage("c", self.key, "lost")
        self.assertEqual(self.crm.get("c", self.key)["stage"], "lost")

    def test_invalid_stage_raises(self):
        self.crm.upsert("c", self.lead)
        with self.assertRaises(ValueError):
            self.crm.set_stage("c", self.key, "banana")

    def test_lead_detail_renders_timeline(self):
        from zero.board import render_lead
        self.crm.upsert("c", self.lead, stage="qualified")
        self.crm.set_stage("c", self.key, "won", detail="manual")
        out = render_lead(self.crm, "c", self.key, color=False)
        self.assertIn("Acme", out)
        self.assertIn("Historial", out)
        self.assertIn("won", out)


class RobustnessTest(unittest.TestCase):
    """A live model may deviate from the mock's clean contract — don't crash."""

    def test_string_score_is_coerced(self):
        self.assertEqual(Lead.from_dict({"company": "X", "score": "85"}).score, 85)
        self.assertEqual(Lead.from_dict({"company": "X", "score": 85.0}).score, 85)

    def test_garbage_score_becomes_none(self):
        self.assertIsNone(Lead.from_dict({"company": "X", "score": "alto"}).score)

    def test_gate_survives_stringy_score(self):
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        lead = Lead.from_dict({"company": "X", "role": "CEO", "channel": "email",
                               "email": "x@x.cl", "score": "92"})
        ok, _ = z.validate_lead(lead, exclusions=[])   # would TypeError if score stayed a str
        self.assertTrue(ok)

    def test_corrupt_crm_file_raises_clear_error(self):
        import os
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "crm.json")
        with open(path, "w") as fh:
            fh.write("{ this is not valid json")
        with self.assertRaises(RuntimeError) as ctx:
            CRM(path)
        self.assertIn("corrupto", str(ctx.exception))


class PipelineIntegrationTest(unittest.TestCase):
    """The whole chain in mock: discover → qualify → validate → outreach → CRM."""

    def test_pipeline_and_crm(self):
        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)
        d = z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)

        self.assertEqual(d["summary"]["discovered"], 8)
        # qualified is a subset, and every qualified lead clears the score bar
        self.assertLessEqual(d["summary"]["qualified"], 8)
        self.assertTrue(all(l["score"] >= MIN_ICP_SCORE for l in d["qualified_leads"]))
        # every discovered lead is recorded in the CRM (qualified or disqualified)
        self.assertEqual(sum(crm.counts("acme").values()), 8)


class ExportTest(unittest.TestCase):
    """The deliverable CSV — what a client actually receives."""

    def test_csv_has_header_and_one_row_per_lead(self):
        import csv
        import os
        import tempfile
        from zero.export import deliverable_to_csv

        deliverable = {
            "qualified_leads": [
                {"company": "Acme", "name": "Ana", "role": "CEO", "email": "ana@acme.cl",
                 "phone": None, "channel": "email", "score": 88, "icp_reasons": ["fit alto"]},
            ],
            "outreach": [{"company": "Acme", "channel": "email",
                          "subject": "Hola", "body": "Mensaje de prueba"}],
        }
        path = os.path.join(tempfile.mkdtemp(), "deliverable.csv")
        n = deliverable_to_csv(deliverable, path)
        self.assertEqual(n, 1)

        with open(path, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0][0], "empresa")          # header present
        self.assertEqual(len(rows), 2)                   # header + 1 lead
        self.assertIn("Acme", rows[1])
        self.assertIn("Mensaje de prueba", rows[1])      # outreach joined by company

    def test_crm_book_export(self):
        import csv
        import os
        import tempfile
        from zero.export import crm_to_csv

        crm = CRM(None)
        crm.upsert("c", {"company": "Acme", "role": "CEO", "email": "a@acme.cl", "score": 90},
                   stage="qualified")
        crm.upsert("c", {"company": "Beta", "role": "CTO", "email": "b@beta.cl", "score": 80},
                   stage="contacted")
        path = os.path.join(tempfile.mkdtemp(), "book.csv")
        n = crm_to_csv(crm, "c", path)
        self.assertEqual(n, 2)
        with open(path, encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
        self.assertEqual(rows[0][-1], "actualizado")
        self.assertEqual(len(rows), 3)                   # header + 2 leads
        self.assertIn("etapa", rows[0])


class LifecycleTest(unittest.TestCase):
    """The whole operator journey, end to end, must hold together."""

    def test_run_then_close_then_forecast_then_export(self):
        import os
        import tempfile
        from zero.export import crm_to_csv

        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)

        # 1) run the pipeline → leads land in the CRM, some nurturing
        z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
        nurturing = crm.list("acme", "nurturing")
        self.assertTrue(nurturing)

        # 2) operator closes one deal
        key = nurturing[0]["key"]
        crm.set_stage("acme", key, "won", detail="cerró")
        self.assertEqual(crm.get("acme", key)["stage"], "won")

        # 3) forecast runs over the logged activity
        fc = z.forecast("acme")
        self.assertIn("projection", fc["forecast"])

        # 4) the book exports
        path = os.path.join(tempfile.mkdtemp(), "book.csv")
        self.assertGreaterEqual(crm_to_csv(crm, "acme", path), 1)


if __name__ == "__main__":
    unittest.main()
