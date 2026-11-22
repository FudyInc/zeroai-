"""Onboarding por archivo: catálogo y FAQ de una empresa nueva (zero/onboarding.py).

Lo que se protege: que importar un archivo deje al agente con base de
conocimiento SIN tocar lo escrito a mano, sin inventar precios (ilegible = error,
nunca 0), versionado con el rollback de siempre, y sin poder pisar a PoolEdge.

Los endpoints se llaman como funciones con `make_memory` parchado a una
SessionMemory sin archivo: no tocan state.json ni Supabase.

Run: python3 -m unittest tests.test_onboarding -v
"""
from __future__ import annotations

import base64
import io
import unittest
import zipfile
from unittest import mock

from fastapi import HTTPException

import api
from zero import onboarding
from zero.config import ONBOARDING_MAX_BYTES
from zero.memory import SessionMemory


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _xlsx(rows) -> bytes:
    """Un XLSX mínimo: shared strings para texto, números como número."""
    strings, sheet_rows = [], []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                strings.append(value)
                cells.append(f'<c r="{ref}" t="s"><v>{len(strings) - 1}</v></c>')
        sheet_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml",
                   f'<workbook {ns} xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
                   f'2006/relationships"><sheets><sheet name="Hoja1" sheetId="1" r:id="rId1"/>'
                   f'</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rId1" Target="worksheets/hoja.xml"/>'
                   '</Relationships>')
        z.writestr("xl/sharedStrings.xml",
                   f'<sst {ns}>' + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/hoja.xml",
                   f'<worksheet {ns}><sheetData>{"".join(sheet_rows)}</sheetData></worksheet>')
    return buf.getvalue()


CATALOGO_PUNTO_COMA = ("﻿sku;nombre;categoría;precio;unidad;descripción;stock\n"
                       "L-01;Loseta gris 50x50;Losetas;$12.990;m2;Antideslizante;40\n"
                       "B-02;Borde piscina recto;Bordes;12.990,00;unidad;;\n").encode("utf-8")
MANUAL = "Somos Piscinas Sur. Atendemos de lunes a viernes de 9 a 18.\n\nDespacho en Santiago."


class LecturaTest(unittest.TestCase):

    def test_csv_con_punto_y_coma_y_bom(self):
        rows, errors = onboarding.validate("catalogo", onboarding.read_table("c.csv", CATALOGO_PUNTO_COMA))
        self.assertEqual(errors, [])
        self.assertEqual([r["precio"] for r in rows], [12990, 12990])
        self.assertEqual(rows[0]["categoria"], "Losetas")       # encabezado con tilde
        self.assertEqual(rows[0]["nombre"], "Loseta gris 50x50")

    def test_csv_latin1(self):
        data = "pregunta,respuesta\n¿Hacen envíos?,\"Sí, a todo Chile\"\n".encode("latin-1")
        rows, errors = onboarding.validate("faq", onboarding.read_table("f.csv", data))
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["pregunta"], "¿Hacen envíos?")
        self.assertEqual(rows[0]["respuesta"], "Sí, a todo Chile")

    def test_xlsx_minimo(self):
        data = _xlsx([["sku", "nombre", "precio", "unidad"],
                      ["A1", "Pastelón 40x40", 8990, "unidad"],
                      ["A2", "Pastelón 50x50", "$10.500", "unidad"]])
        rows, errors = onboarding.validate("catalogo", onboarding.read_table("c.xlsx", data))
        self.assertEqual(errors, [])
        self.assertEqual([(r["sku"], r["precio"]) for r in rows], [("A1", 8990), ("A2", 10500)])

    def test_xls_antiguo_no_se_adivina(self):
        with self.assertRaises(onboarding.OnboardingError) as ctx:
            onboarding.read_table("viejo.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest")
        self.assertEqual(ctx.exception.status, 415)

    def test_precios_aceptados(self):
        for raw, esperado in (("$12.990", 12990), ("12990", 12990), ("12.990,00", 12990),
                              ("12,990", 12990), ("$ 1.250.000", 1250000), (8990.0, 8990)):
            self.assertEqual(onboarding.parse_clp(raw), esperado, raw)

    def test_precio_ilegible_es_error_de_fila_nunca_cero(self):
        data = b"nombre,precio\nLoseta,consultar\nBorde,0\nTapa,12.5\nOk,1000\n"
        rows, errors = onboarding.validate("catalogo", onboarding.read_table("c.csv", data))
        self.assertEqual([r["nombre"] for r in rows], ["Ok"])
        self.assertEqual([(e["fila"], e["columna"]) for e in errors],
                         [(2, "precio"), (3, "precio"), (4, "precio")])

    def test_coma_sin_comillas_es_error_no_texto_truncado(self):
        """Encontrado en la corrida real: «Sí, a todo Santiago» quedaba como «Sí»."""
        data = "pregunta,respuesta\n¿Despachan?,Sí, a todo Santiago\n¿Tarjeta?,\"Sí, débito\"\n".encode()
        rows, errors = onboarding.validate("faq", onboarding.read_table("f.csv", data))
        self.assertEqual([e["fila"] for e in errors], [2])
        self.assertEqual(rows[0]["respuesta"], "Sí, débito")

    def test_falta_columna_obligatoria(self):
        rows, errors = onboarding.validate("faq", onboarding.read_table("f.csv", b"pregunta\nHola\n"))
        self.assertEqual(rows, [])
        self.assertEqual(errors, [{"fila": 1, "columna": "respuesta",
                                   "motivo": "falta la columna obligatoria"}])

    def test_fila_repetida_es_error(self):
        data = b"sku,nombre,precio\nA,Uno,100\nA,Otro,200\n"
        _, errors = onboarding.validate("catalogo", onboarding.read_table("c.csv", data))
        self.assertEqual(errors[0]["fila"], 3)
        self.assertIn("fila 2", errors[0]["motivo"])

    def test_demasiadas_filas(self):
        data = ("pregunta,respuesta\n" + "".join(f"p{i},r\n" for i in range(5))).encode()
        with mock.patch.object(onboarding, "ONBOARDING_MAX_ROWS", 3):
            with self.assertRaises(onboarding.OnboardingError) as ctx:
                onboarding.validate("faq", onboarding.read_table("f.csv", data))
        self.assertEqual(ctx.exception.status, 413)


class RevisorTest(unittest.TestCase):
    """Casos reproducidos por el revisor (2026-11-22)."""

    def test_columna_gigante_no_infla_la_fila(self):
        src = zipfile.ZipFile(io.BytesIO(_xlsx([["nombre", "precio"], ["A", 100]])))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for n in src.namelist():
                z.writestr(n, src.read(n).replace(b'r="B2"', b'r="ZZZZZ2"'))
        data = buf.getvalue()
        rows = onboarding.read_table("c.xlsx", data)
        self.assertLessEqual(max(len(cells) for _, cells in rows), 50)

    def test_separadores_colgantes_son_error_de_fila(self):
        for precio in ("12.", "12,", ".120", ",120", "12.990,", "12,990."):
            with self.subTest(precio=precio):
                tabla = onboarding.read_table("c.csv", f"nombre;precio\nA;{precio}".encode())
                rows, errors = onboarding.validate("catalogo", tabla)
                self.assertEqual(rows, [])
                self.assertEqual([(e["fila"], e["columna"]) for e in errors], [(2, "precio")])

    def test_precio_fuera_de_precision_del_cotizador(self):
        for precio in (2**53 + 1, 10**309):
            for name, data in (("c.csv", f"nombre,precio\nA,{precio}".encode()),
                               ("c.xlsx", _xlsx([["nombre", "precio"], ["A", precio]]))):
                with self.subTest(precio=precio, archivo=name):
                    out = onboarding.preview("catalogo", name, data, "", {})
                    self.assertEqual(out["rows"], [])
                    self.assertEqual([(e["fila"], e["columna"]) for e in out["errors"]],
                                     [(2, "precio")])

    def test_marcador_reservado_se_rechaza_en_ambos_archivos(self):
        for kind, col, data in (
            ("faq", "pregunta", b"pregunta,respuesta\n<!-- faq:inicio -->,Si"),
            ("faq", "respuesta", b"pregunta,respuesta\nA?,<!-- catalogo:fin -->"),
            ("catalogo", "descripcion", b"nombre,precio,descripcion\nA,100,Texto <!-- reservado"),
        ):
            with self.subTest(kind=kind, col=col):
                out = onboarding.preview(kind, "archivo.csv", data, "", {})
                self.assertEqual(out["rows"], [])
                self.assertEqual([(e["fila"], e["columna"]) for e in out["errors"]], [(2, col)])

    def test_csv_conserva_filas_vacias_antes_y_despues_del_encabezado(self):
        data = b'\n\npregunta,respuesta\nA,"dos\nlineas"\n\nB,'
        out = onboarding.preview("faq", "archivo.csv", data, "", {})
        self.assertEqual(out["rows"][0]["fila"], 4)
        self.assertEqual(out["errors"][0]["fila"], 6)
        out = onboarding.preview("faq", "archivo.csv", b"\n\npregunta\nA", "", {})
        self.assertEqual(out["errors"][0]["fila"], 3)

    def test_xlsx_respeta_numeros_de_fila_y_omite_anotaciones_foneticas(self):
        src = _xlsx([[], ["pregunta", "respuesta"], ["Hola", "respuesta inicial"], ["Otra", ""]])
        buf = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(src)) as original, zipfile.ZipFile(buf, "w") as z:
            for nombre in original.namelist():
                xml = original.read(nombre)
                if nombre == "xl/sharedStrings.xml":
                    xml = xml.replace(b"<t>Hola</t>", b"<r><t>Ho</t></r><r><t>la</t></r>"
                                      b"<rPh><t>pronunciacion</t></rPh>")
                if nombre.endswith("hoja.xml"):
                    xml = xml.replace(b'<c r="B3" t="s"><v>3</v></c>',
                                      b'<c r="B3" t="inlineStr"><is><t>Respuesta</t>'
                                      b'<rPh><t>fonetica</t></rPh></is></c>')
                    xml = xml.replace(b'<row r="4"', b'<row r="40"')
                    xml = xml.replace(b'A4"', b'A40"').replace(b'B4"', b'B40"')
                z.writestr(nombre, xml)
        out = onboarding.preview("faq", "archivo.xlsx", buf.getvalue(), "", {})
        self.assertEqual(out["rows"], [{"fila": 3, "pregunta": "Hola", "respuesta": "Respuesta"}])
        self.assertEqual(out["errors"][0]["fila"], 40)

    def test_xml_roto_y_precio_infinito_no_son_500(self):
        with self.assertRaises(onboarding.OnboardingError) as ctx:
            onboarding.preview("faq", "c.xlsx", _xlsx([["pregunta"]]).replace(b"<sst", b"<sst<"), "", {})
        self.assertEqual(ctx.exception.status, 422)
        with self.assertRaises(ValueError):
            onboarding.parse_clp(float("inf"))

    def test_mismo_faq_dos_veces_queda_sin_cambio(self):
        rows = [{"pregunta": "a?", "respuesta": "b"}, {"pregunta": "c?", "respuesta": "d"}]
        ficha = onboarding.replace_section(MANUAL, "faq", onboarding.render_section("faq", rows))
        resumen = onboarding.summarize("faq", rows, [], ficha, {})
        self.assertEqual((resumen["sin_cambio"], resumen["cambian"]), (2, 0))


class SeccionTest(unittest.TestCase):

    def test_select_knowledge_recorta_por_item(self):
        """La sección sirve al recorte real del agente: la pregunta por un
        producto trae SU línea con precio, no todo el catálogo."""
        from zero.whatsapp_context import select_knowledge
        rows = [{"nombre": f"Producto {n}", "precio": 1000 * n, "unidad": "", "categoria": "",
                 "sku": "", "descripcion": "", "stock": ""} for n in range(1, 60)]
        rows.append({"nombre": "Cubierta térmica", "precio": 45990, "unidad": "unidad",
                     "categoria": "", "sku": "", "descripcion": "", "stock": ""})
        ficha = onboarding.replace_section(MANUAL, "catalogo", onboarding.render_section("catalogo", rows))
        corte = select_knowledge(ficha, "¿cuánto cuesta la cubierta térmica?", max_chars=600)
        # Es el último de 60 y el corte es de 600 caracteres: entra porque su
        # línea es la que más puntúa, no por estar primero.
        self.assertIn("Cubierta térmica: precio $45.990 por unidad.", corte)
        self.assertNotIn("Producto 59:", corte)

    def test_marcadores_danados_no_se_adivinan(self):
        ficha = MANUAL + "\n\n<!-- faq:inicio -->\n\n- hola\n  chao"
        with self.assertRaises(onboarding.OnboardingError) as ctx:
            onboarding.replace_section(ficha, "faq", onboarding.render_section(
                "faq", [{"pregunta": "a", "respuesta": "b"}]))
        self.assertEqual(ctx.exception.status, 409)


class EndpointsTest(unittest.TestCase):
    """Los endpoints como funciones, con una memoria sin archivo."""

    def setUp(self):
        self.mem = SessionMemory()
        self.mem.register_client("piscinas-sur", "GROWTH")
        self.mem.register_client("losetaschile", "GROWTH")
        self.mem.set_client_knowledge("piscinas-sur", MANUAL, motivo="ficha inicial")
        self.req = mock.Mock()
        self.req.state = mock.Mock(spec=[])            # sin auth: sin alcance
        crm = mock.Mock()
        crm.client_ids.return_value = []
        patches = [mock.patch.object(api, "make_memory", return_value=self.mem),
                   mock.patch.object(api, "_crm", return_value=crm),
                   mock.patch.object(self.mem, "save")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        onboarding.PREVIEWS._items.clear()

    def preview(self, kind, data, client="piscinas-sur", filename="archivo.csv"):
        return api.onboarding_preview(self.req, client, api.OnboardingPreviewBody(
            kind=kind, filename=filename, content_base64=_b64(data)))

    def apply(self, token, client="piscinas-sur"):
        return api.onboarding_apply(self.req, client, api.OnboardingApplyBody(token=token))

    def test_preview_y_apply_rechazan_secciones_superpuestas(self):
        token = self.preview("faq", b"pregunta,respuesta\nA?,B\n")["token"]
        c1, c2 = onboarding.markers("catalogo")
        f1, f2 = onboarding.markers("faq")
        self.mem.set_client_knowledge("piscinas-sur", "\n".join([c1, f1, c2, f2]))
        antes = self.mem.snapshot()
        for call in (lambda: self.preview("catalogo", CATALOGO_PUNTO_COMA),
                     lambda: self.apply(token)):
            with self.assertRaises(HTTPException) as ctx:
                call()
            self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.mem.snapshot(), antes)

    def test_cupo_de_previews_preserva_otro_cliente(self):
        store = onboarding.PreviewStore()
        vecino = store.put({"client": "otra"})
        with mock.patch.object(onboarding, "ONBOARDING_MAX_PREVIEWS_PER_CLIENT", 1):
            viejo = store.put({"client": "prueba"})
            nuevo = store.put({"client": "prueba"})
        with self.assertRaises(onboarding.OnboardingError) as ctx:
            store.get(viejo, "prueba")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(store.get(vecino, "otra")["client"], "otra")
        self.assertEqual(store.get(nuevo, "prueba")["client"], "prueba")

    def test_template(self):
        resp = api.onboarding_template("catalogo")
        self.assertEqual(resp.body.decode().strip(), "sku,nombre,categoria,precio,unidad,descripcion,stock")
        self.assertTrue(resp.media_type.startswith("text/csv"))
        with self.assertRaises(HTTPException) as ctx:
            api.onboarding_template("otra")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_preview_no_escribe(self):
        antes = self.mem.snapshot()
        out = self.preview("catalogo", CATALOGO_PUNTO_COMA)
        self.assertEqual(out["summary"]["validas"], 2)
        self.assertEqual(out["summary"]["nuevas"], 2)
        self.assertTrue(out["token"])
        self.assertEqual(self.mem.snapshot(), antes)
        self.mem.save.assert_not_called()

    def test_preview_con_errores_no_da_token(self):
        out = self.preview("catalogo", b"nombre,precio\nLoseta,consultar\nOk,1000\n")
        self.assertIsNone(out["token"])
        self.assertEqual(out["summary"]["con_error"], 1)

    def test_apply_regenera_solo_su_seccion_y_deja_el_texto_manual(self):
        self.apply(self.preview("faq", b"pregunta,respuesta\nHacen envios?,Si\n")["token"])
        self.apply(self.preview("catalogo", CATALOGO_PUNTO_COMA)["token"])
        ficha = self.mem.get_client_knowledge("piscinas-sur")
        self.assertTrue(ficha.startswith(MANUAL))
        faq_antes = onboarding.section_text(ficha, "faq")
        # Un segundo catálogo distinto: cambia su sección, nada más.
        out = self.preview("catalogo", b"sku,nombre,precio\nL-01,Loseta gris 50x50,15000\n")
        self.assertEqual(out["summary"]["se_eliminan"], 1)
        self.assertEqual(out["summary"]["cambian"], 1)
        self.apply(out["token"])
        ficha2 = self.mem.get_client_knowledge("piscinas-sur")
        self.assertTrue(ficha2.startswith(MANUAL))
        self.assertEqual(onboarding.section_text(ficha2, "faq"), faq_antes)
        self.assertIn("Loseta gris 50x50: precio $15.000.", ficha2)
        self.assertNotIn("Borde piscina", ficha2)
        precios = self.mem.get_client_pricing("piscinas-sur")["items"]
        self.assertEqual([(i["name"], i["unit_price"]) for i in precios], [("Loseta gris 50x50", 15000)])

    def test_apply_respeta_edicion_manual_hecha_despues_del_preview(self):
        token = self.preview("faq", b"pregunta,respuesta\nA?,B\n")["token"]
        self.mem.set_client_knowledge("piscinas-sur", MANUAL + "\n\nNuevo: abrimos sábados.")
        self.apply(token)
        self.assertIn("abrimos sábados", self.mem.get_client_knowledge("piscinas-sur"))

    def test_segundo_apply_es_version_nueva_y_el_rollback_la_revierte(self):
        v1 = self.apply(self.preview("faq", b"pregunta,respuesta\nA?,Uno\n")["token"])["version"]
        ficha_v1 = self.mem.get_client_knowledge("piscinas-sur")
        v2 = self.apply(self.preview("faq", b"pregunta,respuesta\nA?,Dos\n")["token"])["version"]
        self.assertEqual(v2, v1 + 1)
        motivo = self.mem.list_client_knowledge_versions("piscinas-sur")[0]["motivo"]
        self.assertEqual(motivo, "importación archivo.csv")
        api.knowledge_rollback("piscinas-sur", v1)
        self.assertEqual(self.mem.get_client_knowledge("piscinas-sur"), ficha_v1)

    def test_token_se_usa_una_vez(self):
        token = self.preview("faq", b"pregunta,respuesta\nA?,B\n")["token"]
        self.apply(token)
        with self.assertRaises(HTTPException) as ctx:
            self.apply(token)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_token_de_otro_cliente_no_sirve(self):
        self.mem.register_client("otra", "GROWTH")
        token = self.preview("faq", b"pregunta,respuesta\nA?,B\n", client="otra")["token"]
        with self.assertRaises(HTTPException) as ctx:
            self.apply(token)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_token_expirado(self):
        reloj = [1000.0]
        store = onboarding.PreviewStore(ttl=10, clock=lambda: reloj[0])
        with mock.patch.object(onboarding, "PREVIEWS", store):
            token = self.preview("faq", b"pregunta,respuesta\nA?,B\n")["token"]
            reloj[0] += 11
            with self.assertRaises(HTTPException) as ctx:
                self.apply(token)
        self.assertEqual(ctx.exception.status_code, 410)

    def test_losetaschile_preview_si_apply_409(self):
        out = self.preview("faq", b"pregunta,respuesta\nA?,B\n", client="losetaschile")
        self.assertTrue(out["token"])
        antes = self.mem.snapshot()
        with self.assertRaises(HTTPException) as ctx:
            self.apply(out["token"], client="losetaschile")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self.mem.snapshot(), antes)

    def test_archivo_sobre_el_limite_413(self):
        with self.assertRaises(HTTPException) as ctx:
            self.preview("faq", b"pregunta,respuesta\n" + b"x" * (ONBOARDING_MAX_BYTES + 1))
        self.assertEqual(ctx.exception.status_code, 413)

    def test_base64_invalido_400(self):
        with self.assertRaises(HTTPException) as ctx:
            api.onboarding_preview(self.req, "piscinas-sur", api.OnboardingPreviewBody(
                kind="faq", content_base64="no es base64!!"))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_cliente_desconocido_404_en_apply_y_status(self):
        for call in (lambda: self.apply("x", client="nadie"),
                     lambda: api.onboarding_status(self.req, "nadie")):
            with self.assertRaises(HTTPException) as ctx:
                call()
            self.assertEqual(ctx.exception.status_code, 404)

    def _status(self, whatsapp: bool):
        with mock.patch("zero.client_integrations.configured", return_value=whatsapp):
            return api.onboarding_status(self.req, "piscinas-sur")

    def test_status_sin_whatsapp_no_esta_listo(self):
        self.apply(self.preview("faq", b"pregunta,respuesta\nA?,B\n")["token"])
        self.apply(self.preview("catalogo", CATALOGO_PUNTO_COMA)["token"])
        out = self._status(False)
        self.assertFalse(out["listo"])
        items = {i["clave"]: i for i in out["items"]}
        self.assertEqual(set(items), {"ficha", "catalogo", "faq", "whatsapp_conectado", "huecos_abiertos"})
        self.assertFalse(items["whatsapp_conectado"]["ok"])
        self.assertTrue(items["whatsapp_conectado"]["accion"])
        self.assertTrue(items["catalogo"]["ok"] and items["faq"]["ok"] and items["ficha"]["ok"])

    def test_status_con_whatsapp_y_todo_cargado_esta_listo(self):
        self.apply(self.preview("faq", b"pregunta,respuesta\nA?,B\n")["token"])
        self.apply(self.preview("catalogo", CATALOGO_PUNTO_COMA)["token"])
        self.assertTrue(self._status(True)["listo"])

    def test_status_ficha_solo_importada_no_cuenta_como_ficha(self):
        self.mem.register_client("vacia", "GROWTH")
        self.apply(self.preview("faq", b"pregunta,respuesta\nA?,B\n", client="vacia")["token"],
                   client="vacia")
        with mock.patch("zero.client_integrations.configured", return_value=True):
            out = api.onboarding_status(self.req, "vacia")
        items = {i["clave"]: i for i in out["items"]}
        self.assertFalse(items["ficha"]["ok"])
        self.assertFalse(out["listo"])

    def test_rol_cco_tiene_onboarding_y_operador_no(self):
        self.assertTrue(api._role_may_access("cco", "POST", "/api/onboarding/apply"))
        self.assertTrue(api._role_may_access("cco", "GET", "/api/onboarding/status"))
        self.assertFalse(api._role_may_access("operador", "POST", "/api/onboarding/apply"))


if __name__ == "__main__":
    unittest.main()
