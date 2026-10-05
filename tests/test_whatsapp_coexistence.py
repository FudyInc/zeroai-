import json
import tempfile
import unittest
from pathlib import Path

from zero.whatsapp_coexistence import archive_events
from zero.whatsapp_inbound import parse_inbound


class CoexistenceWebhookTest(unittest.TestCase):
    def test_archive_one_time_sync_and_app_echo_without_replying(self):
        payload = {"entry": [{"id": "waba-1", "changes": [
            {"field": "history", "value": {"history": [{"messages": [{"text": "anterior"}]}]}},
            {"field": "smb_message_echoes", "value": {"message_echoes": [
                {"from": "business", "to": "lead", "text": {"body": "respuesta humana"}}]}},
            {"field": "messages", "value": {"metadata": {"phone_number_id": "phone-1"},
                                           "messages": [{"from": "lead", "type": "text",
                                                         "text": {"body": "hola"}}]}},
        ]}]}
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "events.jsonl"
            self.assertEqual(archive_events(payload, str(target)), 2)
            records = [json.loads(line) for line in target.read_text().splitlines()]
            self.assertEqual([r["field"] for r in records], ["history", "smb_message_echoes"])
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(parse_inbound(payload), [
            {"from": "lead", "text": "hola", "to_phone_id": "phone-1"}])

    def test_malformed_or_unrelated_events_do_not_create_archive(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "events.jsonl"
            self.assertEqual(archive_events({"entry": "bad"}, str(target)), 0)
            self.assertEqual(archive_events({"entry": [{"changes": "bad"}]}, str(target)), 0)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
