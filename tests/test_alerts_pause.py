import os
import unittest
from unittest import mock

from zero.alerts import notify_owner, reset_throttle


class AlertPauseTest(unittest.TestCase):
    def test_owner_whatsapp_pause_keeps_email_alerts(self):
        outbox = mock.Mock()
        outbox.send.return_value = {"status": "sent"}
        with mock.patch.dict(os.environ, {
            "OWNER_WHATSAPP_TO": "56911111111",
            "OWNER_WHATSAPP_PAUSED": "1",
            "OWNER_EMAIL_TO": "owner@example.com",
        }):
            reset_throttle()
            result = notify_owner("aviso", kind="pause-test", outbox=outbox)
        self.assertEqual(result["via"], "email")
        outbox.send.assert_called_once_with({
            "channel": "email", "to": "owner@example.com",
            "body": "aviso", "subject": "ZeroAI — aviso del sistema",
        })


if __name__ == "__main__":
    unittest.main()
