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


class MediaBuyerImproveAdTest(unittest.TestCase):
    """MEDIABUYER improve_ad: sugiere cómo mejorar UN anuncio pagado, sin inventar cifras."""

    _AD = {"ad_id": "a1", "ad_name": "Losetas verano", "campaign_name": "Leads RM", "status": "ACTIVE",
           "creative": {"title": "Losetas Chile", "body": "Calidad y buen precio.",
                        "image_url": "https://x/img.jpg", "call_to_action": "LEARN_MORE"},
           "spend": 50000, "impressions": 12000, "reach": 9000, "clicks": 60, "ctr": 0.5,
           "leads": 4, "cpl": 12500}

    def _run(self, ad):
        m = _agents()["MEDIABUYER"]
        task = TaskPayload(agent="MEDIABUYER", client_id="acme", client_tier="GROWTH",
                           instructions="x", data={"action": "improve_ad", "ad": ad,
                                                   "good_cpl_clp": 6000},
                           constraints=Constraints())
        return m.run(task)

    def test_contract_shape(self):
        resp = self._run(self._AD)
        self.assertTrue(resp.ok)
        r = resp.result
        self.assertTrue(r["diagnostico"])
        self.assertFalse(r["pocos_datos"])
        self.assertTrue(r["sugerencias"])
        for s in r["sugerencias"]:
            self.assertIn(s["campo"], ("title", "body", "call_to_action", "imagen"))
            for k in ("actual", "propuesta", "por_que"):
                self.assertIsInstance(s[k], str)
            self.assertTrue(s["propuesta"] and s["por_que"])
        # `actual` es la creatividad real del anuncio, no lo que diga el modelo.
        por_campo = {s["campo"]: s["actual"] for s in r["sugerencias"]}
        self.assertEqual(por_campo.get("title"), "Losetas Chile")
        self.assertEqual(por_campo.get("imagen"), "https://x/img.jpg")
        nombres = {m["metrica"] for m in r["metricas_usadas"]}
        self.assertTrue({"ctr", "cpl"} <= nombres)

    def test_deterministic(self):
        self.assertEqual(self._run(self._AD).result, self._run(self._AD).result)

    def test_few_impressions_says_so(self):
        ad = dict(self._AD, impressions=400)
        r = self._run(ad).result
        self.assertTrue(r["pocos_datos"])
        self.assertIn("pocos datos para concluir", r["diagnostico"].lower())

    def test_missing_impressions_counts_as_few(self):
        ad = {k: v for k, v in self._AD.items() if k != "impressions"}
        self.assertTrue(self._run(ad).result["pocos_datos"])

    def test_no_figures_absent_from_item(self):
        from zero.agents.mediabuyer import cifras_ajenas, _contexto_ad
        for ad in (self._AD, dict(self._AD, impressions=300), dict(self._AD, leads=0, cpl=None),
                   dict(self._AD, ctr=2.4, cpl=3000)):
            task = TaskPayload(agent="MEDIABUYER", client_id="acme", client_tier="", instructions="x",
                               data={"action": "improve_ad", "ad": ad, "good_cpl_clp": 6000})
            r = _agents()["MEDIABUYER"].run(task).result
            self.assertEqual(cifras_ajenas(r, ad, _contexto_ad(task)), [], ad)

    def test_validator_catches_invented_figures(self):
        from zero.agents.mediabuyer import cifras_ajenas, _contexto_ad
        task = TaskPayload(agent="MEDIABUYER", client_id="acme", client_tier="", instructions="x",
                           data={"action": "improve_ad", "ad": self._AD, "good_cpl_clp": 6000})
        r = {"diagnostico": "CPL $12.500 sobre $6.000 y CTR 0,5%.",
             "sugerencias": [{"campo": "body", "actual": "", "propuesta": "Ofrece 20% de descuento",
                              "por_que": "Subiría el CTR a 1,8%"}]}
        self.assertEqual(cifras_ajenas(r, self._AD, _contexto_ad(task)), ["20", "1,8"])

    def _ajenas(self, ad, texto):
        from zero.agents.mediabuyer import cifras_ajenas, _contexto_ad
        task = TaskPayload(agent="MEDIABUYER", client_id="acme", client_tier="", instructions="x",
                           data={"action": "improve_ad", "ad": ad, "good_cpl_clp": 6000})
        return cifras_ajenas({"diagnostico": texto, "sugerencias": []}, ad, _contexto_ad(task))

    def test_validator_does_not_read_ctr_times_100_as_allowed(self):
        # Con CTR 0.5, «50» no puede pasar por «el CTR en otra escala».
        self.assertEqual(self._ajenas(self._AD, "Ofrece 50% de descuento"), ["50"])

    def test_validator_is_strict_on_small_values(self):
        self.assertEqual(self._ajenas(self._AD, "CTR 0,55%"), ["0,55"])
        self.assertEqual(self._ajenas(dict(self._AD, ctr=0.534), "CTR 0,53% (0,5%)"), [])

    def test_validator_reads_chilean_formats(self):
        ad = dict(self._AD, cpl=12500.5, spend=1234567)
        self.assertEqual(self._ajenas(ad, "CPL $12.500,5 · gasto $1.234.567 · objetivo $6.000"), [])

    def test_validator_allows_numbers_in_the_ad_name(self):
        self.assertEqual(self._ajenas(dict(self._AD, ad_name="Verano 2025"), "«Verano 2025»"), [])

    def test_ctr_as_fraction_is_detected_and_cited_as_percent(self):
        ad = dict(self._AD, ctr=0.005)   # 60 / 12000 = 0.5 %
        r = self._run(ad).result
        self.assertIn("0,5%", " ".join(s["por_que"] for s in r["sugerencias"]))
        self.assertEqual(self._ajenas(ad, "CTR 0,5%"), [])

    def test_every_por_que_cites_a_metric_even_if_the_model_did_not(self):
        class Vago:
            def complete(self, system, user, model):
                return '{"diagnostico": "CTR bajo", "sugerencias": [' \
                       '{"campo": "title", "propuesta": "Nuevo", "por_que": "No llama la atención."},' \
                       '{"campo": "body", "propuesta": "Nuevo", "por_que": "No convierte."}]}'
        m = build_agents(backend=Vago())["MEDIABUYER"]
        r = m.run(TaskPayload(agent="MEDIABUYER", client_id="acme", client_tier="", instructions="x",
                              data={"action": "improve_ad", "ad": self._AD, "good_cpl_clp": 6000})).result
        por_que = {s["campo"]: s["por_que"] for s in r["sugerencias"]}
        self.assertIn("CTR 0,5%", por_que["title"])
        self.assertIn("CPL $12.500 vs objetivo de $6.000", por_que["body"])
        self.assertEqual({x["metrica"] for x in r["metricas_usadas"]}, {"ctr", "cpl"})

    def test_signals_reach_the_model(self):
        seen = {}

        class Spy:
            def complete(self, system, user, model):
                seen["user"] = user
                return '{"diagnostico": "ok", "sugerencias": []}'
        m = build_agents(backend=Spy())["MEDIABUYER"]
        m.run(TaskPayload(agent="MEDIABUYER", client_id="acme", client_tier="", instructions="x",
                          data={"action": "improve_ad", "ad": self._AD, "good_cpl_clp": 6000}))
        self.assertIn('"ctr_bajo": true', seen["user"])
        self.assertIn('"cpl_sobre_objetivo": true', seen["user"])

    def test_real_path_rejects_invented_figures_instead_of_showing_them(self):
        class Fake:
            def complete(self, system, user, model):
                return '{"diagnostico": "CTR 0.5%", "sugerencias": [{"campo": "title", ' \
                       '"propuesta": "Ahorra 30%", "por_que": "CTR 0.5%"}]}'
        m = build_agents(backend=Fake())["MEDIABUYER"]
        resp = m.run(TaskPayload(agent="MEDIABUYER", client_id="acme", client_tier="",
                                 instructions="x", data={"action": "improve_ad", "ad": self._AD,
                                                         "good_cpl_clp": 6000}))
        self.assertEqual(resp.status, "error")
        self.assertIn("30", resp.notes)

    def test_helper_raises_on_engine_error(self):
        from zero.agents.mediabuyer import improve_ad

        class Down:
            def complete(self, *a, **k):
                raise ConnectionError("ollama caído")
        from zero.memory import SessionMemory
        from zero.orchestrator import Zero
        z = Zero(build_agents(backend=Down()), memory=SessionMemory())
        with self.assertRaises(RuntimeError):
            improve_ad(z, self._AD, 6000, "acme")


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
