"""Importación de Lead Ads (Instagram): parser de renta, regla income_ok, dedup,
lead_sync, el script automático y su timer. Sin red: Meta va mockeado."""
import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

import api
from zero import config, leadads, metaads
from zero.crm import CRM
from zero.memory import SessionMemory

from tests.test_metaads import _resp

REPO = Path(__file__).resolve().parent.parent
CLIENTE = "Augustar Seguros"


class ParseIncomeRangeTest(unittest.TestCase):
    def test_formatos_chilenos(self):
        casos = {
            "Más de $3.000.000": (3_000_000, None),
            "más de 3.000.000": (3_000_000, None),
            "$2.000.000 - $3.000.000": (2_000_000, 3_000_000),
            "$2.000.000 – $3.000.000": (2_000_000, 3_000_000),
            "2.000.000-3.000.000": (2_000_000, 3_000_000),
            "Entre 2 y 3 millones": (2_000_000, 3_000_000),
            "entre $2 y $3 millones": (2_000_000, 3_000_000),
            "Entre 1,5 y 2,5 millones": (1_500_000, 2_500_000),
            "3M": (3_000_000, 3_000_000),
            "+3M": (3_000_000, None),
            "3 millones": (3_000_000, 3_000_000),
            "Menos de $1.000.000": (None, 1_000_000),
            "Menos de 1 millón": (None, 1_000_000),
            "Hasta $800.000": (None, 800_000),
            "3.000.000 o más": (3_000_000, None),
            "3.000.000 o mas": (3_000_000, None),
            "$3.000.000": (3_000_000, 3_000_000),
            "Sobre 4 millones": (4_000_000, None),
            "500 mil": (500_000, 500_000),
            "Entre 500 mil y 1 millón": (500_000, 1_000_000),
            "3.000.000 mensuales": (3_000_000, 3_000_000),
            "5 millones o menos": (None, 5_000_000),
            "$3.000.000 o menos": (None, 3_000_000),
            "3 millones o inferior": (None, 3_000_000),
            "Como máximo 3 millones": (None, 3_000_000),
            "hasta 3 millones": (None, 3_000_000),
            "hasta $3.000.000": (None, 3_000_000),
            "al menos 3 millones": (3_000_000, None),
            "2 millones y medio": (2_500_000, 2_500_000),
            "2 y medio millones": (2_500_000, 2_500_000),
        }
        for texto, esperado in casos.items():
            self.assertEqual(leadads.parse_income_range(texto), esperado, texto)

    def test_ilegible_es_none(self):
        for texto in ("", None, "prefiero no decir", "3", "sin ingresos", "Más de tres millones"):
            self.assertEqual(leadads.parse_income_range(texto), (None, None), repr(texto))


class IncomeOkTest(unittest.TestCase):
    def test_umbral_de_augustar(self):
        self.assertEqual(config.LEAD_ADS_MIN_INCOME_CLP[CLIENTE], 3_000_000)
        casos = {
            "Más de $3.000.000": True,
            "3.000.000 o más": True,
            "$3.000.000 - $5.000.000": True,
            "+3M": True,
            "Entre 2 y 3 millones": False,       # el mínimo del tramo no llega
            "$2.000.000 - $3.000.000": False,
            "Menos de $1.000.000": False,
            "Menos de $3.000.000": False,
            "Menos de 5 millones": None,          # tope sobre el umbral: no se sabe
            "no sé": None,
            "": None,
        }
        for texto, esperado in casos.items():
            self.assertIs(leadads.income_ok(texto, CLIENTE), esperado, texto)

    def test_cliente_sin_umbral_es_none(self):
        self.assertIsNone(leadads.income_ok("Más de $3.000.000", "otro-cliente"))
        self.assertIsNone(leadads.min_income_clp("otro-cliente"))


def _lead(**kw):
    base = {"key": "ana@example.cl", "email": "ana@example.cl", "phone": "+56912345678",
            "name": "Ana", "company": "Ana", "channel": "whatsapp", "source": "meta_ads",
            "meta_form_id": "123", "income_range": "Más de $3.000.000",
            "lead_origin": {"platform": "ig", "form_id": "123", "ad_id": "ad-1",
                            "ad_name": "A", "campaign_name": "C", "lead_id": "l1"}}
    base.update(kw)
    return base


def _memory(meta=None):
    memory = SessionMemory()
    memory.register_client(CLIENTE, "STARTER")
    memory.set_client_meta(CLIENTE, {"lead_form_ids": ["123"], "ad_account": "act_1", **(meta or {})})
    return memory


def _importar(crm, leads, memory=None, client=CLIENTE):
    memory = memory or _memory()
    source = SimpleNamespace(live=True, lead_ads=lambda c, cfg, since=None: leads)
    with mock.patch("zero.leadads.make_metaads", return_value=source):
        return leadads.import_lead_ads(client, memory, crm), memory


class ImportLeadAdsTest(unittest.TestCase):
    def test_lead_de_instagram_entra_en_new_con_origen_y_renta(self):
        crm = CRM()
        result, _ = _importar(crm, [_lead()])
        self.assertEqual((result["read"], result["created"], result["already_present"],
                          result["skipped_blocked"]), (1, 1, 0, 0))
        rec = crm.list(CLIENTE)[0]
        self.assertEqual(rec["stage"], "new")
        self.assertEqual(rec["source"], "instagram_ads")
        self.assertEqual(rec["tags"], ["Meta Ads", "Instagram Ads"])
        self.assertEqual(rec["income_range"], "Más de $3.000.000")
        self.assertIs(rec["income_ok"], True)
        self.assertEqual(rec["lead_origin"]["ad_id"], "ad-1")

    def test_renta_baja_marca_income_ok_false_pero_importa(self):
        crm = CRM()
        _importar(crm, [_lead(income_range="Menos de $1.000.000")])
        rec = crm.list(CLIENTE)[0]
        self.assertIs(rec["income_ok"], False)
        self.assertEqual(rec["stage"], "new")

    def test_plataforma_de_la_config_marca_instagram_aunque_meta_no_la_informe(self):
        crm = CRM()
        _importar(crm, [_lead(lead_origin={"platform": None})],
                  _memory({"lead_platform": "instagram"}))
        self.assertEqual(crm.list(CLIENTE)[0]["source"], "instagram_ads")

    def test_facebook_sin_plataforma_configurada_queda_como_meta(self):
        crm = CRM()
        _importar(crm, [_lead(lead_origin={"platform": "fb"})])
        rec = crm.list(CLIENTE)[0]
        self.assertEqual((rec["source"], rec["tags"]), ("meta_ads", ["Meta Ads"]))

    def test_contacto_existente_con_mismo_telefono_no_se_duplica_ni_cambia_de_etapa(self):
        crm = CRM()
        crm.upsert(CLIENTE, {"phone": "+56 9 1234 5678", "name": "Ana"}, stage="contacted")
        result, _ = _importar(crm, [_lead()])
        self.assertEqual((result["created"], result["already_present"]), (0, 1))
        self.assertEqual(len(crm.list(CLIENTE)), 1)
        rec = crm.list(CLIENTE)[0]
        self.assertEqual(rec["stage"], "contacted")
        self.assertEqual(rec["income_range"], "Más de $3.000.000")   # enriquecido

    def test_opt_out_por_telefono_no_se_reimporta_con_email_nuevo(self):
        crm = CRM()
        crm.upsert(CLIENTE, {"phone": "+56 9 1234 5678", "name": "Ana"})
        crm.block(CLIENTE, "+56 9 1234 5678")
        result, _ = _importar(crm, [_lead()])
        self.assertEqual((result["created"], result["skipped_blocked"]), (0, 1))
        self.assertEqual(len(crm.list(CLIENTE)), 1)

    def test_mismo_telefono_de_otro_cliente_no_bloquea(self):
        crm = CRM()
        crm.upsert("petlabs", {"phone": "+56912345678", "name": "Otra Ana"})
        crm.block("petlabs", "+56912345678")
        result, _ = _importar(crm, [_lead()])
        self.assertEqual((result["created"], result["skipped_blocked"]), (1, 0))

    def test_importacion_repetida_no_duplica(self):
        crm = CRM()
        memory = _memory()
        first, _ = _importar(crm, [_lead()], memory)
        second, _ = _importar(crm, [_lead()], memory)
        self.assertEqual((first["created"], second["created"], second["already_present"]), (1, 0, 1))
        self.assertEqual(len(crm.list(CLIENTE)), 1)

    def test_guarda_lead_sync_y_conserva_el_resto_de_la_config(self):
        memory = _memory({"monthly_budget_clp": 500000})
        _importar(CRM(), [_lead()], memory)
        meta = memory.get_client_meta(CLIENTE)
        self.assertEqual(meta["monthly_budget_clp"], 500000)
        self.assertEqual(meta["lead_form_ids"], ["123"])
        sync = meta["lead_sync"]
        self.assertEqual({k: v for k, v in sync.items() if k != "at"},
                         {"read": 1, "created": 1, "already_present": 0, "skipped_blocked": 0})
        self.assertRegex(sync["at"], r"^\d{4}-\d\d-\d\dT.*\+00:00$")

    def test_sin_formularios_es_error_claro_y_queda_registrado(self):
        memory = _memory()
        memory.set_client_meta(CLIENTE, {"ad_account": "act_1"})
        with self.assertRaisesRegex(leadads.LeadAdsError, "al menos un formulario"):
            leadads.import_lead_ads(CLIENTE, memory, CRM())
        self.assertIn("formulario", memory.get_client_meta(CLIENTE)["lead_sync"]["error"])

    def test_sin_meta_conectado_no_cae_a_mock_ni_abre_el_crm(self):
        crm = mock.Mock(return_value=CRM())
        with mock.patch.dict("os.environ", {metaads.client_token_key(CLIENTE): ""}):
            with self.assertRaisesRegex(leadads.LeadAdsError, "Meta Ads no está conectado"):
                leadads.import_lead_ads(CLIENTE, _memory(), crm)
        crm.assert_not_called()

    def test_error_de_meta_se_registra_en_lead_sync(self):
        memory = _memory()
        source = SimpleNamespace(live=True, lead_ads=mock.Mock(side_effect=RuntimeError("Meta HTTP 400: token")))
        with mock.patch("zero.leadads.make_metaads", return_value=source):
            with self.assertRaisesRegex(leadads.LeadAdsError, "Meta HTTP 400"):
                leadads.import_lead_ads(CLIENTE, memory, CRM())
        sync = memory.get_client_meta(CLIENTE)["lead_sync"]
        self.assertEqual(sync["error"], "Meta HTTP 400: token")
        self.assertNotIn("created", sync)

    def test_cliente_inexistente(self):
        with self.assertRaises(leadads.ClienteNoEncontrado):
            leadads.import_lead_ads("fantasma", _memory(), CRM())


class EnriquecimientoTest(unittest.TestCase):
    def _ficha_b2b(self, crm):
        crm.upsert(CLIENTE, {"key": "ventas@acme.cl", "phone": "+56 9 1234 5678",
                             "name": "Ana (editado)", "company": "Acme", "channel": "email",
                             "source": "pipeline"}, stage="contacted")

    def test_ficha_existente_conserva_source_channel_y_nombre_y_gana_renta_y_tags(self):
        crm = CRM()
        self._ficha_b2b(crm)
        result, _ = _importar(crm, [_lead()])
        self.assertEqual((result["created"], result["already_present"]), (0, 1))
        rec = crm.list(CLIENTE)[0]
        self.assertEqual((rec["source"], rec["channel"], rec["name"], rec["company"]),
                         ("pipeline", "email", "Ana (editado)", "Acme"))
        self.assertEqual(rec["stage"], "contacted")
        self.assertEqual(rec["email"], "ana@example.cl")            # estaba vacío: se completa
        self.assertEqual(rec["income_range"], "Más de $3.000.000")
        self.assertIs(rec["income_ok"], True)
        self.assertEqual(rec["lead_origin"]["ad_id"], "ad-1")
        self.assertEqual(rec["tags"], ["Meta Ads", "Instagram Ads"])

    def test_segunda_importacion_identica_no_toca_la_ficha_ni_guarda(self):
        crm = CRM()
        self._ficha_b2b(crm)
        _importar(crm, [_lead()])
        antes = json.dumps(crm.list(CLIENTE)[0], sort_keys=True)
        with mock.patch.object(crm, "save") as guardar, mock.patch.object(crm, "upsert") as upsert:
            result, _ = _importar(crm, [_lead()])
        self.assertEqual(result["already_present"], 1)
        guardar.assert_not_called()
        upsert.assert_not_called()
        self.assertEqual(json.dumps(crm.list(CLIENTE)[0], sort_keys=True), antes)

    def test_renta_distinta_en_el_formulario_actualiza_la_ficha(self):
        crm = CRM()
        _importar(crm, [_lead(income_range="Menos de $1.000.000")])
        _importar(crm, [_lead(income_range="Más de $3.000.000")])
        rec = crm.list(CLIENTE)[0]
        self.assertEqual(rec["income_range"], "Más de $3.000.000")
        self.assertIs(rec["income_ok"], True)


class MemoriaConcurrenteTest(unittest.TestCase):
    def test_import_no_borra_escrituras_concurrentes_del_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "state.json")
            memory = SessionMemory(path)
            memory.register_client(CLIENTE, "STARTER")
            memory.set_client_meta(CLIENTE, {"lead_form_ids": ["123"], "ad_account": "act_1"})
            memory.save()

            def leads_mientras_el_api_escribe(c, cfg, since=None):
                otra = SessionMemory(path)                  # el API, en otro proceso
                otra.set_client_meta(CLIENTE, {**otra.get_client_meta(CLIENTE), "monthly_budget_clp": 777})
                otra.register_client("nuevo", "STARTER")
                otra.save()
                return [_lead()]

            source = SimpleNamespace(live=True, lead_ads=leads_mientras_el_api_escribe)
            with mock.patch("zero.leadads.make_metaads", return_value=source):
                leadads.import_lead_ads(CLIENTE, memory, CRM())
            final = SessionMemory(path)
            meta = final.get_client_meta(CLIENTE)
            self.assertEqual(meta["monthly_budget_clp"], 777)
            self.assertIn("nuevo", final.clients)
            self.assertEqual(meta["lead_sync"]["created"], 1)
            self.assertEqual(meta["lead_form_ids"], ["123"])

    def test_si_record_sync_falla_se_relanza_el_error_original_de_meta(self):
        memory = _memory()
        source = SimpleNamespace(live=True, lead_ads=mock.Mock(side_effect=RuntimeError("Meta HTTP 400")))
        with mock.patch("zero.leadads.make_metaads", return_value=source), \
             mock.patch.object(memory, "reload", side_effect=OSError("disco lleno")):
            with self.assertRaisesRegex(leadads.LeadAdsError, "Meta HTTP 400") as ctx:
                leadads.import_lead_ads(CLIENTE, memory, CRM())
        self.assertIn("disco lleno", "\n".join(ctx.exception.__notes__))


class CursorYFormulariosTest(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict("os.environ", {"META_ADS_TOKEN": "tok"})
        env.start()
        self.addCleanup(env.stop)

    @staticmethod
    def _filas(form, created):
        return json.dumps({"data": [{"id": f"l-{form}", "ad_id": "ad-1", "created_time": created,
                                     "field_data": [{"name": "email", "values": [f"{form}@x.cl"]}]}]})

    def test_cursor_por_formulario_y_filtering_con_margen(self):
        account = json.dumps({"account_id": "1"})
        cfg = {"lead_form_ids": ["1", "2"]}
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=[
                _resp(self._filas("1", "2026-10-15T10:00:00+0000")), _resp(account),
                _resp(self._filas("2", "2026-10-15T11:00:00+0000"))]):
            src = metaads.MetaAds("act_1")
            src.lead_ads("c", cfg)
        self.assertEqual(src.cursors, {"1": "2026-10-15T10:00:00+0000", "2": "2026-10-15T11:00:00+0000"})
        urls = []
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=lambda r, **kw: (
                urls.append(r.full_url), _resp(json.dumps({"data": []})))[1]):
            src.lead_ads("c", cfg, since=src.cursors)
        from urllib.parse import parse_qs, urlparse
        filtro = json.loads(parse_qs(urlparse(urls[0]).query)["filtering"][0])
        esperado = int(metaads._parse_graph_time("2026-10-15T10:00:00+0000").timestamp()) \
            - config.LEAD_ADS_CURSOR_MARGIN_SECONDS
        self.assertEqual(filtro, [{"field": "time_created", "operator": "GREATER_THAN", "value": esperado}])
        self.assertEqual(config.LEAD_ADS_CURSOR_MARGIN_SECONDS, 3600)

    def test_primera_vez_pide_todo_sin_filtering(self):
        urls = []
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=lambda r, **kw: (
                urls.append(r.full_url), _resp(json.dumps({"data": []})))[1]):
            metaads.MetaAds("act_1").lead_ads("c", {"lead_form_ids": ["1"]})
        self.assertNotIn("filtering", urls[0])

    def test_un_formulario_caido_no_aborta_a_los_demas_ni_avanza_su_cursor(self):
        account = json.dumps({"account_id": "1"})
        err = urllib.error.URLError("sin red")

        def fake(req, **kw):
            if "/1/leads" in req.full_url:
                raise err
            return _resp(account if "fields=account_id" in req.full_url
                         else self._filas("2", "2026-10-15T11:00:00+0000"))
        src = metaads.MetaAds("act_1")
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=fake):
            leads = src.lead_ads("c", {"lead_form_ids": ["1", "2"]},
                                 since={"1": "2026-10-15T09:00:00+0000"})
        self.assertEqual([l["email"] for l in leads], ["2@x.cl"])
        self.assertEqual([f["form_id"] for f in src.failed_forms], ["1"])
        self.assertEqual(src.cursors, {"2": "2026-10-15T11:00:00+0000"})   # el "1" conserva el previo

    def test_si_fallan_todos_los_formularios_es_error(self):
        with mock.patch("zero.metaads.urllib.request.urlopen", side_effect=urllib.error.URLError("x")):
            with self.assertRaisesRegex(RuntimeError, "formulario 1"):
                metaads.MetaAds("act_1").lead_ads("c", {"lead_form_ids": ["1", "2"]})

    def test_lead_sync_guarda_cursores_y_formularios_fallidos_y_los_conserva_en_error(self):
        memory = _memory()
        source = SimpleNamespace(live=True, lead_ads=mock.Mock(return_value=[_lead()]),
                                 failed_forms=[{"form_id": "9", "error": "boom"}],
                                 cursors={"123": "2026-10-15T10:00:00+0000"})
        with mock.patch("zero.leadads.make_metaads", return_value=source):
            result = leadads.import_lead_ads(CLIENTE, memory, CRM())
        self.assertEqual(result["failed_forms"], [{"form_id": "9", "error": "boom"}])
        self.assertNotIn("since", result)
        sync = memory.get_client_meta(CLIENTE)["lead_sync"]
        self.assertEqual(sync["since"], {"123": "2026-10-15T10:00:00+0000"})
        self.assertEqual(sync["failed_forms"], [{"form_id": "9", "error": "boom"}])
        source.lead_ads.assert_called_with(CLIENTE, mock.ANY, since=None)
        source.lead_ads.side_effect = RuntimeError("Meta HTTP 500")
        with mock.patch("zero.leadads.make_metaads", return_value=source):
            with self.assertRaises(leadads.LeadAdsError):
                leadads.import_lead_ads(CLIENTE, memory, CRM())
        sync = memory.get_client_meta(CLIENTE)["lead_sync"]
        self.assertEqual(sync["since"], {"123": "2026-10-15T10:00:00+0000"})
        self.assertIn("error", sync)
        with mock.patch("zero.leadads.make_metaads", return_value=source):
            source.lead_ads.side_effect = None
            leadads.import_lead_ads(CLIENTE, memory, CRM())
        source.lead_ads.assert_called_with(CLIENTE, mock.ANY, since={"123": "2026-10-15T10:00:00+0000"})


class SyncEndpointTest(unittest.TestCase):
    def test_operador_ajeno_recibe_404_sin_tocar_nada(self):
        request = SimpleNamespace(state=SimpleNamespace(auth={"role": "operador", "clients": ["otro"]}))
        with mock.patch.object(api, "make_memory") as memoria:
            with self.assertRaises(HTTPException) as ctx:
                api.sync_ad_leads(request, CLIENTE)
        self.assertEqual((ctx.exception.status_code, ctx.exception.detail), (404, "cliente no encontrado"))
        memoria.assert_not_called()

    def test_cliente_inexistente_es_404_y_el_resto_de_errores_400(self):
        request = SimpleNamespace(state=SimpleNamespace())
        memory = _memory()
        with mock.patch.object(api, "make_memory", return_value=memory):
            with self.assertRaises(HTTPException) as ctx:
                api.sync_ad_leads(request, "fantasma")
            self.assertEqual(ctx.exception.status_code, 404)
            memory.set_client_meta(CLIENTE, {})
            with self.assertRaises(HTTPException) as ctx:
                api.sync_ad_leads(request, CLIENTE)
            self.assertEqual(ctx.exception.status_code, 400)

    def test_importa_por_el_endpoint(self):
        crm = CRM()
        source = SimpleNamespace(live=True, lead_ads=lambda c, cfg, since=None: [_lead()])
        with mock.patch.object(api, "make_memory", return_value=_memory()), \
             mock.patch.object(api, "_crm", return_value=crm), \
             mock.patch("zero.leadads.make_metaads", return_value=source):
            out = api.sync_ad_leads(SimpleNamespace(state=SimpleNamespace()), CLIENTE)
        self.assertEqual(out, {"client": CLIENTE, "read": 1, "created": 1,
                               "already_present": 0, "skipped_blocked": 0})


def _cargar_script():
    spec = importlib.util.spec_from_file_location(
        "importar_instagram", REPO / "scripts" / "importar-instagram.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class ScriptImportarInstagramTest(unittest.TestCase):
    def setUp(self):
        self.script = _cargar_script()
        self.memory = SessionMemory()
        for nombre, forms in (("a", ["1"]), ("b", ["2"]), ("c", ["3"]), ("sin-forms", [])):
            self.memory.register_client(nombre, "STARTER")
            self.memory.set_client_meta(nombre, {"lead_form_ids": forms})

    def _correr(self, import_fn):
        salida = io.StringIO()
        with mock.patch.object(self.script, "make_memory", return_value=self.memory), \
             mock.patch.object(self.script, "make_crm", return_value=CRM()), \
             mock.patch.object(self.script, "import_lead_ads", side_effect=import_fn) as llamadas, \
             redirect_stdout(salida):
            codigo = self.script.main()
        return codigo, salida.getvalue(), llamadas

    def test_un_cliente_que_falla_no_frena_al_resto(self):
        def importar(cliente, memory, crm):
            if cliente == "b":
                raise leadads.LeadAdsError("token vencido")
            return {"client": cliente, "read": 2, "created": 1, "already_present": 1, "skipped_blocked": 0}
        codigo, salida, llamadas = self._correr(importar)
        self.assertEqual([c.args[0] for c in llamadas.call_args_list], ["a", "b", "c"])
        self.assertEqual(codigo, 1)
        self.assertIn("b: ERROR token vencido", salida)
        self.assertIn("c: leídos 2, nuevos 1", salida)

    def test_todo_bien_sale_con_cero(self):
        codigo, _, _ = self._correr(lambda cliente, memory, crm: {
            "client": cliente, "read": 0, "created": 0, "already_present": 0, "skipped_blocked": 0})
        self.assertEqual(codigo, 0)

    def test_sin_clientes_con_formularios_no_llama_a_nadie(self):
        for nombre in ("a", "b", "c"):
            self.memory.set_client_meta(nombre, {})
        codigo, salida, llamadas = self._correr(lambda *a: {})
        self.assertEqual(codigo, 0)
        llamadas.assert_not_called()
        self.assertIn("ningún cliente", salida)

    def test_el_crm_se_abre_recien_al_necesitarlo(self):
        abierto = mock.Mock(return_value=CRM())
        self.memory.set_client_meta("a", {"lead_form_ids": ["1"]})
        for nombre in ("b", "c"):
            self.memory.set_client_meta(nombre, {})
        with mock.patch.object(self.script, "make_memory", return_value=self.memory), \
             mock.patch.object(self.script, "make_crm", abierto), \
             redirect_stdout(io.StringIO()):
            codigo = self.script.main()     # "a" no tiene token de Meta: falla antes del CRM
        self.assertEqual(codigo, 1)
        abierto.assert_not_called()
        self.assertIn("Meta Ads no está conectado", self.memory.get_client_meta("a")["lead_sync"]["error"])


class ScriptAyudaTest(unittest.TestCase):
    def test_help_sale_con_cero_sin_importar_nada(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"PATH": "/usr/bin:/bin", "STATE_PATH": str(Path(tmp) / "state.json"),
                   "CRM_PATH": str(Path(tmp) / "crm.json")}
            out = subprocess.run([sys.executable, "-I", str(REPO / "scripts" / "importar-instagram.py"), "--help"],
                                 capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("DATOS REALES", out.stdout)
            self.assertEqual(list(Path(tmp).iterdir()), [])


class TimerTest(unittest.TestCase):
    def test_el_timer_corre_cada_lead_ads_sync_minutes(self):
        timer = (REPO / "deploy" / "zero-instagram.timer").read_text()
        minutos = re.search(r"^OnUnitActiveSec=(\d+)min$", timer, re.M)
        self.assertIsNotNone(minutos)
        self.assertEqual(int(minutos.group(1)), config.LEAD_ADS_SYNC_MINUTES)

    def test_el_servicio_ejecuta_el_script(self):
        servicio = (REPO / "deploy" / "zero-instagram.service").read_text()
        self.assertIn("scripts/importar-instagram.py", servicio)
        self.assertTrue((REPO / "scripts" / "importar-instagram.py").exists())


if __name__ == "__main__":
    unittest.main()
