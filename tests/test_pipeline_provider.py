"""Selección por búsqueda: sin red, sin credenciales reales ni escrituras al CRM."""
import os
import unittest
from unittest.mock import MagicMock, patch
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError
import api
from zero import runs


class PipelineProvider(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        runs.olvidar_todo()
        self.addCleanup(runs.olvidar_todo)

    def test_invalid_provider_is_rejected(self):
        with self.assertRaises(ValidationError):
            api.RunRequest(client='test', query='test', provider='automatic-paid')

    def test_explicit_provider_never_uses_global_priority(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test', 'ANTHROPIC_API_KEY': 'test', 'LOCAL_MODEL': 'qwen2.5:14b'}):
            for provider, cls in [('openai', 'OpenAIBackend'), ('anthropic', 'AnthropicBackend'), ('qwen', 'LocalBackend')]:
                with self.subTest(provider=provider), patch('zero.backends.' + cls) as backend, patch.object(api, 'build_agents') as build, patch.object(api, '_agents_best') as fallback:
                    source = object()
                    api._pipeline_agents(provider, source)
                    build.assert_called_once_with(backend=backend.return_value, mock=False, source=source)
                    fallback.assert_not_called()

    def test_missing_provider_fails_before_creating_run_or_crm(self):
        with patch.object(api, 'make_crm') as crm, patch.object(api, '_agents_best') as fallback:
            for provider in ['openai', 'anthropic', 'qwen']:
                req = api.RunRequest(client='test', query='test', provider=provider)
                for endpoint in [lambda: api.start_pipeline(req, BackgroundTasks()), lambda: api.run_pipeline(req)]:
                    with self.assertRaises(HTTPException) as error:
                        endpoint()
                    self.assertEqual(error.exception.status_code, 503)
            crm.assert_not_called()
            fallback.assert_not_called()

    def test_initialization_failure_does_not_switch_provider(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'test', 'LOCAL_MODEL': 'qwen2.5:14b'}), patch('zero.backends.OpenAIBackend', side_effect=ValueError('secret')), patch.object(api, '_agents_best') as fallback:
            with self.assertRaises(HTTPException) as error:
                api._pipeline_agents('openai')
            self.assertNotIn('secret', error.exception.detail)
            fallback.assert_not_called()

    def test_local_non_qwen_is_not_misrepresented(self):
        with patch.dict(os.environ, {'LOCAL_MODEL': 'llama3'}):
            with self.assertRaises(HTTPException):
                api._pipeline_agents('qwen')

    def test_legacy_requests_keep_automatic_selection(self):
        with patch.object(api, '_agents_best', return_value=({}, 'live')) as best:
            api._pipeline_agents(None)
            best.assert_called_once_with(source=None)

    def test_background_runs_capture_distinct_backends_and_never_reselect(self):
        tasks = BackgroundTasks()
        first, second = object(), object()
        with patch.object(api, '_pipeline_agents', side_effect=[(first, 'live'), (second, 'live')]) as select, patch.object(api, 'make_crm'), patch.object(api, 'make_memory'), patch.object(api, 'make_outbox'), patch.object(api, 'Zero') as zero:
            zero.return_value.run_pipeline.return_value = {'summary': {}}
            api.start_pipeline(api.RunRequest(client='test', query='one', provider='openai'), tasks)
            api.start_pipeline(api.RunRequest(client='test', query='two', provider='qwen'), tasks)
            for task in tasks.tasks:
                task.func()
            self.assertEqual(select.call_count, 2)
            self.assertIs(zero.call_args_list[0].args[0], first)
            self.assertIs(zero.call_args_list[1].args[0], second)

    def test_sync_endpoint_uses_selected_backend(self):
        backend = object()
        with patch.object(api, '_pipeline_agents', return_value=(backend, 'live')) as select, patch.object(api, 'make_crm'), patch.object(api, 'make_memory'), patch.object(api, 'make_outbox'), patch.object(api, 'Zero') as zero:
            zero.return_value.run_pipeline.return_value = {}
            result = api.run_pipeline(api.RunRequest(client='test', query='test', provider='anthropic'))
            self.assertEqual(select.call_args.args[0], 'anthropic')
            self.assertIs(zero.call_args.args[0], backend)
            self.assertEqual(result['provider'], 'anthropic')
