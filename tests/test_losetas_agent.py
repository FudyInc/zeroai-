"""El agente que conduce: el modelo decide, el código calcula, ejecuta y revisa.

Casos reales de la auditoría 2026-11-20 (anonimizados): el flujo fijo contestaba
«¿Qué producto está buscando?» a «¿cuánto sale enviar a Antofagasta?», y el modelo
solo inventó una dirección de la fábrica. Ninguna prueba llama a Claude.
"""
import os
import unittest
from unittest import mock

from zero.agents import build_agents
from zero.config import LOSETASCHILE_AGENT
from zero.crm import CRM
from zero.losetas_agent import UBICACION, responder, revisar_respuesta
from zero.memory import SessionMemory
from zero.orchestrator import Zero

PRICING = {"currency": "CLP", "iva_rate": 0, "items": [
    {"id": "borde-recto-nariz-50x50", "name": "Borde recto con nariz 50x50", "unit_price": 6000, "unit": "unidad"},
    {"id": "borde-ballena-50x40", "name": "Borde ballena 50x40", "unit_price": 5500, "unit": "unidad"},
    {"id": "esquina-piscina-50x50", "name": "Esquina piscina 50x50", "unit_price": 3800, "unit": "unidad"},
    {"id": "pastelones-40x40", "name": "Pastelones 40x40", "unit_price": 1600, "unit": "unidad"}]}
FICHA = "Vendemos bordes y pastelones. No hacemos instalación. Compra mínima regiones $200.000."
PHONE, BOT, CHAT, GROUP = "56900000002", "56911111111", "56900000002@c.us", "123@g.us"


def modelo(*salidas):
    """Un Claude simulado que devuelve `salidas` en orden y anota lo que recibió."""
    llamadas = []

    def llamar(system, user):
        llamadas.append((system, user))
        return salidas[min(len(llamadas), len(salidas)) - 1]
    llamar.llamadas = llamadas
    return llamar


def res_de(salida, **kw):
    return responder(kw.pop("mensaje", "Hola"), kw.pop("historial", []), knowledge=FICHA,
                     pricing_raw=PRICING, nombres=kw.pop("nombres", ["Elizabeth"]),
                     llamar=modelo(*salida) if isinstance(salida, tuple) else modelo(salida))


class RevisionTest(unittest.TestCase):
    def revisar(self, texto):
        return revisar_respuesta(texto, knowledge=FICHA, pricing=PRICING, nombres=["Elizabeth"])

    def test_respuestas_normales_pasan(self):
        for texto in ("Buenas noches. ¿Cuáles son las medidas de su piscina?",
                      "El borde recto con nariz 50x50 vale $6.000 la unidad.",
                      "Para regiones la compra mínima es de $200.000."):
            with self.subTest(texto=texto):
                self.assertEqual(self.revisar(texto), [])

    def test_bloquea_lo_que_no_puede_salir(self):
        for texto in ("Buenas noches, Elizabeth. ¿Qué busca?",            # nombre
                      "Nuestra fábrica está en Av. Américo Vespucio Sur 3200",  # dirección inventada
                      "Le hacemos el borde a $4.900",                      # precio fuera de lista
                      "Estaría listo en 5 días hábiles",                    # plazo sin respaldo
                      "Necesita 42 bordes y 4 esquinas",                    # cantidad calculada por el modelo
                      "Lo reviso y le confirmo",                            # aviso de revisión
                      "Soy un bot de PoolEdge",
                      "1. Bordes\n2. Pastelones"):
            with self.subTest(texto=texto):
                self.assertTrue(self.revisar(texto))


class AccionesTest(unittest.TestCase):
    def test_saludo_de_anuncio_pide_medidas_y_manda_catalogo(self):
        res = res_de({"mensaje": "Buenas noches. ¿Cuáles son las medidas de su piscina?",
                      "acciones": [{"tipo": "catalogo_bordes"}]}, mensaje="¡Hola! Quiero más información")
        self.assertEqual(res["catalog_document"]["category"], "bordes")
        self.assertTrue(res["reply_after_document"])
        self.assertIn("medidas", res["reply"])

    def test_la_direccion_la_pone_el_codigo(self):
        res = res_de({"mensaje": "Estamos en La Pintana.", "acciones": [{"tipo": "ubicacion"}]})
        self.assertIn(UBICACION, res["reply"])

    def test_presupuesto_de_bordes_lo_calcula_el_codigo(self):
        res = res_de({"mensaje": "", "acciones": [{
            "tipo": "presupuesto_bordes", "modelo": "Borde recto con nariz 50x50",
            "largo_m": 7, "ancho_m": 3.4, "forma": "rectangular", "color": "Gris", "entrega": "retiro"}]})
        lineas = {linea["id"]: linea["qty"] for linea in res["quote"]["lines"]}
        self.assertEqual(lineas, {"borde-recto-nariz-50x50": 42, "esquina-piscina-50x50": 4})
        self.assertIn("redondeadas", res["quote"]["review_notes"][0])
        self.assertTrue(res["quote"]["delivery_detail"].startswith("Retiro"))
        self.assertEqual(res["selected_tone"], "Gris")

    def test_piscina_no_rectangular_se_deriva(self):
        res = res_de({"mensaje": "", "acciones": [{
            "tipo": "presupuesto_bordes", "modelo": "Borde ballena 50x40",
            "largo_m": 8, "ancho_m": 4, "forma": "otra"}]})
        self.assertEqual(res["intent"], "handoff")
        self.assertNotIn("quote", res)

    def test_pastelones_van_al_grupo_con_su_precio(self):
        res = res_de({"mensaje": "", "acciones": [{
            "tipo": "presupuesto_pastelones", "modelo": "Laja española", "m2": 14}]})
        self.assertEqual(res["paver_order"]["area_m2"], "14")
        self.assertEqual(res["paver_order"]["unit_price"], 1600)

    def test_derivar_sin_respuesta_queda_en_silencio(self):
        res = res_de({"mensaje": "", "acciones": [{"tipo": "derivar", "motivo": "Flete a Antofagasta"}]})
        self.assertEqual((res["intent"], res["reply"]), ("handoff", ""))
        self.assertEqual(res["review_reason"], "Flete a Antofagasta")

    def test_responde_y_deriva_lo_que_falta(self):
        res = res_de({"mensaje": "Para regiones la compra mínima es de $200.000.",
                      "acciones": [{"tipo": "derivar", "motivo": "Costo de flete a Valdivia"}]})
        self.assertTrue(res["reply"])
        self.assertEqual(res["attention"], "Costo de flete a Valdivia")

    def test_respuesta_bloqueada_se_corrige_una_vez(self):
        mala = {"mensaje": "Buenas noches, Elizabeth.", "acciones": []}
        buena = {"mensaje": "Buenas noches. ¿Qué está buscando?", "acciones": []}
        llamar = modelo(mala, buena)
        res = responder("Hola", [], knowledge=FICHA, pricing_raw=PRICING, nombres=["Elizabeth"],
                        llamar=llamar)
        self.assertEqual(res["reply"], buena["mensaje"])
        self.assertIn("nombre del cliente", llamar.llamadas[1][1])

    def test_si_sigue_mal_no_se_envia(self):
        mala = {"mensaje": "Le confirmo en 5 días", "acciones": []}
        res = res_de((mala, mala))
        self.assertEqual((res["intent"], res["reply"]), ("handoff", ""))

    def test_falla_del_modelo_no_llega_al_cliente(self):
        def roto(system, user):
            raise RuntimeError("sin saldo")
        res = responder("Hola", [], knowledge=FICHA, pricing_raw=PRICING, nombres=[], llamar=roto)
        self.assertEqual((res["intent"], res["reply"]), ("handoff", ""))

    def test_el_modelo_ve_el_chat_completo_y_la_ficha(self):
        historial = [{"role": "lead", "text": f"mensaje {i}"} for i in range(30)]
        llamar = modelo({"mensaje": "Ok.", "acciones": []})
        responder("¿y?", historial, knowledge=FICHA, pricing_raw=PRICING, nombres=[], llamar=llamar)
        system, user = llamar.llamadas[0]
        self.assertIn(FICHA, system)
        self.assertIn("mensaje 0", user)
        self.assertIn("$6.000", system)


class OrquestadorTest(unittest.TestCase):
    """El agente reemplaza los pasos fijos; envío y grupo siguen igual."""

    def setUp(self):
        LOSETASCHILE_AGENT["modo"] = "conduce"
        self.addCleanup(LOSETASCHILE_AGENT.__setitem__, "modo", "flujo")

    def chat(self, salidas, mensajes):
        memory = SessionMemory(None)
        memory.register_client("losetaschile", "STARTER")
        memory.set_client_agent_profile("losetaschile", {"whatsapp_number": BOT, "response_mode": "automatic"})
        memory.set_client_pricing("losetaschile", PRICING)
        memory.set_client_knowledge("losetaschile", FICHA)
        crm = CRM(None)
        crm.upsert("losetaschile", {"phone": PHONE, "source": "test"})
        zero = Zero(build_agents(mock=True), memory=memory, crm=crm)
        zero._deliver = mock.Mock(return_value={"status": "sent", "via": "whatsapp_web"})
        sent = {"id": "x", "ack": 0}
        llamar = modelo(*salidas)
        with mock.patch("zero.losetas_agent._llamar_claude", llamar), \
                mock.patch("zero.whatsapp_web.send_catalog_document", return_value=sent) as doc, \
                mock.patch("zero.whatsapp_web.send_catalog_image", return_value=sent), \
                mock.patch("zero.whatsapp_web.send_group_text", return_value={"id": "g1", "ack": 0}) as group, \
                mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": GROUP}), \
                mock.patch.object(zero, "dispatch"):
            for texto in mensajes:
                zero.handle_inbound(PHONE, texto, to_phone_id=BOT, whatsapp_chat_id=CHAT)
        bodies = [call.args[3]["body"] for call in zero._deliver.call_args_list]
        return bodies, doc, group, llamar

    def test_pregunta_de_despacho_se_responde_no_se_reinicia_el_menu(self):
        respuesta = "Para regiones la compra mínima es de $200.000; el flete se cotiza con transporte."
        bodies, _, _, llamar = self.chat(
            [{"mensaje": respuesta, "acciones": []}],
            ["¿Cuánto sale enviar a Antofagasta? La piscina es de 7,50 x 3,50"])
        self.assertEqual(bodies, [respuesta])
        self.assertEqual(len(llamar.llamadas), 1)

    def test_catalogo_y_pregunta(self):
        bodies, doc, _, _ = self.chat(
            [{"mensaje": "Buenas noches. ¿Cuáles son las medidas de su piscina?",
              "acciones": [{"tipo": "catalogo_bordes"}]}],
            ["¡Hola! Quiero más información"])
        self.assertEqual(doc.call_count, 1)
        self.assertEqual(bodies, ["Buenas noches. ¿Cuáles son las medidas de su piscina?"])

    def test_presupuesto_va_al_grupo_y_no_al_cliente(self):
        bodies, _, group, _ = self.chat(
            [{"mensaje": "", "acciones": [{
                "tipo": "presupuesto_bordes", "modelo": "Borde recto con nariz 50x50",
                "largo_m": 7, "ancho_m": 3.5, "forma": "rectangular", "color": "Gris",
                "entrega": "retiro"}]}],
            ["Borde con nariz 50x50 gris, piscina 7 x 3,5, retiro yo"])
        self.assertEqual(group.call_count, 1)
        self.assertIn("42", group.call_args.args[3])
        self.assertEqual(bodies, [])

    def test_presupuesto_con_respuesta_manda_solo_la_respuesta(self):
        bodies, _, group, _ = self.chat(
            [{"mensaje": "Puede retirar en la fábrica.", "acciones": [{"tipo": "ubicacion"}, {
                "tipo": "presupuesto_bordes", "modelo": "Borde recto con nariz 50x50",
                "largo_m": 7, "ancho_m": 3.5, "forma": "rectangular", "entrega": "retiro"}]}],
            ["Presupuesto para eso y dónde se retira"])
        self.assertEqual(group.call_count, 1)
        self.assertEqual(len(bodies), 1)
        self.assertIn("Los Granados 029", bodies[0])
        self.assertNotIn("42", bodies[0])

    def test_no_repite_el_catalogo_ya_enviado(self):
        historial = [{"role": "agent", "text": "Catálogo Bordes de Piscina"}]
        res = res_de({"mensaje": "¿Qué modelo le interesa?", "acciones": [{"tipo": "catalogo_bordes"}]},
                     mensaje="7x4", historial=historial)
        self.assertNotIn("catalog_document", res)
        res = res_de({"mensaje": "Se lo reenvío.", "acciones": [{"tipo": "catalogo_bordes"}]},
                     mensaje="¿me manda el catálogo de nuevo?", historial=historial)
        self.assertEqual(res["catalog_document"]["category"], "bordes")

    def test_derivacion_no_avisa_al_cliente(self):
        bodies, _, _, _ = self.chat(
            [{"mensaje": "", "acciones": [{"tipo": "derivar", "motivo": "Garantía"}]}],
            ["¿Qué garantía tienen?"])
        self.assertEqual(bodies, [])

    def test_presupuesto_repetido_no_vuelve_al_grupo(self):
        # Prueba del 2026-11-21: «hola, quiero más información» días después del pedido.
        presupuesto = {"tipo": "presupuesto_bordes", "modelo": "Borde recto con nariz 50x50",
                       "largo_m": 7, "ancho_m": 3.5, "forma": "rectangular", "color": "Gris",
                       "entrega": "retiro"}
        bodies, _, group, _ = self.chat(
            [{"mensaje": "", "acciones": [presupuesto]},
             {"mensaje": "", "acciones": [presupuesto]},
             {"mensaje": "Buenas tardes. ¿En qué le puedo ayudar?", "acciones": [presupuesto]}],
            ["Borde con nariz gris, 7 x 3,5, retiro", "Hola quiero más información", "Hola"])
        self.assertEqual(group.call_count, 1)
        self.assertEqual(bodies, ["Buenas tardes. ¿En qué le puedo ayudar?"])

    def test_presupuesto_que_cambia_si_vuelve_al_grupo(self):
        base = {"tipo": "presupuesto_bordes", "modelo": "Borde recto con nariz 50x50",
                "forma": "rectangular", "color": "Gris", "entrega": "retiro"}
        _, _, group, _ = self.chat(
            [{"mensaje": "", "acciones": [{**base, "largo_m": 7, "ancho_m": 3.5}]},
             {"mensaje": "", "acciones": [{**base, "largo_m": 8, "ancho_m": 4}]}],
            ["7 x 3,5 gris retiro", "perdón, es 8 x 4"])
        self.assertEqual(group.call_count, 2)


class AjustesConversacionTest(unittest.TestCase):
    def test_ubicacion_va_antes_de_la_pregunta(self):
        res = res_de({"mensaje": "Somos de Santiago.\n\n¿De qué comuna es usted?",
                      "acciones": [{"tipo": "ubicacion"}]}, mensaje="¿De dónde son?")
        self.assertEqual(res["reply"], "Somos de Santiago.\n\n" + UBICACION + "\n\n¿De qué comuna es usted?")

    def test_pedido_grande_no_menciona_compra_minima(self):
        res = res_de({"mensaje": "Perfecto. Para regiones la compra mínima es de $200.000. "
                                 "Con esto le preparamos el presupuesto.",
                      "acciones": [{"tipo": "presupuesto_bordes", "modelo": "Borde recto con nariz 50x50",
                                    "largo_m": 7.5, "ancho_m": 4.5, "forma": "rectangular",
                                    "color": "Gris", "entrega": "despacho a Litueche"}]},
                     mensaje="Litueche")
        self.assertNotIn("mínima", res["reply"])
        self.assertIn("le preparamos el presupuesto", res["reply"])

    def test_pedido_chico_conserva_compra_minima(self):
        res = res_de({"mensaje": "Para regiones la compra mínima es de $200.000.", "acciones": []},
                     mensaje="¿despachan a Arica?")
        self.assertIn("mínima", res["reply"])

    def test_opciones_una_por_linea_pasan_la_revision(self):
        texto = ("¿Qué modelo de borde le interesa?\n\n• Recto con nariz 50x50\n"
                 "• Ballena 50x40\n• Ballena nariz 50x50")
        self.assertEqual(revisar_respuesta(texto, knowledge=FICHA, pricing=PRICING, nombres=[]), [])


class ExtensionYPesoTest(unittest.TestCase):
    def test_extension_como_la_cotizo_diego(self):
        from decimal import Decimal
        from zero.losetas_agent import piezas_extension
        self.assertEqual(piezas_extension(Decimal("8.5"), Decimal("3"), Decimal("0.4"), 1), 57)
        self.assertEqual(piezas_extension(Decimal("8.5"), Decimal("3"), Decimal("0.4"), 0), 0)

    def test_presupuesto_ballena_con_extension_y_peso(self):
        pricing = {**PRICING, "items": PRICING["items"] + [
            {"id": "esquina-borde-ballena-50x40", "name": "Esquina borde ballena 50x40", "unit_price": 5500, "unit": "unidad"},
            {"id": "extension-borde-piscina", "name": "Extensión borde piscina", "unit_price": 3800, "unit": "unidad"}]}
        res = responder("Ballena, 8,5 x 3, una corrida, blanco, retiro", [], knowledge=FICHA,
                        pricing_raw=pricing, nombres=[], llamar=modelo({"mensaje": "", "acciones": [{
                            "tipo": "presupuesto_bordes", "modelo": "Borde ballena 50x40", "largo_m": 8.5,
                            "ancho_m": 3, "forma": "rectangular", "color": "Blanco", "entrega": "retiro",
                            "corridas_extension": 1}]}))
        lineas = {l["id"]: l["qty"] for l in res["quote"]["lines"]}
        self.assertEqual(lineas, {"borde-ballena-50x40": 46, "esquina-borde-ballena-50x40": 4,
                                  "extension-borde-piscina": 57})
        self.assertEqual(res["quote"]["total"], 46 * 5500 + 4 * 5500 + 57 * 3800)
        self.assertIn("Peso estimado sin esquinas: 1.339 kg.", " ".join(res["quote"]["review_notes"]))


class FechasTest(unittest.TestCase):
    def test_el_modelo_ve_la_fecha_de_cada_mensaje(self):
        from datetime import datetime, timezone
        llamar = modelo({"mensaje": "Buenas tardes.", "acciones": []})
        responder("Hola", [{"role": "lead", "text": "7x3 gris", "at": "2026-11-19T00:50:00+00:00"}],
                  knowledge=FICHA, pricing_raw=PRICING, nombres=[], llamar=llamar,
                  ahora=datetime(2026, 11, 21, 15, 20, tzinfo=timezone.utc))
        user = llamar.llamadas[0][1]
        self.assertIn("[18/11 21:50] CLIENTE: 7x3 gris", user)
        self.assertIn("NUEVO MENSAJE DEL CLIENTE (21/11 12:20)", user)


class PartesPropiasTest(unittest.TestCase):
    def test_partes_de_una_respuesta_dividida_son_del_agente(self):
        # Prueba del 2026-11-21: «Buenas tardes.» enviado en partes pausó el chat.
        from zero.config import WHATSAPP_HUMAN_DELIVERY as cfg
        from zero.orchestrator import _agent_sent_texts
        from zero.whatsapp_format import format_whatsapp_reply, split_whatsapp_parts
        texto = ("Buenas tardes.\n\nLe envío nuestro catálogo de bordes de piscina.\n\n"
                 "¿Qué medidas tiene su piscina (largo y ancho)? Así le preparamos el presupuesto.")
        conocidos = _agent_sent_texts([{"role": "agent", "text": texto}])
        partes = split_whatsapp_parts(format_whatsapp_reply(texto), cfg["max_parts"], cfg["min_split_chars"])
        self.assertEqual(len(partes), 3)
        for parte in partes:
            self.assertIn(" ".join(parte.split()), conocidos)
        self.assertNotIn("Sí, se lo envío hoy", conocidos)
        self.assertEqual(_agent_sent_texts([{"role": "lead", "text": texto}]), set())


if __name__ == "__main__":
    unittest.main()
