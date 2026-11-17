"""Atención permite revisar y cerrar eventos sin reenviar ni mezclar empresas."""
import json
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from fastapi import HTTPException
import api
from zero.memory import SessionMemory
from zero.whatsapp_web import _connect_events


class EventAttentionTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = temp.name + '/events.sqlite3'
        patch = mock.patch.dict(os.environ, {'WHATSAPP_WEB_EVENT_DB': self.path}, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.memory = SessionMemory(None)
        for client, number in [('alpha', '56900000001'), ('beta', '56900000002')]:
            self.memory.register_client(client, 'STARTER')
            self.memory.set_client_agent_profile(client, {'whatsapp_number': number})
        patch = mock.patch.object(api, 'make_memory', return_value=self.memory)
        patch.start()
        self.addCleanup(patch.stop)
        with _connect_events() as db:
            db.execute('SELECT 1')

    def event(self, event_id, client=None, destination='56900000001', **extra):
        payload = {'id': event_id, 'to_phone_id': destination, 'chat_id': '56900000003@c.us',
                   'text': 'Consulta de ejemplo', **extra}
        if client is not None:
            payload['client'] = client
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO received(id,payload,status,error) VALUES (?,?, 'needs_review',?)",
                       (event_id, json.dumps(payload), 'Mensaje antiguo; revisar antes de responder'))

    def test_list_only_includes_unambiguously_owned_events(self):
        self.event('alpha-event')
        self.event('beta-event', destination='56900000002')
        self.event('unknown', destination='56900000009')
        self.event('conflicting', client='beta')
        result = api.whatsapp_attention('alpha')
        self.assertEqual(result['open'], 1)
        [item] = result['items']
        self.assertEqual(item['tipo'], 'evento')
        self.assertEqual(item['chat_id'], '56900000003@c.us')
        self.assertEqual(item['pregunta'], 'Consulta de ejemplo')

    def test_explicit_client_can_associate_event_without_destination(self):
        self.event('explicit', client='alpha', destination='')
        self.assertEqual(api.whatsapp_attention('alpha')['open'], 1)
        self.assertEqual(api.whatsapp_attention('beta')['open'], 0)

    def test_shared_number_without_explicit_client_is_not_exposed(self):
        self.memory.set_client_agent_profile('beta', {'whatsapp_number': '56900000001'})
        self.event('ambiguous')
        self.assertEqual(api.whatsapp_attention('alpha')['open'], 0)

    def test_close_archives_once_without_sending_learning_or_unpausing(self):
        self.event('close')
        [item] = api.whatsapp_attention('alpha')['items']
        self.memory.set_whatsapp_handoff('alpha', item['chat_id'], 'El equipo tomó el chat')
        before = self.memory.snapshot()
        with mock.patch.object(api, '_whatsapp_web_inbox_request') as send:
            self.assertTrue(api.whatsapp_attention_dismiss(api.AttentionDismiss(clave=item['clave']), 'alpha')['ok'])
            send.assert_not_called()
        self.assertEqual(self.memory.snapshot(), before)
        self.assertEqual(api.whatsapp_attention('alpha')['open'], 0)
        self.assertEqual(api.whatsapp_attention('alpha', True)['items'][0]['estado'], 'descartada')
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT status FROM received WHERE id=?', ('close',)).fetchone()[0], 'archived')
        with self.assertRaises(HTTPException) as caught:
            api.whatsapp_attention_dismiss(api.AttentionDismiss(clave=item['clave']), 'alpha')
        self.assertEqual(caught.exception.status_code, 404)

    def test_other_company_cannot_close_known_key(self):
        self.event('owned')
        [item] = api.whatsapp_attention('alpha')['items']
        with self.assertRaises(HTTPException) as caught:
            api.whatsapp_attention_dismiss(api.AttentionDismiss(clave=item['clave']), 'beta')
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(api.whatsapp_attention('alpha')['open'], 1)

    def test_event_cannot_be_answered_or_taught_through_knowledge_routes(self):
        self.event('restricted')
        [item] = api.whatsapp_attention('alpha')['items']
        with mock.patch.object(api, '_whatsapp_web_inbox_request') as send:
            with self.assertRaises(HTTPException):
                api.whatsapp_attention_answer(api.AttentionAnswer(clave=item['clave'], respuesta='texto'), 'alpha')
            with self.assertRaises(HTTPException):
                api.whatsapp_attention_alias(api.AttentionAlias(clave=item['clave'], opcion='Gris'), 'alpha')
            send.assert_not_called()
        self.assertEqual(api.whatsapp_attention('alpha')['open'], 1)

    def test_unknown_company_cannot_list_even_explicit_payload(self):
        self.event('unknown-client', client='unknown', destination='')
        self.assertEqual(api.whatsapp_attention('unknown')['open'], 0)
