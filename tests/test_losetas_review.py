import os
import tempfile
import unittest
from datetime import date
from unittest import mock

from zero.losetas_budget import format_customer_budget
from zero.losetas_polls import FACTORY_ADDRESS, FACTORY_MAP_URL
from zero.losetas_review import (final_messages as _final, handle_review_message, read_owner_reply,
                                 store_review_draft)
from zero.memory import SessionMemory
from zero.whatsapp_web import parse_message
from zero.losetas_budget import _delivery_text

GROUP = "120363000000000001@g.us"
MAPS = "https://maps.app.goo.gl/5AuWWpBpix3W7CZX9"
ADDRESS = "Avenida Los Laureles, poste 104, casa 25, Limache, V Región"
KNOWLEDGE = ("# Ficha\n\n## Respuestas fijas\n### medios de pago\n"
             "Transferencia o efectivo.\nNombre: Pool Edge SpA\nRUT: 76.111.222-3\n"
             "Banco: Banco Estado\nCuenta corriente: 123456789\nCorreo: pagos@example.cl\n\n"
             "## Otra sección\nNo va.\n")
QUOTE = {"currency": "CLP", "total": 302400, "lines": [
    {"name": "Borde recto con nariz 50×50", "qty": 48, "unit_price": 6000, "subtotal": 288000},
    {"name": "Esquina piscina 50×50", "qty": 4, "unit_price": 3600, "subtotal": 14400}]}


def draft(**extra):
    return dict({"lead": "k1", "name": "marcia", "phone": "56933040685", "color": "blanco",
                 "quote": QUOTE, "issued": "2026-10-26", "text": "*PRESUPUESTO ... REVISIÓN*"},
                **extra)


def final_messages(*args):
    return _final(*args)["messages"]


def read(text, **extra):
    return read_owner_reply(text, draft(**extra))


class ReaderTest(unittest.TestCase):
    def test_shipping_variants(self):
        for text, amount, place in (
                ("despacho 80000\nfecha 30/10\ndirección X", 80000, None),
                ("Despacho $80.000", 80000, None),
                ("despacho a Limache 80000", 80000, "Limache"),
                ("Flete 80.000", 80000, None),
                ("DESPACHO A Viña del Mar $80.000", 80000, "Viña del Mar")):
            with self.subTest(text=text):
                fields = read(text)["fields"]
                self.assertEqual((fields["shipping"], fields["place"]), (amount, place))

    def test_place_deduced_from_end_of_address_only_when_sure(self):
        self.assertEqual(read(f"dirección {ADDRESS}")["fields"]["place"], "Limache")
        self.assertIsNone(read("dirección Avenida Los Laureles 25")["fields"]["place"])
        self.assertIsNone(read("dirección Calle 1, casa 25, V Región")["fields"]["place"])

    def test_date_variants(self):
        want = [date(2026, 10, 30), date(2026, 10, 31)]
        for text in ("30/10 y 31/10", "30-10 o 31-10", "fecha 30/10/2026 y 31/10/2026",
                     "viernes 30 o sábado 31 de octubre", "30 y 31 de octubre",
                     "Fecha: 30/10 o 31/10"):
            with self.subTest(text=text):
                got = read(text)
                self.assertEqual(got["fields"]["delivery"], want)
                self.assertEqual(got["problems"], [])
        self.assertEqual(read("fecha 30/10")["fields"]["delivery"], [date(2026, 10, 30)])

    def test_date_before_issue_rolls_to_next_year(self):
        self.assertEqual(read("fecha 05/01")["fields"]["delivery"], [date(2027, 1, 5)])

    def test_weekday_that_does_not_match_is_flagged(self):
        got = read("sábado 30 de octubre")
        self.assertTrue(got["problems"])
        self.assertIn("sabado", got["problems"][0])

    def test_address_link_and_pool(self):
        got = read(f"dir {ADDRESS}\nubicación {MAPS}\npiscina 4 x 8")["fields"]
        self.assertEqual(got["address"], ADDRESS)
        self.assertEqual(got["map_url"], MAPS)
        self.assertEqual(got["pool"], "4 × 8 m")
        self.assertEqual(read("direccion Calle 5")["fields"]["address"], "Calle 5")
        self.assertEqual(read("4x8 m")["fields"]["pool"], "4 × 8 m")
        self.assertEqual(read("piscina 4x8")["fields"]["pool"], "4 × 8 m")
        self.assertEqual(read("https://www.google.com/maps?q=-33.6,-70.6")["fields"]["map_url"],
                         "https://www.google.com/maps?q=-33.6,-70.6")

    def test_shared_location_is_used_when_owner_gives_no_link(self):
        got = read("despacho 5000", quote=dict(
            QUOTE, delivery_detail="Ubicación compartida: https://www.google.com/maps?q=1,2"))
        self.assertEqual(got["fields"]["map_url"], "https://www.google.com/maps?q=1,2")

    def test_pickup_needs_no_shipping_or_address(self):
        for extra, text in (({"quote": dict(QUOTE, delivery_detail="Retiro en fábrica: X")},
                             "fecha 30/10"), ({}, "retiro\n30/10")):
            got = read(text, **extra)
            self.assertTrue(got["fields"]["pickup"])
            self.assertEqual(got["missing"], [])

    def test_missing_and_unrecognized(self):
        self.assertEqual(read("despacho 80000")["missing"], ["dirección", "fecha"])
        self.assertFalse(read("gracias, lo reviso mañana")["recognized"])


FULL = f"despacho a Limache 80000\nfecha 30/10 y 31/10\ndirección {ADDRESS}\n{MAPS}\npiscina 4x8"


class MessagesTest(unittest.TestCase):
    def test_marcia(self):
        budget, payment = final_messages(draft(), read(FULL), KNOWLEDGE)
        self.assertIn("*PRESUPUESTO N° PE-261026-0685*", budget)
        self.assertIn("Despacho a Limache: $80.000", budget)
        self.assertIn("*TOTAL: $382.400*", budget)
        self.assertIn("Piscina: 4 × 8 m", budget)
        self.assertEqual(payment, (
            "Para confirmar su pedido se hace un abono de $10.000 y el resto ($372.400) se paga "
            "contra entrega, en efectivo o por transferencia.\n\nDatos para la transferencia:\n"
            "Nombre: Pool Edge SpA\nRUT: 76.111.222-3\nBanco: Banco Estado\n"
            "Cuenta corriente: 123456789\nCorreo: pagos@example.cl\n\n"
            "Cuando haga el abono, envíenos el comprobante por este chat."))

    def test_missing_bank_details(self):
        messages = final_messages(draft(), read(FULL), "# Ficha sin pagos")
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[1], "Falta en la ficha: datos de transferencia")

    def test_missing_fields_and_incoherent(self):
        self.assertEqual(final_messages(draft(), read("despacho 80000"), KNOWLEDGE),
                         ["Falta: dirección, fecha"])
        out = final_messages(draft(), read("sábado 30 de octubre\ndespacho 1\ndir X"), KNOWLEDGE)
        self.assertIn("No cuadra:", out[0])

    def test_unrecognized_is_silent(self):
        self.assertEqual(final_messages(draft(), read("ok gracias"), KNOWLEDGE), [])

    def test_pickup_budget(self):
        messages = final_messages(draft(), read("retiro\nfecha 30/10"), KNOWLEDGE)
        self.assertIn("Retiro en fábrica: sin costo", messages[0])
        self.assertIn("*TOTAL: $302.400*", messages[0])
        self.assertIn(FACTORY_ADDRESS, messages[0])
        self.assertIn("($292.400)", messages[1])


class PickupFormatTest(unittest.TestCase):
    def setUp(self):
        self.data = dict(number="PE-1", issued=date(2026, 10, 26), customer="ana",
                         phone="56912345678", address="Calle 1", color=None, pool=None,
                         shipping=5000, shipping_label="Despacho", delivery=[date(2026, 10, 30)],
                         deposit=10000, map_url="https://maps.app.goo.gl/x")

    def test_default_output_unchanged_and_pickup_replaces_shipping(self):
        normal = format_customer_budget(QUOTE, **self.data)
        self.assertEqual(normal, format_customer_budget(QUOTE, pickup=False, **self.data))
        self.assertIn("Despacho: $5.000", normal)
        text = format_customer_budget(QUOTE, pickup=True, **self.data)
        lines = text.splitlines()
        self.assertIn("Retiro en fábrica: sin costo", lines)
        self.assertNotIn("Despacho: $5.000", lines)
        self.assertIn(FACTORY_ADDRESS, lines[lines.index("*Entrega*"):])
        self.assertIn(f"Ubicación: {FACTORY_MAP_URL}", lines)
        self.assertNotIn("Calle 1", text)


class ParseTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": GROUP})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.payload = {"kind": "review_group", "id": "m1", "chat_id": GROUP, "from_me": True,
                        "sent_by_bridge": False, "author": None, "text": "despacho 1",
                        "quoted_id": "q1", "quoted_text": "t", "timestamp": 1,
                        "to_phone_id": "56911111111"}

    def test_review_payload(self):
        got = parse_message(self.payload, ["zeroai", "losetaschile"])
        self.assertEqual((got["client"], got["quoted_id"], got["kind"]),
                         ("losetaschile", "q1", "review_group"))

    def test_ignored(self):
        clients = ["losetaschile"]
        for change in ({"sent_by_bridge": True}, {"chat_id": "120363999@g.us"},
                       {"text": "*PRESUPUESTO N° 1"}, {"text": "*POOLEDGE*\nx"},
                       {"text": "Para confirmar su pedido se hace"}, {"id": ""}):
            with self.subTest(change=change):
                self.assertIsNone(parse_message({**self.payload, **change}, clients))
        self.assertIsNone(parse_message(self.payload, ["otro"]))

    def test_customer_messages_unchanged(self):
        base = {"id": "a", "from": "56912345678", "to_phone_id": "56987654321", "text": "hola",
                "chat_id": "56912345678@c.us"}
        self.assertEqual(parse_message(base)["from"], "56912345678")
        self.assertIsNone(parse_message({**base, "chat_id": GROUP}, ["losetaschile"]))
        self.assertIsNone(parse_message({**base, "kind": "x", "from": ""}, ["losetaschile"]))


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.memory = SessionMemory(None)
        self.memory.clients["losetaschile"] = {}
        self.memory.set_client_knowledge("losetaschile", KNOWLEDGE) \
            if hasattr(self.memory, "set_client_knowledge") else \
            self.memory.clients["losetaschile"].update(knowledge=KNOWLEDGE)
        store_review_draft(self.memory, "losetaschile", "G1", draft())

    def reply(self, text, **extra):
        message = {"kind": "review_group", "client": "losetaschile", "id": "r1",
                   "chat_id": GROUP, "text": text, "to_phone_id": "56911111111",
                   "quoted_id": "G1", "quoted_text": ""}
        message.update(extra)
        with mock.patch("zero.whatsapp_web.send_group_text",
                        return_value={"id": "x", "ack": 1}) as send, \
                mock.patch("zero.losetas_review.today", return_value=date(2026, 10, 26)):
            handle_review_message(self.memory, message)
        return send

    def test_draft_is_stored_and_trimmed(self):
        stored = self.memory.clients["losetaschile"]["review_drafts"]["G1"]
        self.assertEqual((stored["phone"], stored["status"]), ("56933040685", "pending"))
        for n in range(60):
            store_review_draft(self.memory, "losetaschile", f"X{n}", draft(text=f"t{n}"))
        self.assertEqual(len(self.memory.clients["losetaschile"]["review_drafts"]), 50)

    def test_full_reply_publishes_two_messages_in_the_group(self):
        send = self.reply(FULL)
        self.assertEqual(send.call_count, 2)
        for call in send.call_args_list:
            self.assertEqual(call.args[:3], ("losetaschile", "56911111111", GROUP))
        self.assertIn("*TOTAL: $382.400*", send.call_args_list[0].args[3])
        self.assertIn("($372.400)", send.call_args_list[1].args[3])
        self.assertEqual([a["action"] for a in self.memory.actions], ["final_budget_ready"])
        self.assertEqual(self.memory.actions[0]["total"], 382400)
        self.assertEqual(self.memory.clients["losetaschile"]["review_drafts"]["G1"]["status"],
                         "final_published")

    def test_found_by_quoted_text_and_second_reply_corrects(self):
        self.assertEqual(self.reply(FULL, quoted_id="", quoted_text="PRESUPUESTO ... REVISIÓN"
                                    ).call_count, 2)
        fixed = FULL.replace("80000", "90000")
        send = self.reply(fixed, id="r2")
        self.assertIn("*TOTAL: $392.400*", send.call_args_list[0].args[3])

    def test_missing_data_posts_one_short_line(self):
        send = self.reply("despacho 80000")
        send.assert_called_once()
        self.assertEqual(send.call_args.args[3], "Falta: dirección, fecha")

    def test_no_quote_or_unknown_quote_or_no_fields_is_silent(self):
        self.reply(FULL, quoted_id="", quoted_text="").assert_not_called()
        self.reply(FULL, quoted_id="ZZ").assert_not_called()
        self.reply("gracias").assert_not_called()

    def test_bridge_error_is_logged_not_retried(self):
        message = {"client": "losetaschile", "id": "r", "chat_id": GROUP, "text": FULL,
                   "to_phone_id": "56911111111", "quoted_id": "G1", "quoted_text": ""}
        with mock.patch("zero.whatsapp_web.send_group_text",
                        side_effect=RuntimeError("Puente WhatsApp Web: HTTP 502")) as send, \
                mock.patch("zero.losetas_review.today", return_value=date(2026, 10, 26)):
            handle_review_message(self.memory, message)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.memory.actions[0]["action"], "review_group_send_uncertain")


class ReviewFixesTest(unittest.TestCase):
    def test_sizes_and_time_slots_are_not_dates(self):
        got = read("Piscina 4x8, entrega jueves 29 de octubre")["fields"]["delivery"]
        self.assertEqual(got, [date(2026, 10, 29)])
        got = read("entrega 29-10 entre 10-12 hrs")["fields"]["delivery"]
        self.assertEqual(got, [date(2026, 10, 29)])
        self.assertEqual(read("llevar 8 cajas el 30 de octubre")["fields"]["delivery"],
                         [date(2026, 10, 30)])

    def test_pickup_only_from_line_or_draft(self):
        self.assertFalse(read("no es retiro\nfecha 30/10")["fields"]["pickup"])
        self.assertTrue(read("Retiro en fábrica\n30/10")["fields"]["pickup"])
        got = read("retiro\ndespacho 80000\n30/10")
        self.assertEqual(final_messages(draft(), got, KNOWLEDGE),
                         ["No cuadra: despacho y retiro a la vez"])

    def test_recent_past_date_is_a_problem_far_past_rolls_over(self):
        got = read("fecha 20/10")
        self.assertIn("fecha anterior a hoy (20/10)", got["problems"])
        self.assertEqual(read("fecha 05/01")["fields"]["delivery"], [date(2027, 1, 5)])

    def test_shipping_amount(self):
        for text, amount in (("Despacho Maipú $25.000 (2 viajes)", 25000),
                             ("despacho 25 mil", 25000), ("flete 25.000", 25000),
                             ("despacho 80000", 80000)):
            with self.subTest(text=text):
                self.assertEqual(read(text)["fields"]["shipping"], amount)
        for text in ("despacho 25", "despacho 2 viajes"):
            with self.subTest(text=text):
                got = read(text)
                self.assertIn("monto de despacho", got["problems"])
                self.assertIsNone(got["fields"]["shipping"])

    def test_three_dates_are_all_listed(self):
        days = [date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)]
        self.assertEqual(_delivery_text(days), "Lunes 2, martes 3 o miércoles 4 de noviembre")
        self.assertEqual(_delivery_text(days[:2]), "Lunes 2 o martes 3 de noviembre")

    def test_agent_posts_and_unconfigured_phone(self):
        with mock.patch.dict(os.environ, {"LOSETASCHILE_REVIEW_GROUP_ID": GROUP}):
            base = {"kind": "review_group", "id": "m", "chat_id": GROUP,
                    "to_phone_id": "56911111111"}
            for text in ("Falta: fecha", "No cuadra: x", "Falta en la ficha: datos"):
                self.assertIsNone(parse_message({**base, "text": text}, ["losetaschile"]))
            with self.assertLogs(level="WARNING"):
                self.assertIsNone(parse_message(
                    {**base, "text": "x", "to_phone_id": ""}, ["losetaschile"]))


class FollowupFlowTest(FlowTest):
    def post(self, text, **extra):
        message = {"client": "losetaschile", "id": "r", "chat_id": GROUP, "text": text,
                   "to_phone_id": "56911111111", "quoted_id": "G1", "quoted_text": ""}
        message.update(extra)
        sent = []

        def fake(client, account, group, body):
            sent.append(body)
            return {"id": f"bot{len(sent)}{len(self.memory.actions)}", "ack": 1}
        with mock.patch("zero.whatsapp_web.send_group_text", side_effect=fake), \
                mock.patch("zero.losetas_review.today", return_value=date(2026, 10, 26)):
            handle_review_message(self.memory, message)
        return sent

    def test_answer_to_falta_combines_with_earlier_data(self):
        first = self.post("despacho a Limache 80000\nfecha 30/10")
        self.assertEqual(first, ["Falta: dirección"])
        index = self.memory.clients["losetaschile"]["review_draft_index"]
        bot_id = next(k for k, v in index.items() if k.startswith("bot"))
        second = self.post(f"dirección {ADDRESS}", quoted_id=bot_id)
        self.assertEqual(len(second), 2)
        self.assertIn("Despacho a Limache: $80.000", second[0])
        self.assertIn("*TOTAL: $382.400*", second[0])
        by_text = self.post("despacho 90000", quoted_id="", quoted_text="Falta: dirección")
        self.assertEqual(len(by_text), 2)
        self.assertIn("$90.000", by_text[0])

    def test_issue_date_is_the_day_the_final_is_made(self):
        sent = self.post(FULL)
        self.assertIn("Emitido el 26 de octubre de 2026", sent[0])

    def test_stops_at_first_failure_and_always_saves(self):
        saves = []
        self.memory.save = lambda: saves.append(1)
        with mock.patch("zero.whatsapp_web.send_group_text",
                        side_effect=RuntimeError("HTTP 502")) as send, \
                mock.patch("zero.losetas_review.today", return_value=date(2026, 10, 26)):
            handle_review_message(self.memory, {
                "client": "losetaschile", "id": "r", "chat_id": GROUP, "text": FULL,
                "to_phone_id": "56911111111", "quoted_id": "G1", "quoted_text": ""})
        self.assertEqual((send.call_count, len(saves)), (1, 1))
        self.assertEqual(self.memory.clients["losetaschile"]["review_drafts"]["G1"]["status"],
                         "needs_data")
        self.assertNotIn("final_budget_ready", [a["action"] for a in self.memory.actions])

    def test_budget_without_bank_data_is_not_final(self):
        self.memory.clients["losetaschile"].pop("knowledge", None)
        with mock.patch.object(self.memory, "get_client_knowledge", return_value="x"):
            sent = self.post(FULL)
        self.assertEqual(sent[1], "Falta en la ficha: datos de transferencia")
        self.assertEqual(self.memory.clients["losetaschile"]["review_drafts"]["G1"]["status"],
                         "budget_sent")
        self.assertNotIn("final_budget_ready", [a["action"] for a in self.memory.actions])


if __name__ == "__main__":
    unittest.main()
