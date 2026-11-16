"""La segunda parte no puede pisar una intervención humana o un nuevo mensaje."""
import time
import unittest
from unittest import mock

from zero.memory import SessionMemory
from zero.whatsapp_web import WhatsAppWebSender, _event_context


class SplitTakeoverTest(unittest.TestCase):
    def send(self, interruption=None):
        from tests.test_whatsapp_human_delivery import LONG_A, LONG_B
        self.memory = SessionMemory(None)
        self.memory.register_client('losetaschile', 'STARTER')
        self.memory.set_client_agent_profile('losetaschile', {'response_mode': 'automatic'})
        self.messages = [{'id': 'incoming', 'fromMe': False, 'body': 'consulta'}]
        self.sent = []
        self.payloads = []

        def transport(path, body=None, client_id=None):
            if path == '/status':
                return {'state': 'ready', 'account': '56900000002'}
            if path == '/send':
                self.sent.append(body['text'])
                self.payloads.append(body)
                message_id = f'sent-{len(self.sent)}'
                self.messages.append({'id': message_id, 'fromMe': True, 'body': body['text']})
                if interruption:
                    interruption(self)
                return {'id': message_id, 'ack': 1}
            raise AssertionError(path)

        context = {'message': {'id': 'incoming', 'timestamp': time.time(), 'to_phone_id': '56900000002',
                              '_queued_at': time.time(), 'chat_id': '56900000001@c.us'}, 'timings': {}}
        token = _event_context.set(context)
        try:
            with mock.patch('zero.store.make_memory', return_value=self.memory), \
                    mock.patch('zero.whatsapp_web.read_chat_messages', side_effect=lambda *a, **kw: {'messages': list(self.messages)}), \
                    mock.patch('zero.whatsapp_web._bridge_request', side_effect=transport):
                return WhatsAppWebSender().send({
                    'client_id': 'losetaschile', 'to': '56900000001',
                    'whatsapp_from': '56900000002', 'whatsapp_chat_id': '56900000001@c.us',
                    'body': LONG_A+'\n\n'+LONG_B, 'humanize': True})
        finally:
            _event_context.reset(token)

    def test_manual_takeover_after_first_part_stops_remaining_parts(self):
        result = self.send(lambda s: s.memory.set_whatsapp_handoff('losetaschile', '56900000001@c.us', 'El equipo tomó el chat'))
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(result['partial'])
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['sent_text'], self.sent[0])

    def test_phone_message_without_webhook_yet_stops_remaining_parts(self):
        result = self.send(lambda s: s.messages.append({'id': 'manual', 'fromMe': True, 'body': 'Le respondí yo'}))
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(result['partial'])

    def test_new_customer_message_stops_remaining_parts(self):
        result = self.send(lambda s: s.messages.append({'id': 'new-customer', 'fromMe': False, 'body': 'Otra consulta'}))
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(result['partial'])

    def test_missing_live_history_stops_remaining_parts(self):
        result = self.send(lambda s: s.messages.clear())
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(result['partial'])

    def test_missing_attention_profile_stops_remaining_parts(self):
        result = self.send(lambda s: s.memory.set_client_agent_profile('losetaschile', {}))
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(result['partial'])

    def test_switch_to_manual_stops_remaining_parts(self):
        result = self.send(lambda s: s.memory.set_client_agent_profile('losetaschile', {'response_mode': 'manual'}))
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(result['partial'])

    def test_own_confirmed_first_part_allows_second_and_sends_bridge_guard(self):
        result = self.send()
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(result['status'], 'sent')
        self.assertEqual(self.payloads[0]['expected_last_id'], 'incoming')
        self.assertEqual(self.payloads[1]['expected_last_id'], 'sent-1')
        self.assertGreater(self.payloads[0]['expires_at'], time.time())
