"""CONCIERGE intent detection — 15+ real-world Spanish messages → expected intent.

Covers the 9 intents (disclose, optout, trust, objection, info, pricing, explain,
meeting, accept) plus the edge cases that make WhatsApp text messy: CAPS, missing
tildes, elongated words, emojis, and one-word replies.

Run: python3 -m unittest tests.test_concierge_intents -v
"""
from __future__ import annotations

import unittest

from zero.agents import build_agents
from zero.contracts import Constraints, TaskPayload


def _intent(msg: str) -> dict:
    c = build_agents(mock=True)["CONCIERGE"]
    task = TaskPayload(agent="CONCIERGE", client_id="acme", client_tier="GROWTH",
                       instructions="x",
                       data={"message": msg, "lead": {"name": "Carla", "company": "Acme"},
                             "icp": {"sells": "pallets"}},
                       constraints=Constraints(channels=["whatsapp"]))
    return c.run(task).result


class CoreIntentTest(unittest.TestCase):
    """One real message per intent — the happy path for each of the 9 intents."""

    def test_intent_disclose(self):
        self.assertEqual(_intent("¿eres un bot o una persona?")["intent"], "disclose")

    def test_intent_optout_explicit(self):
        self.assertEqual(_intent("no me interesa, gracias")["intent"], "optout")

    def test_intent_trust_implicit(self):
        self.assertEqual(_intent("es esto seguro?")["intent"], "trust")

    def test_intent_trust_data_source(self):
        self.assertEqual(_intent("¿de dónde sacaste mi número?")["intent"], "trust")

    def test_intent_objection_provider(self):
        self.assertEqual(_intent("ya tenemos proveedor para esto")["intent"], "objection")

    def test_intent_objection_price(self):
        self.assertEqual(_intent("nos parece muy caro")["intent"], "objection")

    def test_intent_info_request(self):
        self.assertEqual(_intent("mándame más info")["intent"], "info")

    def test_intent_pricing(self):
        self.assertEqual(_intent("¿cuánto cuesta el servicio?")["intent"], "pricing")

    def test_intent_explain(self):
        self.assertEqual(_intent("¿cómo funciona esto?")["intent"], "explain")

    def test_intent_meeting(self):
        self.assertEqual(_intent("¿podemos agendar una llamada?")["intent"], "meeting")

    def test_intent_accept_simple(self):
        self.assertEqual(_intent("dale")["intent"], "accept")


class AcceptEdgeCaseTest(unittest.TestCase):
    """'accept' is the most edge-case-prone intent: short, caps, tildes, emojis."""

    def test_intent_accept_with_caps(self):
        self.assertEqual(_intent("DALE")["intent"], "accept")

    def test_intent_accept_edge_tildes(self):
        # con tilde ("sí") y sin ella ("dale") deben dar lo mismo
        self.assertEqual(_intent("Sí, dale")["intent"], "accept")

    def test_intent_accept_edge_short_msg(self):
        self.assertEqual(_intent("ok")["intent"], "accept")

    def test_intent_accept_edge_emoji(self):
        self.assertEqual(_intent("dale 👍")["intent"], "accept")
        self.assertEqual(_intent("sí👍")["intent"], "accept")

    def test_intent_accept_vale(self):
        # 'vale' como muletilla chilena de "ok"
        self.assertEqual(_intent("vale, perfecto")["intent"], "accept")


class OptoutEdgeCaseTest(unittest.TestCase):
    """'optout' must close the door even when the 'no' is decorated or shouted."""

    def test_intent_optout_caps(self):
        self.assertEqual(_intent("NO, GRACIAS")["intent"], "optout")

    def test_intent_optout_elongated(self):
        self.assertEqual(_intent("nooo")["intent"], "optout")
        self.assertEqual(_intent("NO!!")["intent"], "optout")

    def test_intent_negated_interest_beats_meeting(self):
        # 'interesa' es keyword de meeting, pero "no me interesa" sigue siendo optout
        self.assertEqual(_intent("no me interesa, dejen de escribir")["intent"], "optout")


class AmbiguousMessageTest(unittest.TestCase):
    """Messages with no clear signal fall back to 'general' — never a false positive."""

    def test_lone_channel_choice_is_general(self):
        # "por acá" solo, sin oferta previa, es ambiguo — no es 'info' ni 'accept'
        self.assertNotIn(_intent("por acá")["intent"], ("info", "accept"))

    def test_bare_greeting_is_general(self):
        self.assertEqual(_intent("hola")["intent"], "general")

    def test_uncertainty_is_not_accept(self):
        # arranca con 'bueno' (palabra afirmativa) pero el "no" descarta 'accept'
        self.assertNotEqual(_intent("bueno, no estoy seguro")["intent"], "accept")


class ActivityContextTest(unittest.TestCase):
    """Activity field must be used over icp.industry to avoid confusing lead sector.

    Bug (2026-08-21): with icp.industry='empresas de mudanzas' and an unknown lead,
    the agent said "ayudamos a empresas de mudanzas como la tuya" — invented context.

    Fix: if lead.activity exists, use it; if not, speak in general.
    Never "empresas como la tuya" without knowing what they actually do.
    """

    def test_without_activity_no_icp_industry_mention(self):
        """Lead with no activity: don't mention icp.industry as if it were the lead's sector."""
        c = build_agents(mock=True)["CONCIERGE"]
        task = TaskPayload(
            agent="CONCIERGE",
            client_id="acme",
            client_tier="GROWTH",
            instructions="x",
            data={
                "message": "¿cómo funciona?",
                "lead": {"name": "Carlos", "company": "Acme Corp"},  # no activity
                "icp": {"sells": "leads", "industry": "empresas de mudanzas"}  # industry is BUYER profile, not lead sector
            },
            constraints=Constraints(channels=["whatsapp"])
        )
        result = c.run(task).result
        reply = result["reply"].lower()

        # Must NOT mention "mudanzas" or "empresas como la tuya" when we don't know the lead's sector
        self.assertNotIn("mudanzas", reply)
        self.assertNotIn("empresas como la tuya", reply)
        # Should fall back to generic offer
        self.assertIn("leads", reply)

    def test_with_activity_uses_real_sector(self):
        """Lead with activity: mention their real sector, not the buyer profile."""
        c = build_agents(mock=True)["CONCIERGE"]
        task = TaskPayload(
            agent="CONCIERGE",
            client_id="acme",
            client_tier="GROWTH",
            instructions="x",
            data={
                "message": "¿qué hacen?",
                "lead": {"name": "María", "company": "DistritBuy", "activity": "distribuidora de insumos de aseo"},
                "icp": {"sells": "leads B2B", "industry": "retail"}  # different from activity
            },
            constraints=Constraints(channels=["whatsapp"])
        )
        result = c.run(task).result
        reply = result["reply"].lower()

        # Must mention the lead's actual sector (activity)
        self.assertIn("aseo", reply)  # part of "distribuidora de insumos de aseo"
        # Should NOT say "como la tuya" after a sector we're not sure about

    def test_activity_with_sells_both_mentioned(self):
        """When both activity and sells are present, both should appear in context."""
        c = build_agents(mock=True)["CONCIERGE"]
        task = TaskPayload(
            agent="CONCIERGE",
            client_id="acme",
            client_tier="GROWTH",
            instructions="x",
            data={
                "message": "¿cómo funciona?",
                "lead": {"name": "Diego", "company": "TechStart", "activity": "fintech"},
                "icp": {"sells": "leads de clientes con presupuesto"}
            },
            constraints=Constraints(channels=["whatsapp"])
        )
        result = c.run(task).result
        reply = result["reply"].lower()
        intent = result["intent"]

        # Should trigger 'explain' intent when asked how it works
        self.assertEqual(intent, "explain")
        # Both activity and sells should be referenced
        self.assertIn("fintech", reply)
        self.assertIn("leads", reply)


if __name__ == "__main__":
    unittest.main()
