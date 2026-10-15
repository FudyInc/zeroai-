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

    def test_lead_ads_paginacion_rota_no_avanza_el_cursor(self):
        # Meta anuncia otra página sin cursor: el formulario cuenta como fallido
        # (no se importa un resultado parcial ni se mueve su cursor).
        respuestas = {
            "1/leads": {"data": [{"id": "9", "created_time": "2026-10-15T10:00:00+0000",
                                  "ad_id": "7", "field_data": [
                                      {"name": "email", "values": ["a@b.cl"]}]}],
                        "paging": {"next": "otra-pagina"}},
            "2/leads": {"data": []},
        }
        with mock.patch("zero.metaads._graph", side_effect=lambda path, *a, **k: respuestas[path]):
            src = metaads.MetaAds("act_1")
            leads = src.lead_ads("acme", {"lead_form_ids": ["1", "2"]},
                                 since={"1": "2026-10-14T10:00:00+0000"})
        self.assertEqual(leads, [])
        self.assertEqual([f["form_id"] for f in src.failed_forms], ["1"])
        self.assertIn("sin cursor", src.failed_forms[0]["error"])
        self.assertNotIn("1", src.cursors)

    def test_lead_ads_cursor_repetido_no_importa_parcial(self):
        pagina = {"data": [], "paging": {"next": "mas", "cursors": {"after": "c1"}}}
        with mock.patch("zero.metaads._graph", return_value=pagina):
            with self.assertRaisesRegex(RuntimeError, "repitió el cursor"):
                metaads.MetaAds("act_1").lead_ads("acme", {"lead_form_ids": ["1"]})

    def test_lead_ads_paginacion_invalida_en_todos_lanza(self):
        with mock.patch("zero.metaads._graph", return_value={"data": [], "paging": "invalida"}):
            with self.assertRaisesRegex(RuntimeError, "paginación inválida"):
                metaads.MetaAds("act_1").lead_ads("acme", {"lead_form_ids": ["1"]})

    def test_lead_ads_lee_solo_formularios_asignados_y_normaliza(self):
        body = json.dumps({"data": [{"id": "lead-1", "ad_id": "ad-1", "ad_name": "Anuncio IG",
                                     "campaign_name": "Seguros", "platform": "ig", "field_data": [
            {"name": "full_name", "values": ["Ana Pérez"]},
            {"name": "phone_number", "values": ["+56912345678"]},
            {"name": "email", "values": ["ANA@EXAMPLE.CL"]},
        ]}]})
        account = json.dumps({"account_id": "1"})
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[_resp(body), _resp(account)]) as fetch:
            leads = metaads.MetaAds("act_1").lead_ads("losetaschile", {"lead_form_ids": ["123"]})
        primera = fetch.call_args_list[0].args[0].full_url
        self.assertEqual(primera.split("?")[0].split("/")[-2:], ["123", "leads"])
        self.assertIn("ad_name%2Ccampaign_name%2Cplatform", primera)
        self.assertEqual(leads[0]["email"], "ana@example.cl")
        self.assertEqual(leads[0]["source"], "meta_ads")
        self.assertEqual(leads[0]["company"], "Ana Pérez")
        self.assertEqual(leads[0]["lead_origin"], {
            "platform": "ig", "form_id": "123", "ad_id": "ad-1", "ad_name": "Anuncio IG",
            "campaign_name": "Seguros", "lead_id": "lead-1"})

    def test_lead_ads_no_importa_anuncios_de_otra_cuenta(self):
        body = json.dumps({"data": [{"id": "lead-1", "ad_id": "ad-1", "field_data": [
            {"name": "email", "values": ["ana@example.cl"]}]}]})
        account = json.dumps({"account_id": "999"})
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[_resp(body), _resp(account)]):
            self.assertEqual(metaads.MetaAds("act_1").lead_ads("losetaschile", {"lead_form_ids": ["123"]}), [])

    def _renta(self, field_data):
        body = json.dumps({"data": [{"id": "l", "ad_id": "ad-1", "field_data": field_data}]})
        account = json.dumps({"account_id": "1"})
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[_resp(body), _resp(account)]):
            return metaads.MetaAds("act_1").lead_ads("c", {"lead_form_ids": ["123"]})[0]["income_range"]

    def test_lead_ads_detecta_la_renta_por_palabra_clave(self):
        self.assertEqual(self._renta([
            {"name": "phone_number", "values": ["+56911111111"]},
            {"name": "otra_pregunta", "values": ["x"]},
            {"name": "cual_es_su_renta_mensual", "values": ["Más de $3.000.000"]}]), "Más de $3.000.000")

    def test_lead_ads_la_unica_pregunta_propia_es_la_renta(self):
        self.assertEqual(self._renta([
            {"name": "phone_number", "values": ["+56911111111"]},
            {"name": "rango", "values": ["$1.000.000 - $2.000.000"]}]), "$1.000.000 - $2.000.000")

    def test_lead_ads_con_varias_preguntas_sin_palabra_clave_no_adivina(self):
        self.assertIsNone(self._renta([
            {"name": "phone_number", "values": ["+56911111111"]},
            {"name": "a", "values": ["1"]}, {"name": "b", "values": ["2"]}]))

    def test_mock_lead_ads_tiene_la_misma_forma_que_el_real(self):
        mock_lead = metaads.MockMetaAds().lead_ads("acme")[0]
        body = json.dumps({"data": [{"id": "l", "ad_id": "ad-1", "field_data": [
            {"name": "email", "values": ["a@b.cl"]}, {"name": "renta", "values": ["3M"]}]}]})
        with mock.patch("zero.metaads.urllib.request.urlopen",
                        side_effect=[_resp(body), _resp(json.dumps({"account_id": "1"}))]):
            real = metaads.MetaAds("act_1").lead_ads("acme", {"lead_form_ids": ["1"]})[0]
        self.assertEqual(set(real) - set(mock_lead), set())
        self.assertEqual(set(real["lead_origin"]), set(mock_lead["lead_origin"]))


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
