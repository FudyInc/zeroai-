"""Las credenciales y los datos de un negocio no pasan al siguiente."""
import os
import asyncio
import json
import unittest
from unittest import mock

from fastapi import BackgroundTasks, HTTPException

import api
from zero.channels import Outbox
from zero.client_integrations import configured, credentials, secret_key
from zero.crm import CRM
from zero.memory import SessionMemory


class ClientIntegrationIsolationTest(unittest.TestCase):
    def test_no_global_fallback_or_other_client_secret(self):
        losetas = secret_key("losetaschile", "VAPI_API_KEY")
        env = {"VAPI_API_KEY": "global", losetas: "losetas-key"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(credentials("losetaschile", "vapi")["VAPI_API_KEY"], "losetas-key")
            self.assertFalse(configured("Petlabs", "vapi"))
            self.assertNotEqual(secret_key("Petlabs", "VAPI_API_KEY"), losetas)

    def test_live_outbox_never_uses_global_email_for_other_client(self):
        global_sender = mock.Mock()
        box = Outbox({"email": global_sender}, tenant_scope=True, retry_attempts=1)
        with mock.patch.dict(os.environ, {"SMTP_HOST": "smtp.example.com", "SMTP_FROM": "agency@example.com"}):
            result = box.send({"client_id": "Petlabs", "channel": "email", "to": "a@example.com"})
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["via"], "sin_integracion")
        global_sender.send.assert_not_called()

    def test_vapi_route_does_not_call_provider_without_client_key(self):
        memory = mock.Mock(clients={"losetaschile": {}, "Petlabs": {}})
        with mock.patch.object(api, "make_memory", return_value=memory), \
             mock.patch("zero.calls.list_assistants") as provider, \
             mock.patch.dict(os.environ, {secret_key("losetaschile", "VAPI_API_KEY"): "owned"}, clear=True):
            with self.assertRaises(HTTPException) as caught:
                api.assistants("Petlabs")
            self.assertEqual(caught.exception.status_code, 400)
            provider.assert_not_called()

    def test_functions_list_only_selected_client(self):
        memory = mock.Mock(clients={"losetaschile": {}, "Petlabs": {}})
        memory.list_functions.return_value = [
            {"id": "l", "lookup_scope": {"client_id": "losetaschile"}},
            {"id": "p", "lookup_scope": {"client_id": "Petlabs"}},
        ]
        with mock.patch.object(api, "make_memory", return_value=memory):
            self.assertEqual([f["id"] for f in api.list_functions("Petlabs")["functions"]], ["p"])

    def test_lead_search_only_selected_client(self):
        crm = CRM()
        rows = {
            "losetaschile": [{"client_id": "losetaschile", "company": "Mismo", "email": "l@x.cl", "phone": "", "score": 5, "key": "l"}],
            "Petlabs": [{"client_id": "Petlabs", "company": "Mismo", "email": "p@x.cl", "phone": "", "score": 8, "key": "p"}],
        }
        with mock.patch.object(crm, "list", side_effect=lambda c: rows[c]), \
             mock.patch.object(crm, "client_ids", return_value=list(rows)):
            self.assertEqual([r["key"] for r in crm.search("mismo", client_id="Petlabs")], ["p"])

    def test_web_status_rejects_unknown_business_before_bridge(self):
        memory = mock.Mock(clients={"losetaschile": {}})
        with mock.patch.object(api, "make_memory", return_value=memory), \
             mock.patch("zero.whatsapp_web.bridge_request") as bridge:
            with self.assertRaises(HTTPException) as caught:
                api.whatsapp_web_status("Petlabs")
            self.assertEqual(caught.exception.status_code, 404)
            bridge.assert_not_called()

    def test_global_config_cannot_create_shared_business_credential(self):
        with self.assertRaises(HTTPException) as caught:
            api.set_config(api.ConfigBody(vapi_api_key="global-key"))
        self.assertEqual(caught.exception.status_code, 400)

    def test_webhook_accepts_client_web_while_global_provider_is_meta(self):
        memory = SessionMemory(None)
        memory.register_client("petlabs", "STARTER")
        memory.set_client_agent_profile("petlabs", {"whatsapp_number": "56922222222"})
        payload = {"id": "evt-1", "from": "56933333333", "to_phone_id": "56922222222",
                   "text": "Hola", "chat_id": "56933333333@c.us"}

        class Request:
            headers = {"x-zero-signature": "sha256=test"}
            async def body(self):
                return json.dumps(payload).encode()

        env = {"WHATSAPP_PROVIDER": "meta", secret_key("petlabs", "WHATSAPP_PROVIDER"): "web"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(api, "make_memory", return_value=memory), \
             mock.patch("zero.whatsapp_web._client_ports", return_value={"petlabs": 8811}), \
             mock.patch("zero.whatsapp_web.verify_signature", return_value=True), \
             mock.patch("zero.whatsapp_web.claim_event", return_value=True) as claim:
            result = asyncio.run(api.whatsapp_web_inbound(Request(), BackgroundTasks()))
        self.assertEqual(result["received"], 1)
        self.assertEqual(claim.call_args.args[1]["to_phone_id"], "56922222222")


if __name__ == "__main__":
    unittest.main()
