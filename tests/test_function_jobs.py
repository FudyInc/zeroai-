"""Trabajos de agente pedidos por una función programada (zero/function_actions.py).

Lo que se prueba acá son los RIELES, no que el pipeline funcione (eso ya está
en test_core.py). El riesgo de esta feature es específico: son corridas
desatendidas, cada N minutos, sin nadie mirando. Un tope mal puesto no se nota
hasta que el CRM tiene 200 leads basura o le llegó un mensaje a un cliente real.

Orquestador falso en la frontera — ningún test sale a la web ni llama a un
modelo.

Correr solo:  python3 -m unittest tests.test_function_jobs -v
"""
from __future__ import annotations

import unittest

from zero import config, function_actions


class _FakeMemory:
    def __init__(self, clients=None):
        self.clients = clients or {}


class _FakeZero:
    """Lo que run_job realmente toca del orquestador."""

    def __init__(self, engine_mode="local", clients=None, fail=None):
        self._engine_mode = engine_mode
        self.memory = _FakeMemory(clients)
        self.fail = fail
        self.pipeline_calls = []
        self.followup_calls = []

    def run_pipeline(self, client_id, tier, query, count=8, auto_send=True, **kw):
        if self.fail:
            raise RuntimeError(self.fail)
        self.pipeline_calls.append(
            {"client": client_id, "tier": tier, "query": query,
             "count": count, "auto_send": auto_send})
        return {"delivered": [{"company": "Acme"}] * min(count, 2)}

    def run_followups(self, client_id, as_of=None, auto_send=True):
        self.followup_calls.append(
            {"client": client_id, "as_of": as_of, "auto_send": auto_send})
        return {"advanced": 3}


class _FakeCRM:
    def __init__(self):
        self.saved = False

    def list(self, client_id, stage=None):
        return []

    def save(self):
        self.saved = True


def _fn(client_id="acme"):
    return {"id": "f1", "lookup_scope": {"client_id": client_id}}


def _apply(actions, zero, crm=None):
    return function_actions.apply_actions({"actions": actions}, _fn(),
                                          crm=crm or _FakeCRM(), zero=zero)


class NeverSendsTest(unittest.TestCase):
    """El riel que más importa: una corrida automática deja BORRADORES, nunca
    manda. Si esto se rompe, un lead real recibe un mensaje que nadie revisó."""

    def test_pipeline_runs_in_review_mode(self):
        z = _FakeZero(clients={"acme": {"tier": "GROWTH"}})
        _apply([{"type": "pipeline", "query": "fintech"}], z)
        self.assertFalse(z.pipeline_calls[0]["auto_send"])

    def test_followups_run_in_review_mode(self):
        z = _FakeZero(clients={"acme": {"tier": "GROWTH"}})
        _apply([{"type": "followups"}], z)
        self.assertFalse(z.followup_calls[0]["auto_send"])

    def test_policy_constant_is_false(self):
        """Blindaje explícito: si alguien la pone en True, este test lo dice."""
        self.assertFalse(config.FUNCTION_JOBS_AUTO_SEND)


class MockEngineRefusedTest(unittest.TestCase):
    def test_job_with_mock_agents_is_rejected(self):
        """Con agentes en mock el pipeline inventa leads deterministas y los
        escribe en el CRM real — trabajo falso indistinguible del de verdad."""
        z = _FakeZero(engine_mode="mock", clients={"acme": {"tier": "GROWTH"}})
        rep = _apply([{"type": "pipeline", "query": "fintech"}], z)
        self.assertEqual(rep["applied"], 0)
        self.assertEqual(z.pipeline_calls, [])
        self.assertIn("mock", rep["rejected"][0]["reason"])


class CountCapTest(unittest.TestCase):
    def test_count_is_capped_by_policy(self):
        z = _FakeZero(clients={"acme": {"tier": "GROWTH"}})
        _apply([{"type": "pipeline", "query": "x", "count": 999}], z)
        self.assertEqual(z.pipeline_calls[0]["count"], config.FUNCTION_JOB_MAX_COUNT)

    def test_count_has_a_floor_of_one(self):
        z = _FakeZero(clients={"acme": {"tier": "GROWTH"}})
        _apply([{"type": "pipeline", "query": "x", "count": 0}], z)
        self.assertGreaterEqual(z.pipeline_calls[0]["count"], 1)

    def test_garbage_count_is_rejected_with_a_reason(self):
        z = _FakeZero(clients={"acme": {"tier": "GROWTH"}})
        rep = _apply([{"type": "pipeline", "query": "x", "count": "muchos"}], z)
        self.assertEqual(rep["applied"], 0)
        self.assertIn("count", rep["rejected"][0]["reason"])


class JobsPerRunCapTest(unittest.TestCase):
    def test_only_one_job_runs_per_tick(self):
        """Un bucle con bug que pida 5 pipelines dejaría al scheduler ocupado
        horas y llenaría el CRM. Corre uno; el resto se rechaza y se reporta."""
        z = _FakeZero(clients={"acme": {"tier": "GROWTH"}})
        rep = _apply([{"type": "pipeline", "query": f"q{i}"} for i in range(5)], z)
        self.assertEqual(len(z.pipeline_calls), config.FUNCTION_MAX_JOBS_PER_RUN)
        self.assertEqual(rep["applied"], config.FUNCTION_MAX_JOBS_PER_RUN)
        self.assertEqual(len(rep["rejected"]), 5 - config.FUNCTION_MAX_JOBS_PER_RUN)


class TierResolutionTest(unittest.TestCase):
    def test_tier_comes_from_the_registered_client(self):
        z = _FakeZero(clients={"acme": {"tier": "SCALE"}})
        _apply([{"type": "pipeline", "query": "x"}], z)
        self.assertEqual(z.pipeline_calls[0]["tier"], "SCALE")

    def test_registered_tier_wins_over_the_action(self):
        """El tier es política de negocio: una función suelta no lo redefine."""
        z = _FakeZero(clients={"acme": {"tier": "STARTER"}})
        _apply([{"type": "pipeline", "query": "x", "tier": "ENTERPRISE"}], z)
        self.assertEqual(z.pipeline_calls[0]["tier"], "STARTER")

    def test_unknown_client_tier_is_rejected_not_guessed(self):
        z = _FakeZero(clients={})
        rep = _apply([{"type": "pipeline", "query": "x"}], z)
        self.assertEqual(rep["applied"], 0)
        self.assertIn("tier", rep["rejected"][0]["reason"])


class ValidationTest(unittest.TestCase):
    def test_pipeline_without_query_is_rejected(self):
        z = _FakeZero(clients={"acme": {"tier": "GROWTH"}})
        rep = _apply([{"type": "pipeline"}], z)
        self.assertEqual(rep["applied"], 0)
        self.assertIn("query", rep["rejected"][0]["reason"])

    def test_job_without_orchestrator_is_rejected(self):
        rep = function_actions.apply_actions({"actions": [{"type": "followups"}]},
                                             _fn(), crm=_FakeCRM(), zero=None)
        self.assertEqual(rep["applied"], 0)

    def test_a_failing_job_is_reported_not_raised(self):
        z = _FakeZero(clients={"acme": {"tier": "GROWTH"}}, fail="la red se cayó")
        rep = _apply([{"type": "pipeline", "query": "x"}], z)
        self.assertEqual(rep["applied"], 0)
        self.assertIn("la red se cayó", rep["rejected"][0]["reason"])

    def test_unknown_type_still_rejected(self):
        z = _FakeZero(clients={"acme": {"tier": "GROWTH"}})
        rep = _apply([{"type": "borrar_todo"}], z)
        self.assertEqual(rep["applied"], 0)


class MixedActionsTest(unittest.TestCase):
    def test_a_job_and_lead_actions_coexist(self):
        """Un trabajo de agente no rompe el camino de las acciones por lead:
        el job corre y la acción con lead inexistente se rechaza como siempre."""
        z = _FakeZero(clients={"acme": {"tier": "GROWTH"}})
        rep = _apply([
            {"type": "followups"},
            {"type": "note", "lead": "nadie@ejemplo.cl", "text": "hola"},
        ], z, crm=_FakeCRMNoLead())
        self.assertEqual(len(z.followup_calls), 1)
        self.assertEqual(rep["applied"], 1)
        self.assertEqual(len(rep["rejected"]), 1)


class _FakeCRMNoLead(_FakeCRM):
    def find_by_contact(self, phone=None, email=None):
        return None


if __name__ == "__main__":
    unittest.main()
