import http.client
import json
import unittest
from unittest.mock import Mock, patch

from godseye.provider_discovery import (
    CATALOG_URLS, INFERENCE_URLS, MAX_RESPONSE_BYTES, OUTPUT_LIMIT, TIMEOUT,
    DiscoveryError, ProviderDiscovery, request_json,
)

KEYS = {'openai': 'sk-dummy-openai-1234567890', 'openrouter': 'sk-dummy-router-1234567890',
        'huggingface': 'hf_dummyhuggingface1234567890'}


def tool_response(provider, arguments='{}'):
    function = {'name': 'godseye_connection_check', 'arguments': arguments}
    if provider == 'openai':
        return {'status': 'completed', 'output': [{'type': 'function_call', **function}]}
    return {'choices': [{'finish_reason': 'tool_calls', 'message': {
        'tool_calls': [{'type': 'function', 'function': function}]}}]}


class DiscoveryTests(unittest.TestCase):
    def test_provider_specific_catalogs_and_conservative_capabilities(self):
        for provider, key in KEYS.items():
            with self.subTest(provider=provider):
                transport = Mock(return_value={'data': [
                    {'id': 'org/tools', 'supported_parameters': ['tools'],
                     'providers': [{'status': 'live', 'supports_tools': True}]},
                    {'id': 'org/unknown'},
                    {'id': 'org/mixed', 'supported_parameters': [], 'providers': [
                        {'status': 'live', 'supports_tools': True}, {'status': 'live'}]},
                    {'id': 'org/false', 'providers': [{'status': 'live', 'supports_tools': False}]},
                    {'id': 'org/offline', 'providers': [{'status': 'offline', 'supports_tools': True}]},
                    {'id': 'org/named-tools-model'},
                    {'id': key}, {'id': '<script>alert(1)</script>'}, None,
                    {'id': 'org/malformed', 'supported_parameters': 'tools', 'providers': None},
                    {'id': 'org/unknown', 'description': key, 'api_key': key},
                ]})
                result = ProviderDiscovery(transport).load_models(provider, key)
                transport.assert_called_once_with('GET', CATALOG_URLS[provider], key, None)
                self.assertEqual(result['state'], 'success')
                self.assertNotIn(key, json.dumps(result))
                models = {m['id']: m for m in result['models']}
                self.assertEqual(models['org/tools']['tool_support'], 'unknown' if provider == 'openai' else 'supported')
                for model in ('unknown', 'mixed', 'false', 'offline', 'named-tools-model', 'malformed'):
                    self.assertEqual(models['org/' + model]['tool_support'], 'unknown')
                self.assertEqual(len(models), 7)

    def test_probe_one_request_provider_payload_limits_and_no_followup(self):
        for provider, key in KEYS.items():
            with self.subTest(provider=provider):
                transport = Mock(return_value=tool_response(provider))
                result = ProviderDiscovery(transport).test_connection(provider, key, 'org/model', 'latency', confirmed=True)
                self.assertTrue(result['tool_call_verified'])
                self.assertEqual(result['requests'], 1)
                transport.assert_called_once()
                method, url, sent_key, body = transport.call_args.args
                self.assertEqual((method, url, sent_key), ('POST', INFERENCE_URLS[provider], key))
                self.assertEqual(body['model'], 'org/model')
                self.assertIs(body['stream'], False)
                self.assertNotIn(key, json.dumps(body))
                self.assertEqual(body['max_output_tokens'] if provider == 'openai' else body['max_tokens'], OUTPUT_LIMIT)
                if provider == 'openai':
                    self.assertFalse(body['store'])
                    self.assertFalse(body['parallel_tool_calls'])
                    self.assertEqual(body['tools'][0]['name'], 'godseye_connection_check')
                    self.assertEqual(body['tool_choice']['type'], 'function')
                    self.assertNotIn('messages', body)
                else:
                    self.assertEqual(body['tool_choice'], 'required')
                    self.assertEqual(body['tools'][0]['function']['name'], 'godseye_connection_check')
                    self.assertNotIn('input', body)
                if provider == 'openrouter':
                    self.assertEqual(body['provider'], dict(sort='latency', require_parameters=True,
                                                           data_collection='deny', allow_fallbacks=False))
                else:
                    self.assertNotIn('provider', body)

    def test_confirmation_and_validation_before_transport(self):
        transport = Mock()
        discovery = ProviderDiscovery(transport)
        for confirmed in (False, None, 1, 'true'):
            with self.assertRaises(ValueError):
                discovery.test_connection('openai', KEYS['openai'], 'model', confirmed=confirmed)
        for args in [('bad', KEYS['openai'], 'model'), ('openai', '', 'model'),
                     ('openai', KEYS['openai'], ''), ('openai', KEYS['openai'], '$model'),
                     ([], KEYS['openai'], 'model')]:
            with self.assertRaises(ValueError):
                discovery.test_connection(*args, confirmed=True)
        transport.assert_not_called()

    def test_probe_does_not_claim_unsupported_on_incomplete_invalid_or_plain_response(self):
        for provider, key in KEYS.items():
            plain = {'status': 'completed', 'output': []} if provider == 'openai' else {
                'choices': [{'finish_reason': 'stop', 'message': {'content': 'hello'}}]}
            incomplete = tool_response(provider)
            if provider == 'openai':
                incomplete['status'] = 'incomplete'
            else:
                incomplete['choices'][0]['finish_reason'] = 'length'
            multiple = tool_response(provider)
            wrong_name = tool_response(provider)
            if provider == 'openai':
                multiple['output'] *= 2
                wrong_name['output'][0]['name'] = 'unexpected_tool'
            else:
                multiple['choices'][0]['message']['tool_calls'] *= 2
                wrong_name['choices'][0]['message']['tool_calls'][0]['function']['name'] = 'unexpected_tool'
            for response in (plain, incomplete, {}, multiple, wrong_name, tool_response(provider, '{bad'),
                             tool_response(provider, '{"extra": true}'), tool_response(provider, '[]')):
                transport = Mock(return_value=response)
                result = ProviderDiscovery(transport).test_connection(provider, key, 'model', confirmed=True)
                self.assertEqual(result['state'], 'tool_call_unconfirmed')
                self.assertFalse(result['tool_call_verified'])
                transport.assert_called_once()

    def test_errors_and_malformed_catalog_are_sanitized_without_retry(self):
        for response in ({}, {'data': None}, {'error': {'code': 429, 'message': KEYS['openai']}}, []):
            transport = Mock(return_value=response)
            with self.assertRaises(DiscoveryError) as caught:
                ProviderDiscovery(transport).load_models('openai', KEYS['openai'])
            self.assertNotIn(KEYS['openai'], json.dumps(caught.exception.result()))
            transport.assert_called_once()
        for error in (TimeoutError(KEYS['openai']), RuntimeError(KEYS['openai'])):
            transport = Mock(side_effect=error)
            with self.assertRaises(DiscoveryError) as caught:
                ProviderDiscovery(transport).test_connection('openai', KEYS['openai'], 'model', confirmed=True)
            self.assertEqual(caught.exception.state, 'provider_unavailable')
            self.assertNotIn(KEYS['openai'], str(caught.exception))
            transport.assert_called_once()


class TransportTests(unittest.TestCase):
    def connection(self, factory, status=200, raw=b'{}'):
        connection = factory.return_value
        response = connection.getresponse.return_value
        response.status = status
        response.read.return_value = raw
        return connection, response

    @patch('godseye.provider_discovery.http.client.HTTPSConnection')
    def test_fixed_url_timeout_one_request_no_redirects_and_redacted_http_errors(self, factory):
        states = {301: 'provider_unavailable', 307: 'provider_unavailable', 400: 'invalid_request',
                  401: 'authentication', 403: 'authentication', 402: 'billing',
                  404: 'unavailable_model', 410: 'unavailable_model', 422: 'invalid_request',
                  429: 'rate_limit', 500: 'provider_unavailable', 503: 'provider_unavailable'}
        for status, state in states.items():
            factory.reset_mock()
            connection, response = self.connection(factory, status, KEYS['openai'].encode())
            with self.assertRaises(DiscoveryError) as caught:
                request_json('GET', CATALOG_URLS['openai'], KEYS['openai'], None)
            self.assertEqual(caught.exception.state, state)
            self.assertNotIn(KEYS['openai'], str(caught.exception))
            factory.assert_called_once_with('api.openai.com', timeout=TIMEOUT)
            connection.request.assert_called_once()
            connection.close.assert_called_once()
            response.read.assert_not_called()
        factory.reset_mock()
        with self.assertRaises(ValueError):
            request_json('GET', 'https://evil.invalid/models', KEYS['openai'], None)
        factory.assert_not_called()

    @patch('godseye.provider_discovery.http.client.HTTPSConnection')
    def test_invalid_json_size_network_failures_and_success(self, factory):
        for raw in (b'not-json', b'\xff', b'x' * (MAX_RESPONSE_BYTES + 1)):
            factory.reset_mock()
            connection, response = self.connection(factory, raw=raw)
            with self.assertRaises(DiscoveryError) as caught:
                request_json('GET', CATALOG_URLS['openai'], KEYS['openai'], None)
            self.assertEqual(caught.exception.state, 'invalid_response')
            response.read.assert_called_once_with(MAX_RESPONSE_BYTES + 1)
            connection.close.assert_called_once()
        for error in (TimeoutError('dummy'), http.client.RemoteDisconnected('dummy')):
            factory.reset_mock()
            connection, _ = self.connection(factory)
            connection.request.side_effect = error
            with self.assertRaises(DiscoveryError):
                request_json('POST', INFERENCE_URLS['openai'], KEYS['openai'], {'model': 'dummy'})
            connection.request.assert_called_once()
            connection.close.assert_called_once()
        connection.request.side_effect = None
        self.connection(factory, raw=b'{"data": []}')
        self.assertEqual(request_json('GET', CATALOG_URLS['openai'], KEYS['openai'], None), {'data': []})
