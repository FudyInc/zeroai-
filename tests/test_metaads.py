"""Tests de la ruta REAL de zero/metaads.py (Meta Graph API).

MockMetaAds ya está cubierto en tests/test_core.py::MetaAdsTest. Este archivo
cubre `MetaAds`, `_graph` y `list_ad_accounts` — hasta ahora sin ningún test —
mockeando urllib.request.urlopen. Foco: que una respuesta de Graph con forma
inesperada (no-JSON, no-dict, "data" que no es lista, items que no son dict)
nunca reviente con AttributeError/TypeError, sino que degrade a [] o lance un
RuntimeError con mensaje claro, igual que ya se hizo en zero/calls.py.
"""
import json
import os
import unittest
import urllib.error
from unittest import mock

from zero import metaads


def _resp(body: str):
    cm = mock.MagicMock()
    cm.__enter__.return_value.read.return_value = body.encode("utf-8")
    cm.__exit__.return_value = False
    return cm


class MetaAdsCampaignsTest(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"META_ADS_TOKEN": "tok"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_campaigns_ok_mapea(self):
        body = json.dumps({"data": [
            {"id": "1", "name": "Camp A", "objective": "OUTCOME_LEADS",
             "effective_status": "ACTIVE", "daily_budget": "5000"},
        ]})
        with mock.patch("zero.metaads.urllib.request.urlopen", return_value=_resp(body)):
            out = metaads.MetaAds("act_1").campaigns("acme")
            self.assertEqual(out[0]["id"], "1")
            self.assertEqual(out[0]["status"], "active")
            self.assertEqual(out[0]["budget_clp"], 5000)

    def test_campaigns_respuesta_no_json_lanza_runtime_error(self):
        with mock.patch("zero.metaads.urllib.request.urlopen", return_value=_resp("<html>error</html>")):
            with self.assertRaises(RuntimeError) as cm:
                metaads.MetaAds("act_1").campaigns("acme")
            self.assertIn("no-JSON", str(cm.exception))

    def test_campaigns_data_no_es_lista_no_revienta(self):
        body = json.dumps({"data": "oops"})
        with mock.patch("zero.metaads.urllib.request.urlopen", return_value=_resp(body)):
            self.assertEqual(metaads.MetaAds("act_1").campaigns("acme"), [])

    def test_campaigns_ignora_items_no_dict(self):
        body = json.dumps({"data": ["oops", {"id": "1", "name": "Camp A"}]})
        with mock.patch("zero.metaads.urllib.request.urlopen", return_value=_resp(body)):
            out = metaads.MetaAds("act_1").campaigns("acme")
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["id"], "1")

    def test_campaigns_top_level_no_es_dict_no_revienta(self):
        body = json.dumps(["oops"])
        with mock.patch("zero.metaads.urllib.request.urlopen", return_value=_resp(body)):
            self.assertEqual(metaads.MetaAds("act_1").campaigns("acme"), [])

    def test_campaigns_http_error_lanza_con_detalle(self):
        err = urllib.error.HTTPError("url", 401, "no autorizado", {}, mock.Mock())
        err.read = mock.Mock(return_value=b'{"error":{"message":"token vencido"}}')
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as cm:
                metaads.MetaAds("act_1").campaigns("acme")
            self.assertIn("401", str(cm.exception))

    def test_campaigns_url_error_lanza(self):
        with mock.patch("zero.metaads.urllib.request.urlopen",
                        side_effect=urllib.error.URLError("sin red")):
            with self.assertRaises(RuntimeError) as cm:
                metaads.MetaAds("act_1").campaigns("acme")
            self.assertIn("no pude contactar", str(cm.exception))

    def test_lead_ads_requires_page_id(self):
        with self.assertRaisesRegex(RuntimeError, "ID numérico de la página"):
            metaads.MetaAds("act_1").lead_ads("acme")

    def test_lead_ads_reads_only_selected_page_and_maps_contact(self):
        responses = [
            {"data": [{"id": "123", "name": "Consulta"}]},
            {"data": [{"id": "456", "form_id": "123", "campaign_name": "B2B",
                       "field_data": [
                           {"name": "full_name", "values": ["Ana Pérez"]},
                           {"name": "email", "values": ["ana@empresa.cl"]},
                           {"name": "company_name", "values": ["Empresa"]},
                           {"name": "job_title", "values": ["Gerente"]},
                       ]}]},
        ]
        with mock.patch("zero.metaads._graph", side_effect=responses) as graph:
            leads = metaads.MetaAds("act_1").lead_ads("acme", {"page_id": "789"})
        self.assertEqual(graph.call_args_list[0].args[0], "789/leadgen_forms")
        self.assertEqual(graph.call_args_list[1].args[0], "123/leads")
        self.assertEqual(leads[0]["email"], "ana@empresa.cl")
        self.assertEqual(leads[0]["company"], "Empresa")
        self.assertEqual(leads[0]["meta_lead_id"], "456")

    def test_lead_ads_rejects_partial_meta_response(self):
        with mock.patch("zero.metaads._graph", return_value={"data": None}):
            with self.assertRaisesRegex(RuntimeError, "lista de formularios"):
                metaads.MetaAds("act_1").lead_ads("acme", {"page_id": "789"})

    def test_lead_ads_rejects_broken_pagination(self):
        response = {"data": [{"id": "123"}], "paging": {"next": "another-page"}}
        with mock.patch("zero.metaads._graph", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "sin cursor"):
                metaads.MetaAds("act_1").lead_ads("acme", {"page_id": "789"})

    def test_lead_ads_rejects_malformed_paging(self):
        response = {"data": [{"id": "123"}], "paging": "invalid"}
        with mock.patch("zero.metaads._graph", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "paginación inválida"):
                metaads.MetaAds("act_1").lead_ads("acme", {"page_id": "789"})

    def test_lead_ads_rejects_lead_from_another_form(self):
        responses = [
            {"data": [{"id": "123"}]},
            {"data": [{"id": "456", "form_id": "999", "field_data": [
                {"name": "email", "values": ["ana@empresa.cl"]}]}]},
        ]
        with mock.patch("zero.metaads._graph", side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, "otro formulario"):
                metaads.MetaAds("act_1").lead_ads("acme", {"page_id": "789"})


class GraphHelpersTest(unittest.TestCase):
    def test_graph_respuesta_no_dict_lanza(self):
        with mock.patch("zero.metaads.urllib.request.urlopen", return_value=_resp("[1,2,3]")):
            with self.assertRaises(RuntimeError) as cm:
                metaads._graph("me/adaccounts", "tok")
            self.assertIn("forma de respuesta", str(cm.exception))

    def test_list_ad_accounts_mapea(self):
        body = json.dumps({"data": [{"id": "act_1", "name": "Cuenta 1", "account_status": 1}]})
        with mock.patch("zero.metaads.urllib.request.urlopen", return_value=_resp(body)):
            out = metaads.list_ad_accounts("tok")
            self.assertEqual(out[0]["id"], "act_1")

    def test_list_ad_accounts_data_no_lista_no_revienta(self):
        body = json.dumps({"data": None})
        with mock.patch("zero.metaads.urllib.request.urlopen", return_value=_resp(body)):
            self.assertEqual(metaads.list_ad_accounts("tok"), [])


class MakeMetaAdsRealTest(unittest.TestCase):
    def test_con_token_y_cuenta_usa_real(self):
        env = {"META_ADS_TOKEN": "tok", "META_AD_ACCOUNT_ID": "123"}
        with mock.patch.dict(os.environ, env):
            inst = metaads.make_metaads()
            self.assertIsInstance(inst, metaads.MetaAds)
            self.assertEqual(inst.account, "act_123")  # tolera pegar solo el número


if __name__ == "__main__":
    unittest.main()
