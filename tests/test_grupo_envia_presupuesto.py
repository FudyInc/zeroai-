"""Diego responde el borrador en el grupo y el presupuesto final le llega al cliente.

Diego, 2026-11-22: «una vez que se reúnan los datos, que lo envíes al grupo y preguntes
por fecha y costo de despacho o fecha de retiro; según digan en el grupo». Su respuesta
es la revisión humana: sin ella no sale nada al cliente.
"""
import unittest
from datetime import date
from unittest import mock

import zero.config as config
from zero.losetas_budget import format_internal_budget
from zero.losetas_review import handle_review_message, store_review_draft
from zero.memory import SessionMemory
from zero.quotes import compute_quote

PRICING = {"currency": "CLP", "iva_rate": 0, "items": [
    {"id": "borde-recto-nariz-50x50", "name": "Borde recto con nariz 50x50", "unit_price": 6000, "unit": "unidad"},
    {"id": "esquina-piscina-50x50", "name": "Esquina piscina 50x50", "unit_price": 3800, "unit": "unidad"}]}
FICHA = """## Respuestas fijas
### medios de pago
Aceptamos transferencia y efectivo.

Datos para la transferencia:
Nombre: Titular Prueba
RUT: 11.111.111-1
Banco: Banco Prueba
Cuenta Corriente: 123
Correo: prueba@example.com
"""
PHONE, CHAT, GROUP, BOT = "56900000002", "123456789012@lid", "999@g.us", "56911111111"


class GrupoEnviaPresupuestoTest(unittest.TestCase):
    def setUp(self):
        config.LOSETASCHILE_AUTO_SEND_REVIEWED_BUDGET = True
        self.addCleanup(setattr, config, "LOSETASCHILE_AUTO_SEND_REVIEWED_BUDGET", False)
        self.memory = SessionMemory(None)
        self.memory.register_client("losetaschile", "STARTER")
        self.memory.set_client_knowledge("losetaschile", FICHA)
        patcher = mock.patch("zero.losetas_review.today", return_value=date(2026, 11, 22))
        patcher.start()
        self.addCleanup(patcher.stop)

    def borrador(self, entrega):
        quote = compute_quote(PRICING, [{"id": "borde-recto-nariz-50x50", "qty": 42},
                                        {"id": "esquina-piscina-50x50", "qty": 4}])
        quote["delivery_detail"] = entrega
        text = format_internal_budget(quote, profile_name="Cliente Prueba", phone=PHONE, tone="Gris")
        store_review_draft(self.memory, "losetaschile", "true_999@g.us_AAA_1", {
            "lead": PHONE, "name": "Cliente Prueba", "phone": PHONE, "chat_id": CHAT,
            "color": "Gris", "quote": quote, "issued": "2026-11-22", "text": text})
        return text

    def responder(self, texto, falla=False):
        enviado = {"id": "c1", "ack": 0}
        with mock.patch("zero.whatsapp_web.bridge_request",
                        side_effect=RuntimeError("sin puente") if falla else None,
                        return_value=enviado) as cliente, \
                mock.patch("zero.whatsapp_web.send_group_text", return_value={"id": "g9", "ack": 0}) as grupo:
            handle_review_message(self.memory, {
                "client": "losetaschile", "id": "m1", "chat_id": GROUP, "to_phone_id": BOT,
                "quoted_id": "true_999@g.us_AAA_1", "quoted_text": "", "text": texto})
        return cliente, grupo

    def test_el_borrador_pregunta_lo_que_falta(self):
        self.assertIn("*¿Fecha de retiro?*",
                      self.borrador("Retiro en fábrica: Los Granados 029, La Pintana"))
        self.assertIn("*¿Costo y fecha de despacho?*", self.borrador("Despacho: Maipú"))

    def test_retiro_con_fecha_sale_al_cliente(self):
        self.borrador("Retiro en fábrica: Los Granados 029, La Pintana")
        cliente, grupo = self.responder("Fecha: 7/12")
        textos = [llamada.args[1]["text"] for llamada in cliente.call_args_list]
        self.assertEqual(len(textos), 2)
        self.assertIn("*PRESUPUESTO N° PE-221126-0002*", textos[0])
        self.assertIn("Retiro en fábrica: sin costo", textos[0])
        self.assertIn("abono de $10.000", textos[1])
        self.assertTrue(all(ll.args[1]["chat_id"] == CHAT for ll in cliente.call_args_list))
        self.assertEqual(grupo.call_count, 1)
        self.assertIn("✅ Enviado al cliente", grupo.call_args.args[3])
        draft = self.memory.clients["losetaschile"]["review_drafts"]["true_999@g.us_AAA_1"]
        self.assertEqual(draft["status"], "final_published")
        self.assertEqual(len([t for t in self.memory.get_conversation("losetaschile", PHONE)
                              if t["role"] == "agent"]), 2)

    def test_despacho_usa_la_ubicacion_que_dio_el_cliente(self):
        self.borrador("Despacho: https://www.google.com/maps?q=-33.5,-70.7")
        cliente, _ = self.responder("Despacho $20.000\nFecha: 3/12")
        presupuesto = cliente.call_args_list[0].args[1]["text"]
        self.assertIn("$20.000", presupuesto)
        self.assertIn("https://www.google.com/maps?q=-33.5,-70.7", presupuesto)

    def test_falta_un_dato_no_sale_nada(self):
        self.borrador("Despacho: Maipú")
        cliente, grupo = self.responder("Fecha: 3/12")
        cliente.assert_not_called()
        self.assertIn("Falta: despacho", grupo.call_args.args[3])

    def test_si_falla_el_envio_queda_en_el_grupo(self):
        self.borrador("Retiro en fábrica: Los Granados 029, La Pintana")
        _, grupo = self.responder("Fecha: 7/12", falla=True)
        textos = [llamada.args[3] for llamada in grupo.call_args_list]
        self.assertIn("No se pudo enviar al cliente", textos[0])
        self.assertIn("*PRESUPUESTO N°", textos[1])
        self.assertIn("abono de $10.000", textos[2])


if __name__ == "__main__":
    unittest.main()
