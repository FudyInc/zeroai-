import unittest
from unittest.mock import patch

import api


class WonKpisTest(unittest.TestCase):
    def test_won_stage_does_not_assign_a_sale_amount(self):
        with patch.object(api, "make_memory") as memory, patch.object(api, "_crm") as crm:
            memory.return_value.clients = {"negocio": {}}
            crm.return_value.counts.return_value = {"won": 1, "new": 3}
            result = api.kpis("negocio")
        self.assertEqual(result["won"], 1)
        self.assertIsNone(result["pipeline_clp"])
