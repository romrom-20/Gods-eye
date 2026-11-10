import tempfile
import unittest
from pathlib import Path
from godseye.provider_setup import ProviderSettings
from isolation.agent_adapter import ProviderRouter, TOOLS


class RoutingTests(unittest.TestCase):
    def test_profiles_do_not_reuse_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = ProviderSettings(Path(folder) / 'secrets')
            settings.save('sk-dummy-openai-123456789', 'first')
            self.assertFalse(settings.status('openrouter')['configured'])
            with self.assertRaises(ValueError):
                settings.save('', 'second', 'openrouter')
            settings.save('sk-or-dummy-12345678901234', 'vendor/model', 'openrouter', 'latency')
            self.assertEqual(settings.status('openai')['model'], 'first')
            settings.save('hf_dummy1234567890123456789', 'org/model', 'huggingface')
            self.assertEqual(settings.status('openrouter')['routing'], 'latency')
            self.assertIn('huggingface-api-key', (settings.directory / 'provider.env').read_text())
            self.assertEqual((settings.directory / 'openai-api-key').read_text().strip(), 'sk-dummy-openai-123456789')

    def test_chat_tool_roundtrip_and_routing(self):
        for provider in ('openrouter', 'huggingface'):
            requests = []
            message = {'role': 'assistant', 'content': None, 'reasoning_details': [{'text': 'test'}],
                       'tool_calls': [{'id': str(i), 'type': 'function', 'function': {'name': 'list', 'arguments': '{}'}} for i in range(2)]}
            def transport(url, key, body):
                requests.append((url, key, body))
                return {'choices': [{'finish_reason': 'tool_calls', 'message': message}], 'model': 'resolved', 'usage': {'total_tokens': 20}}
            router = ProviderRouter(provider, 'dummy', transport=transport)
            body = dict(model='org/model', input=[{'role': 'user', 'content': 'test'}], tools=TOOLS, max_output_tokens=100)
            response = router(body)
            body['input'] += response['output'] + [{'type': 'function_call_output', 'call_id': str(i), 'output': '{}'} for i in range(2)]
            router(body)
            payload = requests[-1][2]
            self.assertEqual(payload['messages'][1], message)
            self.assertEqual([m['role'] for m in payload['messages']], ['user', 'assistant', 'tool', 'tool'])
            self.assertEqual(payload['tools'][0]['function']['name'], 'list')
            if provider == 'openrouter':
                self.assertEqual(payload['provider'], dict(sort='price', require_parameters=True, data_collection='deny', allow_fallbacks=False))
            else:
                self.assertNotIn('provider', payload)

    def test_openai_passes_responses_through(self):
        body = {'input': [], 'model': 'test'}
        def transport(url, key, payload):
            self.assertEqual(url, 'https://api.openai.com/v1/responses')
            self.assertIs(payload, body)
            return {'output': []}
        self.assertEqual(ProviderRouter('openai', 'dummy', transport=transport)(body), {'output': []})

    def test_bad_provider_and_incomplete_response_fail_closed(self):
        with self.assertRaises(ValueError):
            ProviderRouter('https://evil.example', 'dummy')
        requests = []
        def transport(*args):
            requests.append(args)
            return {'choices': [{'finish_reason': 'length', 'message': {}}]}
        router = ProviderRouter('openrouter', 'dummy', transport=transport)
        with self.assertRaises(ValueError):
            router(dict(model='test', input=[], tools=[], max_output_tokens=10))
        self.assertEqual(len(requests), 1)
