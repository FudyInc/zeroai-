"""Respuesta escrita en la bandeja del panel (WhatsApp Web).

Lo que se fija:
- en un chat @lid el id no es el teléfono: se usa el "phone" que devuelve el
  puente para encontrar el lead y guardar el turno en el historial del agente;
- un envío sin confirmación (202 del puente) no se guarda como dicho;
- en un chat @c.us se sigue usando el número del id.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from zero.crm import CRM
from zero.memory import SessionMemory

LID = "111111111111111@lid"
PHONE = "56933333333"


class InboxReplyTest(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.memory = SessionMemory(str(Path(tmp.name) / "state.json"))
        self.memory.register_client("losetaschile", "STARTER")
        self.crm = CRM(None)
        self.key = self.crm.upsert("losetaschile", {"phone": PHONE, "source": "test"})["key"]

    def reply(self, chat_id, bridge_result, text="Hola, te escribo por tu pedido"):
        import api
        calls = []

        def inbox(path, body=None, client=None):
            calls.append((path, body))
            if path == "/chats":
                return {"chats": [{"id": chat_id}]}
            return bridge_result

        with mock.patch.object(api, "_whatsapp_web_inbox_request", side_effect=inbox), \
             mock.patch.object(api, "make_memory", return_value=self.memory), \
             mock.patch.object(api, "make_crm", return_value=self.crm), \
             mock.patch.object(self.memory, "save"), mock.patch.object(self.crm, "save"):
            out = api.whatsapp_web_reply(chat_id, api.WhatsAppWebReply(text=text),
                                         client="losetaschile")
        return out, calls

    def agent_turns(self):
        return [t["text"] for t in self.memory.get_conversation("losetaschile", self.key)
                if t["role"] == "agent"]

    def test_lid_chat_uses_the_phone_from_the_bridge(self):
        out, calls = self.reply(LID, {"message": {"id": "x"}, "confirmed": True, "phone": PHONE})
        self.assertTrue(out["confirmed"])
        self.assertEqual(self.agent_turns(), ["Hola, te escribo por tu pedido"])
        self.assertIsNotNone(self.memory.get_whatsapp_handoff("losetaschile", LID))
        self.assertEqual(len(calls), 2)   # lista de chats y un solo envío

    def test_unconfirmed_send_is_not_stored(self):
        out, _ = self.reply(LID, {"message": None, "confirmed": False, "phone": PHONE,
                                  "warning": "revisa el chat"})
        self.assertFalse(out["confirmed"])
        self.assertEqual(self.agent_turns(), [])
        # El chat igual queda con el equipo: el mensaje pudo haber salido.
        self.assertIsNotNone(self.memory.get_whatsapp_handoff("losetaschile", LID))

    def test_lid_chat_without_phone_stores_nothing(self):
        self.reply(LID, {"message": {"id": "x"}, "confirmed": True, "phone": None})
        self.assertEqual(self.agent_turns(), [])

    def test_cus_chat_keeps_using_the_id(self):
        self.reply(PHONE + "@c.us", {"message": {"id": "x"}, "confirmed": True, "phone": None})
        self.assertEqual(self.agent_turns(), ["Hola, te escribo por tu pedido"])


if __name__ == "__main__":
    unittest.main()
