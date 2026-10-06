"""El WhatsApp de una empresa no debe ofrecer datos ni totales de otra."""
from __future__ import annotations

import json
import unittest
import os
from tempfile import TemporaryDirectory
from pathlib import Path

from zero.agents import build_agents
from zero.channels import Outbox
from zero.crm import CRM
from zero.memory import SessionMemory
from zero.orchestrator import Zero
from zero.quotes import normalize_pricing
from zero.whatsapp_inbound import parse_inbound as parse_meta


class CompanyContextTest(unittest.TestCase):
    def setUp(self):
        self.memory = SessionMemory(None)
        self.crm = CRM(None)
        self.zero = Zero(build_agents(mock=True), memory=self.memory, crm=self.crm)
        self.memory.set_client_icp("pooledge", {"sells": "bordes de piscina"})

    def test_pending_offer_uses_the_clients_business(self):
        self.crm.upsert("pooledge", {"phone": "+56912345678", "company": "Comprador"})
        first = self.zero.handle_inbound("+56912345678", "mándame más información")
        self.assertEqual(first["intent"], "info")
        accepted = self.zero.handle_inbound("+56912345678", "sí, por acá")
        self.assertEqual(accepted["intent"], "fulfill")
        self.assertIn("bordes de piscina", accepted["reply"])
        self.assertNotIn("leads B2B", accepted["reply"])
        self.assertNotIn("ZeroAI", accepted["reply"])
        self.assertIn("No tengo ejemplos confirmados", accepted["reply"])

    def test_pooledge_does_not_send_product_total_without_shipping_review(self):
        self.memory.set_client_pricing("pooledge", normalize_pricing({
            "currency": "CLP", "iva_rate": 0.19,
            "items": [{"id": "borde-recto", "name": "borde recto",
                       "unit_price": 12000}],
        }))
        result = self.zero.converse_result("pooledge", "precio de dos borde recto")
        self.assertNotIn("quote", result)
        self.assertNotIn("$", result["reply"])
        self.assertNotIn("Presupuesto", result["reply"])

    def test_pooledge_quote_request_does_not_reach_a_real_model(self):
        class BadBackend:
            calls = 0

            def complete(self, *args):
                self.calls += 1
                return '{"result":{"reply":"Total final: $120.000","intent":"pricing"}}'

        backend = BadBackend()
        live = Zero(build_agents(backend=backend, mock=False), memory=self.memory)
        result = live.converse_result("pooledge", "¿cuánto cuesta?")
        self.assertEqual(backend.calls, 0)
        self.assertEqual(result["intent"], "pricing")
        self.assertNotIn("$", result["reply"])

    def test_other_clients_keep_their_existing_catalog_quote(self):
        self.memory.set_client_pricing("acme", normalize_pricing({
            "currency": "CLP", "iva_rate": 0.19,
            "items": [{"id": "sitio-web", "name": "sitio web",
                       "unit_price": 12000}],
        }))
        result = self.zero.converse_result("acme", "precio de dos sitio web")
        self.assertEqual(result["quote"]["lines"][0]["qty"], 2)
        self.assertIn("$", result["reply"])

    def test_same_phone_in_two_companies_uses_the_number_received(self):
        self.memory.upsert_vendor({"id": "pool", "name": "Paula", "tone": "cercana",
                                   "whatsapp_phone_id": "pool-number"})
        self.memory.set_client_vendor("pooledge", "pool")
        self.crm.upsert("zeroai", {"phone": "+56911112222", "name": "Nombre ZeroAI"})
        self.crm.upsert("pooledge", {"phone": "+56911112222", "name": "Nombre PoolEdge"})
        result = self.zero.handle_inbound("56911112222", "hola", to_phone_id="pool-number")
        self.assertTrue(result["matched"])
        self.assertIn("Nombre PoolEdge", result["reply"])
        self.assertNotIn("Nombre ZeroAI", result["reply"])
        self.assertEqual(self.crm.get("zeroai", "+56911112222")["stage"], "new")
        self.assertEqual(self.crm.get("pooledge", "+56911112222")["stage"], "replied")

    def test_number_owned_by_vendor_without_client_does_not_use_zeroai(self):
        self.memory.upsert_vendor({"id": "unassigned", "name": "Sin empresa",
                                   "whatsapp_phone_id": "unassigned-number"})
        result = self.zero.handle_inbound("56911112222", "hola",
                                          to_phone_id="unassigned-number")
        self.assertFalse(result["matched"])
        self.assertIsNone(self.crm.find_by_contact(phone="56911112222"))

    def test_meta_global_number_uses_default_with_multiple_vendors(self):
        self.memory.register_client("zeroai", "GROWTH")
        self.memory.upsert_vendor({"id": "pool", "name": "Paula"})
        self.memory.set_client_vendor("pooledge", "pool")
        previous = os.environ.get("WHATSAPP_PHONE_ID")
        os.environ["WHATSAPP_PHONE_ID"] = "global-meta-number"
        try:
            result = self.zero.handle_inbound("56911112222", "hola",
                                              to_phone_id="global-meta-number")
        finally:
            if previous is None:
                os.environ.pop("WHATSAPP_PHONE_ID", None)
            else:
                os.environ["WHATSAPP_PHONE_ID"] = previous
        self.assertTrue(result["matched"])
        self.assertIsNotNone(self.crm.find_by_contact(phone="56911112222", client_id="zeroai"))
        self.assertIsNone(self.crm.find_by_contact(phone="56911112222", client_id="pooledge"))

    def test_meta_global_number_uses_unique_existing_company_contact(self):
        self.memory.upsert_vendor({"id": "pool", "name": "Paula"})
        self.memory.set_client_vendor("pooledge", "pool")
        self.crm.upsert("pooledge", {"phone": "56911112222", "name": "Nombre PoolEdge"})
        previous = os.environ.get("WHATSAPP_PHONE_ID")
        os.environ["WHATSAPP_PHONE_ID"] = "global-meta-number"
        try:
            result = self.zero.handle_inbound("56911112222", "hola",
                                              to_phone_id="global-meta-number")
        finally:
            if previous is None:
                os.environ.pop("WHATSAPP_PHONE_ID", None)
            else:
                os.environ["WHATSAPP_PHONE_ID"] = previous
        self.assertTrue(result["matched"])
        self.assertIn("Nombre PoolEdge", result["reply"])
        self.assertIsNone(self.crm.find_by_contact(phone="56911112222", client_id="zeroai"))

    def test_meta_global_number_uses_only_configured_company(self):
        self.crm.upsert("pooledge", {"phone": "56911112222", "name": "Nombre PoolEdge"})
        previous = os.environ.get("WHATSAPP_PHONE_ID")
        os.environ["WHATSAPP_PHONE_ID"] = "global-meta-number"
        try:
            result = self.zero.handle_inbound("56911112222", "hola",
                                              to_phone_id="global-meta-number")
        finally:
            if previous is None:
                os.environ.pop("WHATSAPP_PHONE_ID", None)
            else:
                os.environ["WHATSAPP_PHONE_ID"] = previous
        self.assertTrue(result["matched"])
        self.assertIn("Nombre PoolEdge", result["reply"])
        self.assertIsNone(self.crm.find_by_contact(phone="56911112222", client_id="zeroai"))

    def test_meta_global_number_does_not_route_to_dedicated_company(self):
        self.memory.register_client("zeroai", "GROWTH")
        self.memory.upsert_vendor({"id": "pool", "name": "Paula",
                                   "whatsapp_phone_id": "dedicated-pool-number"})
        self.memory.set_client_vendor("pooledge", "pool")
        self.crm.upsert("pooledge", {"phone": "56911112222", "name": "Nombre PoolEdge"})
        previous = os.environ.get("WHATSAPP_PHONE_ID")
        os.environ["WHATSAPP_PHONE_ID"] = "global-meta-number"
        try:
            result = self.zero.handle_inbound("56911112222", "hola",
                                              to_phone_id="global-meta-number")
        finally:
            if previous is None:
                os.environ.pop("WHATSAPP_PHONE_ID", None)
            else:
                os.environ["WHATSAPP_PHONE_ID"] = previous
        self.assertTrue(result["matched"])
        self.assertNotIn("Nombre PoolEdge", result["reply"])
        self.assertEqual(self.crm.get("pooledge", "56911112222")["stage"], "new")
        self.assertIsNotNone(self.crm.find_by_contact(phone="56911112222", client_id="zeroai"))

    def test_meta_global_number_rejects_contact_in_multiple_companies(self):
        self.memory.register_client("zeroai", "GROWTH")
        self.memory.upsert_vendor({"id": "pool", "name": "Paula"})
        self.memory.set_client_vendor("pooledge", "pool")
        self.crm.upsert("zeroai", {"phone": "56911112222"})
        self.crm.upsert("pooledge", {"phone": "56911112222"})
        previous = os.environ.get("WHATSAPP_PHONE_ID")
        os.environ["WHATSAPP_PHONE_ID"] = "global-meta-number"
        try:
            result = self.zero.handle_inbound("56911112222", "hola",
                                              to_phone_id="global-meta-number")
        finally:
            if previous is None:
                os.environ.pop("WHATSAPP_PHONE_ID", None)
            else:
                os.environ["WHATSAPP_PHONE_ID"] = previous
        self.assertFalse(result["matched"])
        self.assertEqual(self.crm.get("zeroai", "56911112222")["stage"], "new")
        self.assertEqual(self.crm.get("pooledge", "56911112222")["stage"], "new")

    def test_shared_recipient_uses_unique_existing_company_contact(self):
        self.memory.upsert_vendor({"id": "shared", "name": "Paula",
                                   "whatsapp_phone_id": "shared-number"})
        self.memory.set_client_vendor("zeroai", "shared")
        self.memory.set_client_vendor("pooledge", "shared")
        self.crm.upsert("pooledge", {"phone": "56911112222", "name": "Nombre PoolEdge"})
        result = self.zero.handle_inbound("56911112222", "hola",
                                          to_phone_id="shared-number")
        self.assertTrue(result["matched"])
        self.assertIn("Nombre PoolEdge", result["reply"])
        self.assertIsNone(self.crm.find_by_contact(phone="56911112222", client_id="zeroai"))

    def test_shared_recipient_rejects_contact_in_multiple_companies(self):
        self.memory.upsert_vendor({"id": "shared", "name": "Paula",
                                   "whatsapp_phone_id": "shared-number"})
        self.memory.set_client_vendor("zeroai", "shared")
        self.memory.set_client_vendor("pooledge", "shared")
        self.crm.upsert("zeroai", {"phone": "56911112222"})
        self.crm.upsert("pooledge", {"phone": "56911112222"})
        result = self.zero.handle_inbound("56911112222", "hola",
                                          to_phone_id="shared-number")
        self.assertFalse(result["matched"])
        self.assertEqual(self.crm.get("zeroai", "56911112222")["stage"], "new")
        self.assertEqual(self.crm.get("pooledge", "56911112222")["stage"], "new")

    def test_meta_extracts_profile_name_when_available(self):
        meta = {"entry": [{"changes": [{"value": {
            "metadata": {"phone_number_id": "pool-number"},
            "contacts": [{"wa_id": "56911112222", "profile": {"name": "Ana Pérez"}}],
            "messages": [{"from": "56911112222", "type": "text",
                          "text": {"body": "Hola"}}],
        }}]}]}
        self.assertEqual(parse_meta(meta)[0]["profile_name"], "Ana Pérez")

    def test_profile_name_and_history_survive_a_second_message_and_restart(self):
        with TemporaryDirectory() as tmp:
            state, leads = str(Path(tmp) / "state.json"), str(Path(tmp) / "crm.json")
            memory, crm = SessionMemory(state), CRM(leads)
            first = Zero(build_agents(mock=True), memory=memory, crm=crm)
            greeting = first.handle_inbound("56911112222", "hola", profile_name="Ana Pérez")
            self.assertIn("Ana Pérez", greeting["reply"])
            second = Zero(build_agents(mock=True), memory=SessionMemory(state), crm=CRM(leads))
            concierge = second.agents["CONCIERGE"]
            original_run = concierge.run
            seen = []

            def capture(task):
                seen.append(task.data)
                return original_run(task)

            concierge.run = capture
            followup = second.handle_inbound("56911112222", "¿qué hacen?", profile_name="Otro Nombre")
            self.assertEqual(seen[-1]["lead"]["name"], "Ana Pérez")
            self.assertEqual([turn["role"] for turn in seen[-1]["history"]],
                             ["lead", "agent"])
            self.assertEqual(seen[-1]["history"][0]["text"], "hola")
            self.assertNotIn("Hola", followup["reply"])
            self.assertNotIn("Estimado/a", followup["reply"])

    def test_unknown_name_uses_respectful_address(self):
        result = self.zero.handle_inbound("56911112222", "hola")
        self.assertTrue(result["reply"].startswith("Estimado/a,"))

    def test_real_backend_receives_saved_name_and_previous_turns(self):
        class CapturingBackend:
            data = None

            def complete(self, system, task_json, model):
                self.data = json.loads(task_json)["data"]
                return '{"reply":"Claro, seguimos con tu consulta.","intent":"general"}'

        with TemporaryDirectory() as tmp:
            state, leads = str(Path(tmp) / "state.json"), str(Path(tmp) / "crm.json")
            first = Zero(build_agents(mock=True), memory=SessionMemory(state), crm=CRM(leads))
            first.handle_inbound("56911112222", "hola", profile_name="Ana Pérez")
            backend = CapturingBackend()
            second = Zero(build_agents(backend=backend, mock=False),
                          memory=SessionMemory(state), crm=CRM(leads))
            second.handle_inbound("56911112222", "quiero retomar")
            self.assertEqual(backend.data["lead"]["name"], "Ana Pérez")
            self.assertEqual(backend.data["message"], "quiero retomar")
            self.assertEqual([turn["role"] for turn in backend.data["history"]],
                             ["lead", "agent"])

    def test_failed_send_does_not_enter_conversation_as_agent_turn(self):
        self.memory.register_client("zeroai", "GROWTH")
        class FailedOutbox(Outbox):
            def send(self, msg, wa_creds=None):
                return {"channel": msg["channel"], "to": msg["to"],
                        "status": "error", "via": "whatsapp", "error": "sin conexión"}

        failed = Zero(build_agents(mock=True), memory=self.memory,
                      crm=self.crm, outbox=FailedOutbox())
        result = failed.handle_inbound("56911112222", "mándame más información")
        self.assertEqual(result["reply"], "")
        rec = self.crm.find_by_contact(phone="56911112222")
        turns = self.memory.get_conversation("zeroai", rec["key"])
        self.assertEqual([t["role"] for t in turns], ["lead"])
        self.assertIsNone(self.memory.get_pending_offer("zeroai", rec["key"]))

    def test_failed_pending_offer_remains_pending(self):
        class FailedOutbox(Outbox):
            def send(self, msg, wa_creds=None):
                return {"channel": msg["channel"], "to": msg["to"],
                        "status": "error", "via": "whatsapp", "error": "sin conexión"}

        self.crm.upsert("pooledge", {"phone": "56911112222", "name": "Ana"})
        self.memory.set_pending_offer("pooledge", "56911112222", "info")
        failed = Zero(build_agents(mock=True), memory=self.memory,
                      crm=self.crm, outbox=FailedOutbox())
        result = failed.handle_inbound("56911112222", "sí, por acá")
        self.assertEqual(result["intent"], "fulfill_failed")
        self.assertIsNotNone(self.memory.get_pending_offer("pooledge", "56911112222"))
        self.assertEqual([t["role"] for t in self.memory.get_conversation(
            "pooledge", "56911112222")], ["lead"])


if __name__ == "__main__":
    unittest.main()
