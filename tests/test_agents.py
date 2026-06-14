"""Contract + determinism tests for sub-agents' mock paths.

Every agent must, in mock mode:
  - return a valid AgentResponse (`status` ∈ done|partial|error, `result` shaped
    per the agent's documented output);
  - be deterministic — the same TaskPayload always produces the same result, so
    the pipeline is reproducible offline (no hidden randomness / wall clock).

Run: python3 -m unittest tests.test_agents -v
"""
from __future__ import annotations

import unittest

from zero.agents import build_agents
from zero.contracts import AgentResponse, Constraints, TaskPayload


def _agents():
    return build_agents(mock=True)


class ProspectorContractTest(unittest.TestCase):
    """PROSPECTOR: discovers leads with the required minimum fields."""

    def _run(self, cap=5):
        p = _agents()["PROSPECTOR"]
        task = TaskPayload(agent="PROSPECTOR", client_id="demo", client_tier="GROWTH",
                           instructions="x", data={"query": "retail Chile"},
                           constraints=Constraints(max_items=cap, channels=["email"]))
        return p.run(task)

    def test_prospector_mock_returns_valid_schema(self):
        resp = self._run()
        self.assertIsInstance(resp, AgentResponse)
        self.assertTrue(resp.ok)
        leads = resp.result["leads"]
        self.assertEqual(len(leads), 5)
        for ld in leads:
            for k in ("company", "role", "channel"):
                self.assertIn(k, ld)
                self.assertTrue(ld[k])

    def test_prospector_deterministic(self):
        a = self._run().result["leads"]
        b = self._run().result["leads"]
        self.assertEqual(a, b)


class QualifierContractTest(unittest.TestCase):
    """QUALIFIER: scores 0-100 with reasons, deterministic per (client, company, role)."""

    def _run(self, leads):
        q = _agents()["QUALIFIER"]
        task = TaskPayload(agent="QUALIFIER", client_id="demo", client_tier="GROWTH",
                           instructions="x", data={"leads": leads, "scoring": "advanced"},
                           constraints=Constraints())
        return q.run(task)

    def test_qualifier_mock_valid(self):
        leads = [{"company": "Acme", "role": "CEO"}]
        resp = self._run(leads)
        self.assertTrue(resp.ok)
        scored = resp.result["leads"][0]
        self.assertIn("score", scored)
        self.assertIn("icp_reasons", scored)
        self.assertTrue(scored["icp_reasons"])
        self.assertTrue(0 <= scored["score"] <= 100)

    def test_qualifier_deterministic(self):
        leads = [{"company": "Acme", "role": "CEO"}, {"company": "Globex", "role": "CTO"}]
        a = self._run(leads).result["leads"]
        b = self._run(leads).result["leads"]
        self.assertEqual(a, b)

    def test_qualifier_empty_leads_does_not_crash(self):
        resp = self._run([])
        self.assertTrue(resp.ok)
        self.assertEqual(resp.result["leads"], [])


class ConciergeContractTest(unittest.TestCase):
    """CONCIERGE: drafts a non-empty reply + a recognized intent for every message."""

    def _run(self, msg):
        c = _agents()["CONCIERGE"]
        task = TaskPayload(agent="CONCIERGE", client_id="acme", client_tier="GROWTH",
                           instructions="x",
                           data={"message": msg, "lead": {"name": "Carla", "company": "Acme"},
                                 "icp": {"sells": "pallets"}},
                           constraints=Constraints(channels=["whatsapp"]))
        return c.run(task)

    def test_concierge_mock_valid(self):
        resp = self._run("¿cuánto cuesta?")
        self.assertTrue(resp.ok)
        self.assertIsInstance(resp.result["reply"], str)
        self.assertTrue(resp.result["reply"])
        self.assertEqual(resp.result["intent"], "pricing")

    def test_concierge_deterministic(self):
        a = self._run("mándame más información").result
        b = self._run("mándame más información").result
        self.assertEqual(a, b)

    def test_concierge_empty_message_does_not_crash(self):
        resp = self._run("")
        self.assertTrue(resp.ok)
        self.assertTrue(resp.result["reply"])
        self.assertEqual(resp.result["intent"], "general")


class MediaBuyerContractTest(unittest.TestCase):
    """MEDIABUYER: recommends scale|reallocate|pause|keep per campaign + a plan."""

    _CAMPS = [
        {"id": "1", "name": "Leads OK", "objective": "OUTCOME_LEADS", "status": "active",
         "region": "Santiago (RM)", "cpl_clp": 4000, "leads": 20},
        {"id": "2", "name": "Leads caro", "objective": "OUTCOME_LEADS", "status": "active",
         "region": "Santiago (RM)", "cpl_clp": 12000, "leads": 3},
    ]

    def _run(self, camps):
        m = _agents()["MEDIABUYER"]
        task = TaskPayload(agent="MEDIABUYER", client_id="acme", client_tier="GROWTH",
                           instructions="x", data={"campaigns": camps, "good_cpl_clp": 6000},
                           constraints=Constraints())
        return m.run(task)

    def test_mediabuyer_mock_valid(self):
        resp = self._run(self._CAMPS)
        self.assertTrue(resp.ok)
        recs = resp.result["recommendations"]
        self.assertEqual(len(recs), len(self._CAMPS))
        for r in recs:
            self.assertIn(r["action"], ("scale", "reallocate", "pause", "keep"))
            self.assertIn("campaign_id", r)
            self.assertTrue(r["reason"])
        self.assertTrue(resp.result["plan"])

    def test_mediabuyer_deterministic(self):
        a = self._run(self._CAMPS).result
        b = self._run(self._CAMPS).result
        self.assertEqual(a, b)

    def test_mediabuyer_no_campaigns_does_not_crash(self):
        resp = self._run([])
        self.assertTrue(resp.ok)
        self.assertEqual(resp.result["recommendations"], [])
        self.assertTrue(resp.result["plan"])


class OutreachContractTest(unittest.TestCase):
    """OUTREACH: one first-touch message per lead, channel within the allowed set."""

    def _run(self, leads, channels=("email",)):
        o = _agents()["OUTREACH"]
        task = TaskPayload(agent="OUTREACH", client_id="acme", client_tier="GROWTH",
                           instructions="x", data={"leads": leads},
                           constraints=Constraints(channels=list(channels)))
        return o.run(task)

    def test_outreach_mock_valid(self):
        leads = [{"company": "Acme", "role": "CEO", "channel": "email", "name": "Ana"}]
        resp = self._run(leads)
        self.assertTrue(resp.ok)
        msgs = resp.result["messages"]
        self.assertEqual(len(msgs), 1)
        m = msgs[0]
        for k in ("company", "channel", "subject", "body"):
            self.assertIn(k, m)
        self.assertTrue(m["body"])

    def test_outreach_coerces_disallowed_channel(self):
        # Lead asks for whatsapp but only email is permitted → falls back to email.
        leads = [{"company": "Acme", "role": "CEO", "channel": "whatsapp"}]
        m = self._run(leads, channels=["email"]).result["messages"][0]
        self.assertEqual(m["channel"], "email")
        self.assertIsNotNone(m["subject"])  # email carries a subject

    def test_outreach_deterministic(self):
        leads = [{"company": "Acme", "role": "CEO", "channel": "email", "name": "Ana"}]
        self.assertEqual(self._run(leads).result, self._run(leads).result)

    def test_outreach_empty_leads_does_not_crash(self):
        resp = self._run([])
        self.assertTrue(resp.ok)
        self.assertEqual(resp.result["messages"], [])


class TrackerContractTest(unittest.TestCase):
    """TRACKER: one follow-up per due sequence step, preserving lead_key/step/kind."""

    def _run(self, seqs, channels=("email",)):
        t = _agents()["TRACKER"]
        task = TaskPayload(agent="TRACKER", client_id="acme", client_tier="GROWTH",
                           instructions="x", data={"sequences": seqs},
                           constraints=Constraints(channels=list(channels)))
        return t.run(task)

    def test_tracker_mock_valid_preserves_step_identity(self):
        seqs = [{"lead_key": "k1", "company": "Acme", "channel": "email",
                 "kind": "breakup", "step": 3, "name": "Ana"}]
        m = self._run(seqs).result["messages"][0]
        self.assertEqual(m["lead_key"], "k1")
        self.assertEqual(m["step"], 3)
        self.assertEqual(m["kind"], "breakup")
        self.assertTrue(m["body"])

    def test_tracker_kinds_produce_distinct_copy(self):
        # nudge / value / breakup must not collapse into the same message.
        bodies = set()
        for kind in ("nudge", "value", "breakup"):
            seqs = [{"lead_key": "k", "company": "Acme", "channel": "email",
                     "kind": kind, "step": 1, "name": "Ana"}]
            bodies.add(self._run(seqs).result["messages"][0]["body"])
        self.assertEqual(len(bodies), 3)

    def test_tracker_deterministic(self):
        seqs = [{"lead_key": "k1", "company": "Acme", "channel": "email",
                 "kind": "nudge", "step": 1, "name": "Ana"}]
        self.assertEqual(self._run(seqs).result, self._run(seqs).result)

    def test_tracker_empty_sequences_does_not_crash(self):
        resp = self._run([])
        self.assertTrue(resp.ok)
        self.assertEqual(resp.result["messages"], [])


class AnalystContractTest(unittest.TestCase):
    """ANALYST: returns the three forecast rates + commentary (mock = baseline passthrough)."""

    def _run(self, rates, metrics=None):
        a = _agents()["ANALYST"]
        task = TaskPayload(agent="ANALYST", client_id="acme", client_tier="GROWTH",
                           instructions="x",
                           data={"rates": rates, "metrics": metrics or {"contacted": 4}},
                           constraints=Constraints())
        return a.run(task)

    def test_analyst_mock_passes_baseline_rates_through(self):
        rates = {"reply_rate": 0.3, "meeting_rate": 0.2, "win_rate": 0.1}
        resp = self._run(rates)
        self.assertTrue(resp.ok)
        self.assertEqual(resp.result["rates"], rates)
        self.assertTrue(resp.result["commentary"])

    def test_analyst_reports_all_three_rate_keys(self):
        # Even with no input rates, the contract shape must be complete (values None).
        resp = self._run({})
        self.assertEqual(
            set(resp.result["rates"].keys()),
            {"reply_rate", "meeting_rate", "win_rate"},
        )

    def test_analyst_deterministic(self):
        rates = {"reply_rate": 0.3, "meeting_rate": 0.2, "win_rate": 0.1}
        self.assertEqual(self._run(rates).result, self._run(rates).result)


if __name__ == "__main__":
    unittest.main()
