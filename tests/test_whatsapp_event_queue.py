"""La cola no reabre chats vencidos ni trata una pausa manual como fallo."""
import json
import os
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

from zero import whatsapp_web as web


class EventQueueTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = temp.name + '/events.sqlite3'
        patch = mock.patch.dict(os.environ, {'WHATSAPP_WEB_EVENT_DB': self.db})
        patch.start()
        self.addCleanup(patch.stop)
        web._inbox_stop.clear()
        self.addCleanup(web._inbox_stop.clear)

    def queue(self, event_id, age=0, **extra):
        payload = {'id': event_id, 'from': '56900000001', 'text': 'consulta', 'timestamp': time.time(), **extra}
        web.claim_event(event_id, payload)
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE received SET created=datetime('now', ?) WHERE id=?",
                       (f'-{age} seconds', event_id))
        return payload

    def row(self, event_id):
        with sqlite3.connect(self.db) as db:
            db.row_factory = sqlite3.Row
            return dict(db.execute('SELECT * FROM received WHERE id=?', (event_id,)).fetchone())

    def run_once(self, processor):
        def bounded(messages):
            try:
                return processor(messages)
            finally:
                web._inbox_stop.set()
        web._inbox_loop(bounded)

    def test_old_pending_is_held_and_next_fresh_message_can_proceed(self):
        self.queue('old', age=600)
        self.queue('fresh')
        selected = web._next_pending()
        self.assertEqual(selected['id'], 'fresh')
        self.assertEqual(self.row('old')['status'], 'needs_review')
        self.assertIn('antiguo', self.row('old')['error'])

    def test_old_origin_is_held_even_when_just_received_by_backend(self):
        self.queue('recovered', timestamp=time.time()-3600)
        self.assertIsNone(web._next_pending())
        self.assertEqual(self.row('recovered')['status'], 'needs_review')

    def test_corrupt_pending_rows_do_not_block_next_valid_message(self):
        bad = [('bad-json', '{', '2020-01-01'),
               ('bad-shape', '[]', '2020-01-01'),
               ('bad-date', '{"id":"bad-date"}', 'invalid'),
               ('missing-id', '{}', '2020-01-01'),
               ('wrong-id', '{"id":"different"}', '2020-01-01')]
        self.queue('fresh')
        with sqlite3.connect(self.db) as db:
            for event_id, payload, created in bad:
                db.execute("INSERT INTO received(id,payload,created,status) VALUES (?,?,?,'pending')",
                           (event_id, payload, created))
        self.assertEqual(web._next_pending()['id'], 'fresh')
        self.assertIsNone(web._next_pending())
        for event_id, _, _ in bad:
            self.assertEqual(self.row(event_id)['status'], 'needs_review')
            self.assertTrue(self.row(event_id)['finished_at'])

    def test_old_review_command_is_held_while_fresh_command_proceeds(self):
        self.queue('old-ok', kind='review_group', timestamp=time.time()-3600)
        self.queue('fresh-ok', kind='review_group')
        self.assertEqual(web._next_pending()['id'], 'fresh-ok')
        self.assertEqual(self.row('old-ok')['status'], 'needs_review')

    def test_review_group_parser_preserves_source_time(self):
        with mock.patch('zero.whatsapp_web.review_group_client', return_value='example'):
            parsed = web.parse_review_group_message({
                'id': 'review', 'chat_id': '1234567890@g.us', 'text': 'ok',
                'to_phone_id': '56900000002', 'timestamp': 1794780000}, ['example'])
        self.assertEqual(parsed.get('timestamp'), 1794780000)

    def test_old_manual_event_still_applies_pause_and_completes(self):
        self.queue('manual', age=3600, kind='owner_message')
        def processor(messages):
            self.assertEqual(messages[0]['id'], 'manual')
            web._inbox_stop.set()
            return [{'owner_message': True, 'paused': True, 'stored': False}]
        self.run_once(processor)
        row = self.row('manual')
        self.assertEqual(row['status'], 'completed')
        self.assertFalse(row['error'])

    def test_processing_and_generation_times_are_retained_without_message_text(self):
        self.queue('normal')
        def processor(messages):
            with web.event_phase('generation'):
                pass
            with mock.patch('zero.whatsapp_web._bridge_request', return_value={'id': 'accepted', 'ack': 0}):
                web.bridge_request('/send', {'text': 'respuesta', 'to': '56900000001'})
            web._inbox_stop.set()
            return [{'matched': True, 'manual_review': True}]
        self.run_once(processor)
        row = self.row('normal')
        self.assertEqual(row['status'], 'completed')
        self.assertTrue(row['started_at'])
        self.assertTrue(row['finished_at'])
        timings = json.loads(row['timings'])
        self.assertGreaterEqual(timings['generation_ms'], 0)
        self.assertGreaterEqual(timings['processing_ms'], 0)
        self.assertGreaterEqual(timings['send_ms'], 0)
        self.assertGreaterEqual(timings['source_to_queue_ms'], 0)
        self.assertNotIn('consulta', row['timings'])

    def test_expiry_during_processing_prevents_transport_call(self):
        self.queue('slow')
        def processor(messages):
            with mock.patch('zero.whatsapp_web.time.time', return_value=time.time()+600), \
                    mock.patch('urllib.request.urlopen') as request:
                with self.assertRaisesRegex(RuntimeError, 'antiguo'):
                    web.bridge_request('/send', {'text': 'respuesta', 'to': '56900000001'})
                request.assert_not_called()
            web._inbox_stop.set()
            return [{'matched': True, 'manual_review': True}]
        self.run_once(processor)
        self.assertEqual(self.row('slow')['status'], 'completed')

    def test_parser_preserves_origin_timestamp(self):
        parsed = web.parse_message({'id': 'source', 'from': '56900000001',
                                    'to_phone_id': '56900000002', 'timestamp': 1794780000})
        self.assertEqual(parsed.get('timestamp'), 1794780000)

    def test_unknown_or_invalid_origin_never_reaches_processor(self):
        for index, value in enumerate((None, 'invalid', float('nan'), time.time()+3600, 10**400)):
            self.queue(f'bad-{index}', timestamp=value)
        self.assertIsNone(web._next_pending())
        self.assertTrue(all(self.row(f'bad-{i}')['status']=='needs_review' for i in range(5)))

    def test_age_limit_is_inclusive_and_rejects_next_second(self):
        self.queue('boundary', timestamp=1000)
        self.queue('expired', timestamp=999)
        with mock.patch('zero.whatsapp_web.time.time', return_value=1300):
            self.assertEqual(web._next_pending()['id'], 'boundary')
            self.assertIsNone(web._next_pending())
        self.assertEqual(self.row('expired')['status'], 'needs_review')

    def test_ignored_manual_event_is_completed_without_delivery(self):
        self.queue('ignored', kind='owner_message')
        self.run_once(lambda messages: [{'owner_message': True, 'ignored': True}])
        self.assertEqual(self.row('ignored')['status'], 'completed')

    def test_failed_delivery_retains_review_status_and_context_is_cleared(self):
        self.queue('failed')
        self.run_once(lambda messages: [{'matched': True, 'delivery': {'status': 'error'}}])
        self.assertEqual(self.row('failed')['status'], 'needs_review')
        self.assertIsNone(web._event_context.get())

    def test_previous_schema_is_migrated_without_replaying_completed_events(self):
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE received (id TEXT PRIMARY KEY, created TEXT DEFAULT CURRENT_TIMESTAMP)')
            db.execute("INSERT INTO received(id) VALUES ('already-done')")
        self.queue('fresh')
        self.assertEqual(web._next_pending()['id'], 'fresh')
        self.assertEqual(self.row('already-done')['status'], 'completed')
        self.assertIsNone(self.row('already-done')['timings'])

    def test_restart_closes_interrupted_event_without_replaying_it(self):
        self.queue('interrupted')
        self.assertEqual(web._next_pending()['id'], 'interrupted')
        with mock.patch.dict(os.environ, {'WHATSAPP_PROVIDER': 'web'}), \
                mock.patch.object(web, '_inbox_thread', None), \
                mock.patch('zero.whatsapp_web.threading.Thread'):
            web.start_inbox_worker(lambda messages: [])
        row = self.row('interrupted')
        self.assertEqual(row['status'], 'needs_review')
        self.assertTrue(row['finished_at'])
        self.assertIsNone(web._next_pending())
