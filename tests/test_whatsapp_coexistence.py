"""Coexistencia Meta + WhatsApp Web: un mensaje se procesa una sola vez.

El número de PoolEdge (+56 9 6453 7891) vive en la WABA y en WhatsApp Web a la
vez, así que Meta entrega por /api/webhooks/whatsapp lo mismo que el puente ya
encoló. Medido en vivo (2026-10-26): dos procesadores guardando la memoria
compartida al mismo tiempo borraban turnos y dejaban pasos sin respuesta.
"""
import asyncio
import json
import os
import unittest
from unittest import mock

from fastapi import BackgroundTasks

import api
from zero.client_integrations import secret_key
from zero.memory import SessionMemory
from zero.whatsapp_inbound import drop_web_served, parse_inbound


def _meta_payload(display: str) -> dict:
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "pid-1", "display_phone_number": display},
        "messages": [{"from": "56911112222", "type": "text", "text": {"body": "hola"}}],
    }}]}]}


class CoexistenceTest(unittest.TestCase):
    def test_parser_keeps_the_receiving_number_as_digits(self):
        msgs = parse_inbound(_meta_payload("+56 9 6453 7891"))
        self.assertEqual(msgs[0]["to_number"], "56964537891")

    def test_only_copies_to_a_web_number_are_dropped(self):
        msgs = [{"from": "a", "to_number": "56964537891"},
                {"from": "b", "to_number": "56900000000"},
                {"from": "c"}]
        kept = drop_web_served(msgs, {"56964537891"})
        self.assertEqual([m["from"] for m in kept], ["b", "c"])

    def _webhook(self, display: str, provider: str):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        memory.register_client("zeroai", "STARTER")
        memory.set_client_agent_profile("losetaschile", {"whatsapp_number": "+56964537891"})
        raw = json.dumps(_meta_payload(display)).encode()

        class Request:
            headers = {"x-hub-signature-256": "sha256=x"}
            async def body(self):
                return raw

        env = {"WHATSAPP_PROVIDER": "meta",
               secret_key("losetaschile", "WHATSAPP_PROVIDER"): provider,
               secret_key("zeroai", "WHATSAPP_PHONE_ID"): "pid-1",
               secret_key("zeroai", "WHATSAPP_APP_SECRET"): "s"}
        tasks = BackgroundTasks()
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(api, "make_memory", return_value=memory), \
             mock.patch("zero.whatsapp_inbound.verify_meta_signature", return_value=True):
            result = asyncio.run(api.whatsapp_inbound(Request(), tasks))
        return result, tasks

    def test_meta_copy_of_the_web_number_is_not_processed(self):
        result, tasks = self._webhook("+56 9 6453 7891", provider="web")
        self.assertEqual(result["received"], 0)
        self.assertEqual(tasks.tasks, [])

    def test_meta_number_not_served_by_web_still_processes(self):
        result, tasks = self._webhook("+56 9 0000 0000", provider="web")
        self.assertEqual(result["received"], 1)
        self.assertEqual(len(tasks.tasks), 1)

    def test_same_number_back_on_meta_processes_again(self):
        result, _ = self._webhook("+56 9 6453 7891", provider="meta")
        self.assertEqual(result["received"], 1)


if __name__ == "__main__":
    unittest.main()
