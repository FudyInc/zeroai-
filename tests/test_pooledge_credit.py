import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from zero.pooledge_credit import credit_status

class CreditTest(unittest.TestCase):
    record = {"available": 15, "capacity": 20, "at": "2026-11-18T13:32:46+00:00"}
    now = datetime(2026, 11, 18, 15, 10, tzinfo=timezone.utc)

    @patch("zero.pooledge_credit.source", return_value=(None, None))
    def test_missing_credentials_show_manual_balance(self, _):
        self.assertEqual(credit_status(self.record, self.now)["state"], "recorded")
        self.assertEqual(credit_status(None)["state"], "empty")

    @patch("zero.pooledge_credit.source", return_value=("test", "key"))
    @patch("zero.pooledge_credit.cost")
    def test_deduct_and_distinguish_provider_outage(self, cost, _):
        cost.return_value = 7
        self.assertEqual(credit_status(self.record, self.now)["available"], 8)
        cost.return_value = 30
        self.assertEqual(credit_status(self.record, self.now)["available"], 0)
        cost.side_effect = OSError()
        self.assertEqual(credit_status(self.record, self.now)["state"], "unavailable")

    @patch("zero.pooledge_credit.urlopen")
    def test_provider_filter_and_cents_across_partial_hours(self, request):
        import io
        from decimal import Decimal
        from urllib.parse import parse_qs, urlparse
        from zero.pooledge_credit import cost
        payload = b'{"has_more":false,"data":[{"cost":{"amount":"25.5","currency":"USD"}}]}'
        request.side_effect = lambda *args, **kwargs: io.BytesIO(payload)
        spent = cost(self.now.replace(hour=13, minute=33), self.now, "test", "apikey_test")
        self.assertEqual(spent, Decimal("0.765"))
        queries = [parse_qs(urlparse(call.args[0].full_url).query) for call in request.call_args_list]
        self.assertTrue(all(q["api_key_ids[]"] == ["apikey_test"] for q in queries))
        self.assertEqual([q.get("time_bucket_width") for q in queries], [["1m"], None, ["1m"]])
