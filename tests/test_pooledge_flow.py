"""Flujo completo fase 2 (confirmado -> vista previa -> ok -> planilla) con fakes, sin red."""
from __future__ import annotations

import json
import os
import unittest
from datetime import date, timedelta
from unittest import mock

from tests.test_losetas_review import FULL, GROUP, KNOWLEDGE, QUOTE, draft
from zero import losetas_review
from zero.losetas_review import handle_review_message, store_review_draft
from zero.memory import SessionMemory

SHEET_ID = "sheet-fake"
INFO = "'INFO PEDIDOS POOLEDGE'"
PLATAS = "'PLATAS 2026'"
HEADER = ["NOMBRE"] + [""] * 8 + ["ID PEDIDO"]


class FakeBridge:
    def __init__(self):
        self.sent = []

    def __call__(self, client, account, group, body):
        self.sent.append(body)
        return {"id": f"bot{len(self.sent)}", "ack": 1}


class FakeSheets:
    def __init__(self, info=None, platas=None):
        self.info = info if info is not None else [HEADER]
        self.platas = platas if platas is not None else [["ID PEDIDO"]]
        self.writes = []
        self.fail_write = False

    def read_values(self, spreadsheet_id, a1, token, render="FORMATTED_VALUE"):
        return self.info if "INFO" in a1 else self.platas

    def batch_values_update(self, spreadsheet_id, data, token, input_option="USER_ENTERED"):
        if self.fail_write:
            raise RuntimeError("HTTP 403 secreto-de-la-api")
        self.writes.append(data)


class Phase2Test(unittest.TestCase):
    def setUp(self):
        self.memory = SessionMemory(None)
        self.memory.clients["losetaschile"] = {"knowledge": KNOWLEDGE}
        store_review_draft(self.memory, "losetaschile", "G1",
                           draft(quote=dict(QUOTE, subtotal=254_117)))
        self.bridge = FakeBridge()
        self.sheets = FakeSheets()
        self.stack = [
            mock.patch("zero.whatsapp_web.send_group_text", side_effect=self.bridge),
            mock.patch("zero.losetas_review.today", return_value=date(2026, 10, 26)),
            mock.patch("zero.losetas_review.POOLEDGE_WRITE_ORDERS", True),
            mock.patch.dict(os.environ, {"LOSETASCHILE_ORDERS_SHEET_ID": SHEET_ID}),
            mock.patch("zero.sheets.get_access_token", return_value="tok"),
            mock.patch("zero.sheets.read_values", side_effect=self.sheets.read_values),
            mock.patch("zero.sheets.batch_values_update",
                       side_effect=self.sheets.batch_values_update),
        ]
        for patcher in self.stack:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.counter = 0

    def say(self, text, quoted_id="", quoted_text=""):
        self.counter += 1
        handle_review_message(self.memory, {
            "client": "losetaschile", "id": f"m{self.counter}", "chat_id": GROUP,
            "text": text, "to_phone_id": "56911111111",
            "quoted_id": quoted_id, "quoted_text": quoted_text})

    def minutes_ago(self, minutes):
        return (losetas_review._now() - timedelta(minutes=minutes)).isoformat()

    def bridge_id_of_last(self):
        return f"bot{len(self.bridge.sent)}"

    def stored(self):
        return self.memory.clients["losetaschile"]["review_drafts"]["G1"]

    def publish_final(self):
        self.say(FULL, quoted_id="G1")
        self.assertEqual(self.stored()["status"], "final_published")
        return self.bridge.sent[0]

    def to_preview(self):
        budget = self.publish_final()
        self.say("confirmado", quoted_text=budget)
        self.assertEqual(self.stored()["status"], "preview_sent")
        return self.bridge.sent[-1]

    def test_draft_is_json_serializable_after_final(self):
        self.publish_final()
        self.assertEqual(self.stored()["fields"]["delivery"], ["2026-10-30", "2026-10-31"])
        json.dumps(self.memory.clients)
        json.dumps(self.memory.snapshot())

    def test_confirmado_posts_preview_with_pesos(self):
        preview = self.to_preview()
        self.assertTrue(preview.startswith("*POOLEDGE* Voy a anotar en la planilla"))
        self.assertIn("hoy sería PE-0001", preview)
        self.assertIn("Venta neta: $254.117", preview)
        self.assertIn("Despacho: $80.000", preview)
        self.assertIn("*ok*", preview)
        self.assertNotIn("**", preview)
        self.assertEqual(self.sheets.writes, [])

    def test_ok_writes_exact_ranges(self):
        preview = self.to_preview()
        self.sheets.info = [HEADER, ["x"] * 9 + ["PE-0041"]]
        self.sheets.platas = [["ID", "F"], ["PE-0041", "f", "", "d", 1]]
        self.say("ok", quoted_text=preview)
        self.assertEqual(self.stored()["status"], "sheet_written")
        (data,) = self.sheets.writes
        self.assertEqual([d["range"] for d in data],
                         [f"{INFO}!A3:J3", f"{PLATAS}!A3:B3", f"{PLATAS}!D3:E3"])
        info = data[0]["values"][0]
        self.assertEqual(len(info), 10)
        self.assertEqual(info[1], "'56933040685")
        self.assertEqual((info[2], info[3], info[6], info[7], info[9]),
                         ("2026-10-30", "No", False, 80000, "PE-0042"))
        self.assertEqual(data[1]["values"], [["PE-0042", "2026-10-30"]])
        self.assertEqual(data[2]["values"][0][1], 254_117)
        self.assertIn("PE-0042", self.bridge.sent[-1])

    def test_ok_found_by_preview_message_id(self):
        self.to_preview()
        self.say("ok", quoted_id=self.bridge_id_of_last())
        self.assertEqual(self.stored()["status"], "sheet_written")

    def test_flag_off_ok_does_not_write_and_flow_is_original(self):
        preview = self.to_preview()
        count = len(self.bridge.sent)
        with mock.patch("zero.losetas_review.POOLEDGE_WRITE_ORDERS", False):
            self.say("ok", quoted_text=preview)
        self.assertEqual(self.sheets.writes, [])
        self.assertEqual(self.stored()["status"], "preview_sent")
        self.assertEqual(len(self.bridge.sent), count)

    def test_flag_off_confirmado_is_silent(self):
        with mock.patch("zero.losetas_review.POOLEDGE_WRITE_ORDERS", False):
            budget = self.publish_final()
            count = len(self.bridge.sent)
            self.say("confirmado", quoted_text=budget)
        self.assertEqual(len(self.bridge.sent), count)

    def test_repeated_ok_does_not_duplicate(self):
        preview = self.to_preview()
        self.say("ok", quoted_text=preview)
        self.say("ok", quoted_text=preview)
        self.assertEqual(len(self.sheets.writes), 1)
        self.assertIn("Ya anotado como PE-0001", self.bridge.sent[-1])

    def test_two_pending_previews_get_distinct_ids(self):
        store_review_draft(self.memory, "losetaschile", "G2",
                           draft(lead="k2", text="*PRESUPUESTO otro*",
                                 quote=dict(QUOTE, subtotal=100_000)))
        p1 = self.to_preview()
        self.say(FULL, quoted_id="G2")
        self.say("confirmado", quoted_text=self.bridge.sent[-2])
        p2 = self.bridge.sent[-1]
        self.assertIn("hoy sería PE-0001", p1)
        self.assertIn("hoy sería PE-0001", p2)
        self.say("ok", quoted_text=p1)
        # la planilla se actualiza con la primera escritura
        self.sheets.info = [HEADER, ["a"] * 9 + ["PE-0001"]]
        self.sheets.platas = [["ID"], ["PE-0001", "f", "", "d", 1]]
        self.say("ok", quoted_text=p2)
        self.assertEqual(len(self.sheets.writes), 2)
        self.assertEqual(self.sheets.writes[1][0]["values"][0][9], "PE-0002")
        self.assertEqual(self.sheets.writes[1][0]["range"], f"{INFO}!A3:J3")
        self.assertIn("PE-0002", self.bridge.sent[-1])
        drafts = self.memory.clients["losetaschile"]["review_drafts"]
        self.assertEqual((drafts["G1"]["order_id"], drafts["G2"]["order_id"]),
                         ("PE-0001", "PE-0002"))

    def test_sheet_writing_recent_says_in_progress_and_does_not_write(self):
        preview = self.to_preview()
        self.stored().update(status="sheet_writing", order_id="PE-0001",
                             sheet_writing_at=self.minutes_ago(2))
        self.say("ok", quoted_text=preview)
        self.assertEqual(self.sheets.writes, [])
        self.assertIn("en proceso", self.bridge.sent[-1])

    def test_sheet_writing_stale_already_applied_is_marked_written(self):
        preview = self.to_preview()
        self.stored().update(status="sheet_writing", order_id="PE-0009",
                             sheet_writing_at=self.minutes_ago(30))
        self.sheets.info = [HEADER, ["a"] * 9 + ["PE-0009"]]
        self.say("ok", quoted_text=preview)
        self.assertEqual(self.sheets.writes, [])
        self.assertEqual(self.stored()["status"], "sheet_written")

    def test_sheet_writing_stale_not_applied_retries(self):
        preview = self.to_preview()
        self.stored().update(status="sheet_writing", order_id="PE-0001",
                             sheet_writing_at=self.minutes_ago(30))
        self.say("ok", quoted_text=preview)
        self.assertEqual(len(self.sheets.writes), 1)
        self.assertEqual(self.stored()["status"], "sheet_written")

    def test_phase2_statuses_ignore_other_messages_silently(self):
        budget = self.publish_final()
        count = len(self.bridge.sent)
        self.say(FULL.replace("80000", "90000"), quoted_text=budget)
        self.say("ok", quoted_text=budget)
        self.assertEqual((len(self.bridge.sent), self.stored()["status"]),
                         (count, "final_published"))
        self.say("confirmado", quoted_text=budget)
        preview = self.bridge.sent[-1]
        count = len(self.bridge.sent)
        for text in (FULL, "confirmado", "gracias"):
            self.say(text, quoted_text=preview)
        self.assertEqual((len(self.bridge.sent), self.stored()["status"]),
                         (count, "preview_sent"))

    def test_strict_words(self):
        preview = self.to_preview()
        for text in ("ok pero cambia la fecha", "ok no", "okey dokey", "no ok"):
            self.say(text, quoted_text=preview)
        self.assertEqual(self.sheets.writes, [])
        self.assertEqual(self.stored()["status"], "preview_sent")
        self.say("Ok. 👍", quoted_text=preview)
        self.assertEqual(self.stored()["status"], "sheet_written")

    def test_confirmado_strict(self):
        budget = self.publish_final()
        count = len(self.bridge.sent)
        self.say("confirmado pero falta algo", quoted_text=budget)
        self.assertEqual(len(self.bridge.sent), count)
        self.say("Confirmado!", quoted_text=budget)
        self.assertEqual(self.stored()["status"], "preview_sent")

    def test_confirmado_with_incomplete_data_does_not_crash(self):
        budget = self.publish_final()
        self.stored()["fields"]["delivery"] = []
        self.say("confirmado", quoted_text=budget)
        self.assertIn("No puedo anotar aún", self.bridge.sent[-1])
        self.assertEqual(self.stored()["status"], "final_published")

    def test_api_error_posts_generic_message_without_detail(self):
        preview = self.to_preview()
        self.sheets.fail_write = True
        self.say("ok", quoted_text=preview)
        last = self.bridge.sent[-1]
        self.assertNotIn("403", last)
        failed = [a for a in self.memory.actions if a["action"] == "order_sheet_failed"]
        self.assertEqual(failed[0]["error"], "RuntimeError")
        self.assertEqual(self.stored()["status"], "sheet_writing")
        self.assertIn("No sé si quedó anotado", last)
        self.assertIn("10 minutos", last)

    def test_read_failure_reverts_to_preview_and_retries_at_once(self):
        preview = self.to_preview()
        with mock.patch("zero.sheets.read_values", side_effect=OSError("secreto")):
            self.say("ok", quoted_text=preview)
        last = self.bridge.sent[-1]
        self.assertEqual(last, "*POOLEDGE* No pude anotar el pedido en la planilla. "
                               "Detalle en el registro.")
        self.assertEqual(self.stored()["status"], "preview_sent")
        self.say("ok", quoted_text=preview)
        self.assertEqual(self.stored()["status"], "sheet_written")

    def test_failure_before_api_call_after_marking_reverts(self):
        preview = self.to_preview()
        with mock.patch.object(self.memory, "save", side_effect=[OSError, None, None]):
            self.say("ok", quoted_text=preview)
        self.assertEqual(self.sheets.writes, [])
        self.assertEqual(self.stored()["status"], "preview_sent")

    def test_success_notice_failure_keeps_written_and_posts_no_error(self):
        preview = self.to_preview()
        count = len(self.bridge.sent)
        with mock.patch("zero.whatsapp_web.send_group_text", side_effect=RuntimeError("x")):
            self.say("ok", quoted_text=preview)
        self.assertEqual(len(self.sheets.writes), 1)
        self.assertEqual(self.stored()["status"], "sheet_written")
        self.assertEqual(len(self.bridge.sent), count)
        actions = [a["action"] for a in self.memory.actions]
        self.assertIn("order_sheet_written_notice_failed", actions)
        self.assertNotIn("order_sheet_failed", actions)

    def test_in_progress_message_mentions_retry_window(self):
        preview = self.to_preview()
        self.stored().update(status="sheet_writing", order_id="PE-0001",
                             sheet_writing_at=self.minutes_ago(1))
        self.say("ok", quoted_text=preview)
        self.assertIn("10 minutos", self.bridge.sent[-1])

    def test_old_draft_without_fields_warns_to_do_by_hand(self):
        budget = self.publish_final()
        del self.stored()["fields"]
        self.say("confirmado", quoted_text=budget)
        self.assertIn("anótalo a mano", self.bridge.sent[-1])
        self.assertEqual(self.stored()["status"], "final_published")

    def test_two_threads_ok_on_same_draft_write_once(self):
        import tempfile
        import threading
        import time
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            self.memory.path = path
            self.memory.save()
            preview = self.to_preview()
            real = self.sheets.batch_values_update

            def slow(*args, **kwargs):
                time.sleep(0.4)
                return real(*args, **kwargs)
            threads = []
            with mock.patch("zero.sheets.batch_values_update", side_effect=slow):
                for n in range(2):
                    memory = SessionMemory(path)
                    message = {"client": "losetaschile", "id": f"t{n}", "chat_id": GROUP,
                               "text": "ok", "to_phone_id": "56911111111",
                               "quoted_id": "", "quoted_text": preview}
                    thread = threading.Thread(target=handle_review_message,
                                              args=(memory, message))
                    threads.append(thread)
                    thread.start()
                    time.sleep(0.1)
                for thread in threads:
                    thread.join()
            self.assertEqual(len(self.sheets.writes), 1)
            saved = SessionMemory(path).clients["losetaschile"]["review_drafts"]["G1"]
            self.assertEqual(saved["status"], "sheet_written")
            self.assertEqual(saved["order_id"], "PE-0001")
            self.assertIn("Ya anotado como PE-0001", self.bridge.sent[-1])

    def test_target_row_skips_false_checkbox_tail(self):
        preview = self.to_preview()
        self.sheets.info = [HEADER, ["a"] * 9 + ["PE-0001x"]] + \
            [["", "", "", "", "", "", False]] * 900
        self.sheets.info[1][9] = "PE-0007"
        self.say("ok", quoted_text=preview)
        # ID del preview PE-0001 no existe; fila destino = 3, no ~902
        self.assertEqual(self.sheets.writes[0][0]["range"], f"{INFO}!A3:J3")

    def test_target_row_fills_gap(self):
        preview = self.to_preview()
        self.sheets.platas = [["ID"], ["PE-0001x"], [], ["PE-0003x"]]
        self.say("ok", quoted_text=preview)
        self.assertEqual(self.sheets.writes[0][1]["range"], f"{PLATAS}!A3:B3")


if __name__ == "__main__":
    unittest.main()
