"""Core safety net — the invariants ZERO must never break.

Stdlib unittest, no deps, all in mock. Run from the project root:

    python3 -m unittest discover -s tests -t .

These tests lock in the *logic* (gate, discovery delivery, scoring, CRM stages,
the whole pipeline). They don't judge lead quality — that's the real model's job.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

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


class ReplyLoopTest(unittest.TestCase):
    """When a lead replies, ZERO stops chasing it and moves it to `replied`."""

    def _run(self):
        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)
        z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
        return z, crm

    def test_reply_closes_sequence_and_advances_stage(self):
        z, crm = self._run()
        key = crm.list("acme", "nurturing")[0]["key"]
        # the lead has an open follow-up sequence before it replies
        self.assertTrue(any(s["lead_key"] == key and s["status"] == "open"
                            for s in z.memory.sequences))

        res = z.register_reply("acme", key, text="me interesa, llámenme")

        self.assertEqual(res["stage"], "replied")
        self.assertTrue(res["sequence_closed"])
        self.assertEqual(crm.get("acme", key)["stage"], "replied")
        # the sequence is closed → TRACKER never nudges this lead again
        self.assertFalse(any(s["lead_key"] == key and s["status"] == "open"
                             for s in z.memory.sequences))
        # and a far-future follow-up sweep won't pick it up
        future = (datetime.now(timezone.utc) + timedelta(days=999)).isoformat()
        self.assertFalse(any(s["lead_key"] == key
                             for s in z.memory.due_sequences("acme", as_of=future)))

    def test_reply_without_open_sequence_still_advances(self):
        z, crm = self._run()
        key = crm.list("acme", "nurturing")[0]["key"]
        z.memory.close_sequence_for_lead("acme", key)   # no open sequence anymore
        res = z.register_reply("acme", key)
        self.assertFalse(res["sequence_closed"])
        self.assertEqual(res["stage"], "replied")

    def test_reply_is_forward_only(self):
        z, crm = self._run()
        key = crm.list("acme", "nurturing")[0]["key"]
        crm.set_stage("acme", key, "won", detail="cerró")
        z.register_reply("acme", key)
        self.assertEqual(crm.get("acme", key)["stage"], "won")  # not dragged back


class ChannelTest(unittest.TestCase):
    """The outbox delivers what gets drafted — mock-first, faithful contract."""

    def test_mock_sender_contract(self):
        from zero.channels import MockSender
        res = MockSender().send({"channel": "email", "to": "a@b.com", "body": "hola"})
        for k in ("channel", "to", "status", "id", "error", "via"):
            self.assertIn(k, res)
        self.assertEqual(res["status"], "sent")
        # no recipient → skipped, not crash
        self.assertEqual(MockSender().send({"channel": "whatsapp", "body": "x"})["status"], "skipped")

    def test_outbox_default_is_mock_and_never_raises(self):
        from zero.channels import Outbox
        box = Outbox()
        self.assertFalse(box.live)

        class Boom:
            name = "email"
            def send(self, msg):
                raise RuntimeError("smtp caído")
        box = Outbox({"email": Boom()})
        self.assertTrue(box.live)
        res = box.send({"channel": "email", "to": "a@b.com", "body": "x"})
        self.assertEqual(res["status"], "error")          # degraded, not crashed
        self.assertIn("smtp caído", res["error"])

    def test_pipeline_sends_first_touch_via_mock(self):
        from zero.channels import Outbox
        crm = CRM(None)
        box = Outbox()
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm, outbox=box)
        d = z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)

        self.assertEqual(d["summary"]["delivery"], "mock")
        self.assertGreater(d["summary"]["sent"], 0)
        self.assertEqual(d["summary"]["sent"], len(box.log))
        # every send is recorded on the lead's CRM history
        key = crm.list("acme", "nurturing")[0]["key"]
        self.assertTrue(any(h["event"] == "send" for h in crm.get("acme", key)["history"]))


class ConciergeTest(unittest.TestCase):
    """The conversational agent answers inbound questions about the business."""

    def _zero(self):
        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)
        z.run_pipeline("acme", "GROWTH", "fintech LATAM", count=8)
        return z, crm

    def test_concierge_intents(self):
        z = Zero(build_agents(mock=True), memory=SessionMemory(None))
        z.memory.set_client_icp("acme", {"sells": "pallets de madera"})
        self.assertIn("plan", z.converse("acme", "¿cuánto cuesta?").lower())
        self.assertIn("pallets", z.converse("acme", "¿qué hacen exactamente?").lower())
        self.assertTrue(z.converse("acme", "¿podemos agendar una llamada?"))
        # transparency: admits it's an AI if asked
        self.assertIn("ia", z.converse("acme", "¿eres un robot?").lower())

    def test_parse_inbound(self):
        from zero.whatsapp_inbound import parse_inbound
        payload = {"entry": [{"changes": [{"value": {"messages": [
            {"from": "56999111222", "type": "text", "text": {"body": "hola, precio?"}},
            {"from": "56999333444", "type": "image"},
        ]}}]}]}
        msgs = parse_inbound(payload)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0], {"from": "56999111222", "text": "hola, precio?"})
        self.assertEqual(msgs[1]["text"], "[image]")
        self.assertEqual(parse_inbound({}), [])      # malformed → empty, no crash

    def test_inbound_matches_lead_and_replies(self):
        z, crm = self._zero()
        lead = crm.list("acme", "nurturing")[0]
        phone = lead.get("phone")
        if not phone:   # a contacted lead always has email or phone; use email then
            res = z.handle_inbound(lead["email"], "¿qué hacen?")
        else:
            res = z.handle_inbound("".join(c for c in phone if c.isdigit()), "¿qué hacen?")
        self.assertTrue(res["matched"])
        self.assertTrue(res["reply"])                      # the agent answered
        self.assertEqual(crm.get("acme", lead["key"])["stage"], "replied")
        self.assertTrue(any(h["event"] == "auto_reply"
                            for h in crm.get("acme", lead["key"])["history"]))

    def test_inbound_unmatched_is_not_an_error(self):
        z, _ = self._zero()
        res = z.handle_inbound("000000000", "hola?")
        self.assertFalse(res["matched"])


class ScalabilityTest(unittest.TestCase):
    """Reads are scoped by client and paginated — no full-table scans."""

    def _crm(self):
        crm = CRM(None)
        for c in ("acme", "globex"):
            for n in range(5):
                crm.upsert(c, {"company": f"{c}-{n}", "role": "CEO",
                               "email": f"{n}@{c}.com", "score": 90 - n}, stage="qualified")
        return crm

    def test_client_ids_and_scoped_list(self):
        crm = self._crm()
        self.assertEqual(crm.client_ids(), ["acme", "globex"])
        acme = crm.list("acme")
        self.assertEqual(len(acme), 5)
        self.assertTrue(all(r["client_id"] == "acme" for r in acme))

    def test_list_pagination(self):
        crm = self._crm()
        page1 = crm.list("acme", limit=2, offset=0)
        page2 = crm.list("acme", limit=2, offset=2)
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 2)
        self.assertNotEqual(page1[0]["key"], page2[0]["key"])   # different slice
        # sorted by score desc → highest first
        self.assertGreaterEqual(page1[0]["score"], page1[1]["score"])

    def test_query_groups_and_pagination(self):
        crm = self._crm()
        self.assertEqual(len(crm.query("acme")), 5)                       # all of one client
        crm.set_stage("acme", crm.list("acme")[0]["key"], "won")
        self.assertEqual(len(crm.query("acme", stages=["won"])), 1)       # group filter
        self.assertEqual(len(crm.query("acme", stages=["qualified"])), 4)
        self.assertEqual(len(crm.query("acme", limit=2, offset=0)), 2)    # page 1
        self.assertEqual(len(crm.query("acme", limit=2, offset=4)), 1)    # last page
        self.assertEqual([r["client_id"] for r in crm.query("acme")], ["acme"] * 5)

    def test_ensure_hook_is_called_per_client(self):
        # SupabaseCRM uses this hook to lazy-load; the base must invoke it on reads.
        crm = CRM(None)
        seen = []
        crm._ensure = lambda cid: seen.append(cid)   # noqa
        crm.list("acme"); crm.counts("globex"); crm.get("acme", "x")
        self.assertIn("acme", seen)
        self.assertIn("globex", seen)


class AuthTest(unittest.TestCase):
    """Single-password agency gate: tokens signed by the password itself."""

    def setUp(self):
        import os
        self._prev = os.environ.get("AUTH_PASSWORD")
        os.environ["AUTH_PASSWORD"] = "s3cret"

    def tearDown(self):
        import os
        if self._prev is None:
            os.environ.pop("AUTH_PASSWORD", None)
        else:
            os.environ["AUTH_PASSWORD"] = self._prev

    def test_password_and_token_roundtrip(self):
        from zero import auth
        self.assertTrue(auth.auth_enabled())
        self.assertTrue(auth.verify_password("s3cret"))
        self.assertFalse(auth.verify_password("nope"))
        tok = auth.make_token()
        self.assertTrue(auth.valid_token(tok))
        self.assertFalse(auth.valid_token(tok + "x"))      # tampered
        self.assertFalse(auth.valid_token("garbage"))

    def test_expired_and_password_change_invalidate(self):
        from zero import auth
        import os
        self.assertFalse(auth.valid_token(auth.make_token(ttl=-1)))   # expired
        tok = auth.make_token()
        os.environ["AUTH_PASSWORD"] = "rotated"                       # rotate
        self.assertFalse(auth.valid_token(tok))                       # old token dies

    def test_disabled_when_no_password(self):
        from zero import auth
        import os
        os.environ.pop("AUTH_PASSWORD", None)
        self.assertFalse(auth.auth_enabled())
        self.assertFalse(auth.valid_token(auth.make_token()))


class MetaAdsTest(unittest.TestCase):
    """Mock de campañas fiel al contrato y determinista por cliente."""

    def test_mock_campaigns_contract(self):
        from zero.metaads import MockMetaAds
        camps = MockMetaAds().campaigns("acme")
        self.assertTrue(camps)
        for c in camps:
            for k in ("id", "name", "objective", "status", "region", "budget_clp", "spent_clp", "leads", "cpl_clp"):
                self.assertIn(k, c)
            self.assertIn(c["status"], ("active", "paused"))
        # determinista por cliente
        self.assertEqual([c["name"] for c in MockMetaAds().campaigns("acme")],
                         [c["name"] for c in MockMetaAds().campaigns("acme")])

    def test_per_client_config_personalizes(self):
        from zero.metaads import MockMetaAds
        cfg = {"monthly_budget_clp": 1_000_000, "regions": ["Valparaíso"]}
        camps = MockMetaAds().campaigns("acme", cfg)
        self.assertEqual(camps[0]["region"], "Valparaíso")          # zona del cliente
        # presupuesto mayor → montos mayores que el default
        base = MockMetaAds().campaigns("acme")[0]["budget_clp"]
        self.assertGreater(camps[0]["budget_clp"], base)

    def test_make_metaads_defaults_to_mock(self):
        from zero.metaads import make_metaads, MockMetaAds
        self.assertIsInstance(make_metaads(), MockMetaAds)   # sin credenciales → mock

    def test_ad_leads_flow_into_crm(self):
        from zero.metaads import MockMetaAds
        crm = CRM(None)
        z = Zero(build_agents(mock=True), memory=SessionMemory(None), crm=crm)
        leads = MockMetaAds().lead_ads("acme")
        self.assertTrue(leads)
        res = z.import_ad_leads("acme", leads)
        self.assertEqual(res["imported"], len(leads))
        recs = crm.list("acme")
        self.assertEqual(len(recs), len(leads))
        self.assertTrue(all("Meta Ads" in (r.get("tags") or []) for r in recs))
        self.assertTrue(all(r["stage"] == "qualified" for r in recs))

    def test_mediabuyer_recommends_actions(self):
        a = build_agents(mock=True)["MEDIABUYER"]
        camps = [
            {"id": "1", "name": "Leads OK", "objective": "OUTCOME_LEADS", "status": "active", "region": "Santiago (RM)", "cpl_clp": 4000, "leads": 20},
            {"id": "2", "name": "Leads caro", "objective": "OUTCOME_LEADS", "status": "active", "region": "Santiago (RM)", "cpl_clp": 12000, "leads": 3},
            {"id": "3", "name": "Awareness", "objective": "OUTCOME_AWARENESS", "status": "active", "region": "Santiago (RM)", "cpl_clp": 0, "leads": 0},
        ]
        resp = a.run(TaskPayload(agent="MEDIABUYER", client_id="acme", client_tier="",
                                 instructions="x", data={"campaigns": camps, "good_cpl_clp": 6000}))
        recs = {r["name"]: r["action"] for r in resp.result["recommendations"]}
        self.assertEqual(recs["Leads OK"], "scale")          # CPL bajo el objetivo
        self.assertEqual(recs["Leads caro"], "reallocate")   # CPL alto
        self.assertEqual(recs["Awareness"], "reallocate")    # no trae leads
        self.assertTrue(resp.result["plan"])


if __name__ == "__main__":
    unittest.main()
