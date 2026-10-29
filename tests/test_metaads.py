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
import urllib.parse
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
        campaigns = json.dumps({"data": [
            {"id": "1", "name": "Camp A", "objective": "OUTCOME_LEADS",
             "effective_status": "ACTIVE", "daily_budget": "5000"},
        ]})
        insights = json.dumps({"data": [{"campaign_id": "1", "spend": "12500.00", "account_currency": "CLP",
                                         "actions": [{"action_type": "lead", "value": "5"}]}]})
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[_resp(campaigns), _resp(insights)]):
            out = metaads.MetaAds("act_1").campaigns("acme")
            self.assertEqual(out[0]["id"], "1")
            self.assertEqual(out[0]["status"], "active")
            self.assertEqual(out[0]["budget_clp"], 5000)
            self.assertEqual((out[0]["spent_clp"], out[0]["leads"], out[0]["cpl_clp"]), (12500, 5, 2500))

    def test_campaigns_no_muestra_usd_como_clp(self):
        campaigns = json.dumps({"data": [{"id": "1", "name": "Camp A"}]})
        insights = json.dumps({"data": [{"campaign_id": "1", "spend": "50",
                                         "account_currency": "USD"}]})
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[_resp(campaigns), _resp(insights)]):
            with self.assertRaisesRegex(RuntimeError, "no usa CLP"):
                metaads.MetaAds("act_1").campaigns("acme")

    def test_campaigns_sin_insights_verifica_moneda_antes_de_mostrar_presupuesto(self):
        campaigns = json.dumps({"data": [{"id": "1", "name": "Camp A", "daily_budget": "5000"}]})
        empty_insights = json.dumps({"data": []})
        usd_account = json.dumps({"currency": "USD"})
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[
            _resp(campaigns), _resp(empty_insights), _resp(usd_account),
        ]):
            with self.assertRaisesRegex(RuntimeError, "no usa CLP"):
                metaads.MetaAds("act_1").campaigns("acme")

    def test_campaigns_sin_moneda_conocida_no_asume_clp(self):
        campaigns = json.dumps({"data": [{"id": "1", "name": "Camp A", "daily_budget": "5000"}]})
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[
            _resp(campaigns), _resp(json.dumps({"data": []})), _resp(json.dumps({})),
        ]):
            with self.assertRaisesRegex(RuntimeError, "no usa CLP"):
                metaads.MetaAds("act_1").campaigns("acme")

    def test_campaigns_sin_campanas_no_consulta_moneda(self):
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[
            _resp(json.dumps({"data": []})), _resp(json.dumps({"data": []})),
        ]) as urlopen:
            self.assertEqual(metaads.MetaAds("act_1").campaigns("acme"), [])
            self.assertEqual(urlopen.call_count, 2)

    def test_daily_spend_no_muestra_gasto_usd_como_clp(self):
        insights = json.dumps({"data": [{"date_start": "2026-10-13", "spend": "50"}]})
        usd_account = json.dumps({"currency": "USD"})
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[
            _resp(insights), _resp(usd_account),
        ]):
            with self.assertRaisesRegex(RuntimeError, "no usa CLP"):
                metaads.MetaAds("act_1").daily_spend()

    def test_daily_spend_clp_se_muestra(self):
        insights = json.dumps({"data": [{"date_start": "2026-10-13", "spend": "4500"}]})
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[
            _resp(insights), _resp(json.dumps({"currency": "CLP"})),
        ]):
            self.assertEqual(metaads.MetaAds("act_1").daily_spend(),
                             [{"date": "2026-10-13", "spent_clp": 4500}])

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
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[
            _resp(body), _resp(json.dumps({"data": []})), _resp(json.dumps({"currency": "CLP"})),
        ]):
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


class MetaAccountsCheckTest(unittest.TestCase):
    """GET /api/metaads/accounts: además de listar cuentas, diagnostica la asignada."""

    def setUp(self):
        import api
        from zero.memory import SessionMemory
        self.api = api
        self.memory = SessionMemory()
        self.memory.register_client("acme", "GROWTH")
        patches = [
            mock.patch.object(api, "make_memory", return_value=self.memory),
            mock.patch("zero.metaads.client_token", return_value="tok"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _check(self, accounts, assigned="act_1", spend=None):
        self.memory.set_client_meta("acme", {"ad_account": assigned} if assigned else {})
        spend = spend if spend is not None else mock.Mock(return_value=[])
        with mock.patch("zero.metaads.list_ad_accounts", return_value=accounts), \
             mock.patch("zero.metaads.MetaAds.daily_spend", spend):
            return self.api.metaads_accounts("acme")

    def test_cuenta_lista(self):
        out = self._check([{"id": "act_1", "name": "A", "status": 1, "currency": "CLP"}])
        self.assertTrue(out["check"]["ready"])
        self.assertTrue(out["check"]["insights_readable"])
        self.assertEqual(out["accounts"][0]["id"], "act_1")

    def test_sin_cuenta_asignada_no_esta_lista(self):
        out = self._check([{"id": "act_1", "status": 1, "currency": "CLP"}], assigned=None)
        self.assertFalse(out["check"]["ready"])
        self.assertIsNone(out["check"]["assigned_account"])

    def test_token_no_ve_la_cuenta_asignada(self):
        out = self._check([{"id": "act_9", "status": 1, "currency": "CLP"}])
        self.assertFalse(out["check"]["account_found"])
        self.assertFalse(out["check"]["ready"])

    def test_cuenta_inactiva_no_esta_lista(self):
        out = self._check([{"id": "act_1", "status": 2, "currency": "CLP"}])
        self.assertFalse(out["check"]["account_active"])
        self.assertFalse(out["check"]["ready"])

    def test_cuenta_en_usd_reporta_el_motivo(self):
        spend = mock.Mock(side_effect=RuntimeError(metaads._NOT_CLP))
        out = self._check([{"id": "act_1", "status": 1, "currency": "USD"}], spend=spend)
        self.assertFalse(out["check"]["ready"])
        self.assertIn("no usa CLP", out["check"]["error"])

    def test_cuenta_guardada_sin_prefijo_act_se_reconoce(self):
        out = self._check([{"id": "act_1", "status": 1, "currency": "CLP"}], assigned="1")
        self.assertTrue(out["check"]["account_found"])
        self.assertTrue(out["check"]["ready"])

    def test_status_como_texto_cuenta_como_activa(self):
        out = self._check([{"id": "act_1", "status": "1", "currency": "CLP"}])
        self.assertTrue(out["check"]["account_active"])

    def test_error_inesperado_en_insights_no_revienta(self):
        out = self._check([{"id": "act_1", "status": 1, "currency": "CLP"}],
                          spend=mock.Mock(side_effect=ValueError("raro")))
        self.assertFalse(out["check"]["ready"])
        self.assertIn("raro", out["check"]["error"])


_AD_INSIGHTS = json.dumps({"data": [
    {"ad_id": "11", "ad_name": "Post A", "campaign_id": "1", "campaign_name": "Camp A",
     "spend": "12000", "impressions": "4000", "reach": "3000", "clicks": "80", "ctr": "2.0",
     "account_currency": "CLP", "actions": [{"action_type": "lead", "value": "4"}]},
    {"ad_id": "12", "ad_name": "Post B", "campaign_id": "1", "campaign_name": "Camp A",
     "spend": "5000", "impressions": "900", "reach": "800", "clicks": "9", "ctr": "1.0",
     "account_currency": "CLP", "actions": []},
    {"ad_id": "13", "ad_name": "Sin gasto", "spend": "0", "account_currency": "CLP"},
]})
_ADS = json.dumps({"data": [
    {"id": "11", "name": "Post A", "campaign_id": "1", "campaign": {"name": "Camp A"},
     "effective_status": "ACTIVE",
     "creative": {"title": "Pisos para piscina", "body": "Cotiza hoy", "image_url": "https://img/a.jpg",
                  "thumbnail_url": "https://img/a_t.jpg", "call_to_action_type": "LEARN_MORE",
                  "effective_object_story_id": "page_post11"}},
]})


class MetaAdsAdsTest(unittest.TestCase):
    """Anuncios pagados: Insights a nivel anuncio unidos con la creatividad de /ads."""

    def _ads(self, *bodies, since=None):
        with mock.patch("zero.metaads.urllib.request.urlopen",
                        side_effect=[_resp(b) for b in bodies]) as urlopen:
            out = metaads.MetaAds("act_1", token="tok").ads("acme", since=since)
        return out, [c.args[0].full_url for c in urlopen.call_args_list]

    def test_une_insights_con_creatividad_por_ad_id(self):
        out, _urls = self._ads(_AD_INSIGHTS, _ADS)
        a = out[0]
        self.assertEqual((a["ad_id"], a["status"], a["post_id"]), ("11", "active", "page_post11"))
        self.assertEqual(a["creative"], {"title": "Pisos para piscina", "body": "Cotiza hoy",
                                         "image_url": "https://img/a.jpg",
                                         "thumbnail_url": "https://img/a_t.jpg",
                                         "call_to_action": "LEARN_MORE"})
        self.assertEqual((a["spend"], a["impressions"], a["reach"], a["clicks"], a["ctr"],
                          a["leads"], a["cpl"]), (12000, 4000, 3000, 80, 2.0, 4, 3000))
        self.assertEqual(set(a), set(metaads.MockMetaAds().ads("acme")[0]))   # mock fiel al contrato

    def test_cpl_none_con_cero_leads_y_anuncio_fuera_de_ads_no_se_pierde(self):
        out, _urls = self._ads(_AD_INSIGHTS, _ADS)
        self.assertEqual([a["ad_id"] for a in out], ["11", "12"])     # el de gasto 0 no es pagado
        b = out[1]
        self.assertEqual((b["leads"], b["cpl"]), (0, None))
        self.assertEqual((b["ad_name"], b["campaign_name"], b["status"], b["post_id"]),
                         ("Post B", "Camp A", None, None))
        self.assertEqual(set(b["creative"].values()), {None})

    def test_cuenta_en_usd_se_declara(self):
        usd = json.dumps({"data": [{"ad_id": "11", "spend": "50", "account_currency": "USD"}]})
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[_resp(usd)]):
            with self.assertRaisesRegex(RuntimeError, "no usa CLP"):
                metaads.MetaAds("act_1", token="tok").ads("acme")

    def test_since_usa_time_range_y_sin_since_todo_el_historial(self):
        _out, urls = self._ads(json.dumps({"data": []}))
        self.assertIn("date_preset=maximum", urls[0])
        self.assertIn("level=ad", urls[0])
        _out, urls = self._ads(json.dumps({"data": []}), since="2026-10-01")
        self.assertIn("time_range=", urls[0])
        self.assertIn("2026-10-01", urllib.parse.unquote(urls[0]))
        self.assertEqual(len(urls), 1)                  # sin anuncios pagados no pide /ads


    def test_lee_todas_las_paginas_de_insights_y_pide_archivados(self):
        page1 = json.dumps({"data": [{"ad_id": "11", "spend": "100", "account_currency": "CLP"}],
                            "paging": {"next": "https://x", "cursors": {"after": "c1"}}})
        page2 = json.dumps({"data": [{"ad_id": "12", "spend": "300", "account_currency": "CLP"}]})
        out, urls = self._ads(page1, page2, _ADS)
        self.assertEqual([a["ad_id"] for a in out], ["12", "11"])      # mayor gasto primero
        self.assertIn("after=c1", urls[1])
        self.assertIn("ARCHIVED", urllib.parse.unquote(urls[2]))

    def test_since_formato_raro_es_400(self):
        import api
        from fastapi import HTTPException
        for since in ("20261001", "2026-W40-1", "2999-01-01"):
            with mock.patch.object(api, "_require_client"), self.assertRaises(HTTPException) as caught:
                api.campaign_ads(mock.Mock(), "acme", since=since)
            self.assertEqual(caught.exception.status_code, 400, since)


class CampaignAdsEndpointTest(unittest.TestCase):
    """GET /api/campaigns/ads: nunca mock, y nunca el token de otro cliente."""

    def setUp(self):
        import api
        self.api = api
        patches = [mock.patch.object(api, "_require_client"),
                   mock.patch.object(api, "_client_meta_cfg", return_value={"ad_account": "act_1"}),
                   mock.patch.dict(os.environ, {"META_ADS_TOKEN": "global-tok",
                                                metaads.client_token_key("otro"): "tok-otro",
                                                metaads.client_token_key("acme"): ""})]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_sin_token_propio_es_unavailable_sin_items_aunque_otro_cliente_tenga(self):
        with mock.patch("zero.metaads.urllib.request.urlopen") as urlopen:
            out = self.api.campaign_ads(mock.Mock(), "acme")
        urlopen.assert_not_called()
        self.assertEqual((out["source"], out["items"]), ("unavailable", []))
        self.assertIn("Meta no conectado", out["reason"])

    def test_usa_el_token_del_cliente_pedido(self):
        with mock.patch.dict(os.environ, {metaads.client_token_key("acme"): "tok-acme"}), \
             mock.patch("zero.metaads.urllib.request.urlopen",
                        side_effect=[_resp(_AD_INSIGHTS), _resp(_ADS)]) as urlopen:
            out = self.api.campaign_ads(mock.Mock(), "acme")
        self.assertEqual((out["source"], out["reason"], out["currency"]), ("live", None, "CLP"))
        self.assertEqual(len(out["items"]), 2)
        auth = {c.args[0].get_header("Authorization") for c in urlopen.call_args_list}
        self.assertEqual(auth, {"Bearer tok-acme"})

    def test_error_de_graph_es_unavailable_con_el_motivo(self):
        err = urllib.error.HTTPError("u", 400, "bad", {}, mock.Mock(read=lambda: json.dumps(
            {"error": {"message": "Invalid OAuth access token"}}).encode()))
        with mock.patch.dict(os.environ, {metaads.client_token_key("acme"): "tok-acme"}), \
             mock.patch("zero.metaads.urllib.request.urlopen", side_effect=err):
            out = self.api.campaign_ads(mock.Mock(), "acme")
        self.assertEqual((out["source"], out["items"]), ("unavailable", []))
        self.assertIn("Invalid OAuth access token", out["reason"])

    def test_sin_cuenta_asignada_es_unavailable(self):
        with mock.patch.object(self.api, "_client_meta_cfg", return_value={}):
            out = self.api.campaign_ads(mock.Mock(), "acme")
        self.assertEqual((out["source"], out["items"]), ("unavailable", []))
        self.assertIn("cuenta publicitaria", out["reason"])
