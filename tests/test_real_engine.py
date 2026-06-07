"""Tests del **camino real** (no-mock) sin necesitar API key.

Un `ScriptedBackend` simula un LLM real devolviendo JSON correcto pero *sucio*
(fences, prosa, arrays sin envoltorio, scores como string/float). Así probamos que:
  1. el parseo aguanta lo que devuelven los modelos de verdad,
  2. el pipeline corre end-to-end por el camino real (backend, no mock),
  3. un fallo del backend degrada en vez de crashear.
"""
import json
import unittest

from zero.agents import build_agents
from zero.backends import extract_json
from zero.contracts import AgentResponse, Lead
from zero.memory import SessionMemory
from zero.orchestrator import Zero


class ScriptedBackend:
    """Finge un LLM real: respuestas válidas pero desordenadas a propósito."""

    def complete(self, system, user, model, max_tokens=4096):
        task = json.loads(user)
        agent = task.get("agent")
        data = task.get("data", {})
        return getattr(self, f"_{agent.lower()}")(task, data)

    def _prospector(self, task, data):
        cap = (task.get("constraints") or {}).get("max_items") or 5
        leads = [{
            "company": f"Empresa{i}", "domain": f"empresa{i}.cl",
            "name": f"Contacto{i}", "role": "Gerente de Operaciones",
            "email": f"contacto{i}@empresa{i}.cl", "phone": f"+5699000000{i}",
            "channel": "email", "source": "scripted",
        } for i in range(cap)]
        body = {"task_id": task["task_id"], "agent": "PROSPECTOR",
                "status": "done", "result": {"leads": leads}}
        # sucio: prosa + code fence
        return "Claro, aquí van los leads:\n```json\n" + json.dumps(body) + "\n```"

    def _qualifier(self, task, data):
        leads = data.get("leads", [])
        # scores mixtos y de tipos distintos: string / float / int / bajos
        scores = ["92", 88.0, 75, 50, 40]
        out = []
        for i, ld in enumerate(leads):
            e = dict(ld)
            e["score"] = scores[i % len(scores)]
            e["icp_reasons"] = ["fit de rol", "scoring real"]
            out.append(e)
        # sucio: ARRAY desnudo (sin envoltorio) y con prosa antes
        return "Evalué los leads:\n" + json.dumps(out)

    def _outreach(self, task, data):
        leads = data.get("leads", [])
        msgs = [{"company": l.get("company"), "channel": "email",
                 "subject": "Hola", "body": f"Mensaje para {l.get('company')}"} for l in leads]
        # sucio: sin envoltorio (solo {messages}) + fence
        return "```json\n" + json.dumps({"messages": msgs}) + "\n```"

    def _analyst(self, task, data):
        body = {"agent": "ANALYST", "status": "done",
                "result": {"rates": data.get("rates", {}), "commentary": "sin cambios"}}
        return json.dumps(body)

    def _tracker(self, task, data):
        seqs = data.get("sequences", [])
        msgs = [{"lead_key": s.get("lead_key"), "company": s.get("company"),
                 "channel": "email", "step": s.get("step"), "kind": s.get("kind"),
                 "subject": "hola", "body": "follow"} for s in seqs]
        return json.dumps({"agent": "TRACKER", "status": "done", "result": {"messages": msgs}})


class BoomBackend:
    def complete(self, *a, **k):
        raise RuntimeError("backend caído")


class TestExtractJson(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})

    def test_fenced(self):
        self.assertEqual(extract_json('```json\n{"a": 1}\n```'), {"a": 1})

    def test_prose_before_object(self):
        self.assertEqual(extract_json('Aquí tienes:\n{"a": 1} listo'), {"a": 1})

    def test_bare_array_wrapped(self):
        self.assertEqual(extract_json('[{"x": 1}]'), {"leads": [{"x": 1}]})

    def test_prose_before_array(self):
        # debe agarrar el array completo, no el primer objeto interno
        self.assertEqual(extract_json('Listo:\n[{"x": 1}, {"x": 2}]'),
                         {"leads": [{"x": 1}, {"x": 2}]})

    def test_braces_inside_strings(self):
        self.assertEqual(extract_json('{"body": "usa {llaves} y ] aquí"}'),
                         {"body": "usa {llaves} y ] aquí"})

    def test_garbage_is_none(self):
        self.assertIsNone(extract_json("no hay json aquí"))
        self.assertIsNone(extract_json(""))


class TestResponseRobustness(unittest.TestCase):
    def test_missing_envelope_lifts_payload(self):
        r = AgentResponse.from_dict({"leads": [{"company": "X"}]}, "t", "QUALIFIER")
        self.assertEqual(r.status, "done")
        self.assertEqual(r.result["leads"], [{"company": "X"}])

    def test_result_as_list_wrapped(self):
        r = AgentResponse.from_dict({"result": [{"company": "X"}]}, "t", "QUALIFIER")
        self.assertEqual(r.result, {"leads": [{"company": "X"}]})

    def test_invalid_status_inferred(self):
        self.assertEqual(AgentResponse.from_dict({"result": {"leads": [1]}}).status, "done")
        self.assertEqual(AgentResponse.from_dict({"foo": "bar"}).status, "error")

    def test_score_coercion(self):
        self.assertEqual(Lead.from_dict({"score": "85"}).score, 85)
        self.assertEqual(Lead.from_dict({"score": 73.0}).score, 73)
        self.assertIsNone(Lead.from_dict({"score": "n/d"}).score)


class TestRealPipeline(unittest.TestCase):
    def setUp(self):
        self.zero = Zero(build_agents(backend=ScriptedBackend(), mock=False),
                         memory=SessionMemory())

    def test_pipeline_runs_on_real_path(self):
        res = self.zero.run_pipeline("acme", "GROWTH", "fintech LATAM", count=5,
                                     icp={"sells": "pallets", "regions": ["RM"]})
        s = res["summary"]
        self.assertEqual(s["discovered"], 5)
        # scores 92/88/75 pasan (>=70); 50/40 no → 3 calificados, 2 rechazados
        self.assertEqual(s["qualified"], 3)
        self.assertEqual(s["rejected"], 2)
        self.assertTrue(all(l["score"] >= 70 for l in res["qualified_leads"]))
        self.assertEqual(len(res["outreach"]), 3)
        self.assertIn("pallets", s["icp"])

    def test_forecast_on_real_path(self):
        self.zero.run_pipeline("acme", "GROWTH", "fintech", count=5)
        fc = self.zero.forecast("acme")["forecast"]
        self.assertIn("expected_pipeline_usd", fc["projection"])
        self.assertGreaterEqual(fc["projection"]["expected_pipeline_usd"], 0)


class TestBackendDegrades(unittest.TestCase):
    def test_backend_failure_does_not_crash(self):
        zero = Zero(build_agents(backend=BoomBackend(), mock=False), memory=SessionMemory())
        res = zero.run_pipeline("acme", "GROWTH", "x", count=3)
        # PROSPECTOR falla → el pipeline reporta error de etapa, no explota
        self.assertEqual(res.get("error"), "discover")


if __name__ == "__main__":
    unittest.main()
