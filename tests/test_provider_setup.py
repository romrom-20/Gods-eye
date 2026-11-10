import http.client
import json
from pathlib import Path
import re
import stat
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from godseye.provider_discovery import DiscoveryError, ProviderDiscovery

from godseye.provider_setup import ProviderSettings, create_server

FAKE_KEY = 'sk-test-only-not-a-real-provider-key'


class ProviderSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'private'
        self.settings = ProviderSettings(self.directory)
        self.transport = Mock(side_effect=AssertionError('Unexpected provider call in test'))
        self.server = create_server(self.settings, discovery=ProviderDiscovery(self.transport))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.host = '127.0.0.1:' + str(self.server.server_port)
        status, _, page = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.csrf = re.search(r'name="setup-token" content="([^"]+)"', page).group(1)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            connection.close()

    def save(self, key=FAKE_KEY, model='test-model', **headers):
        request_headers = {'Content-Type': 'application/json', 'Origin': 'http://' + self.host,
                           'X-Setup-Token': self.csrf}
        request_headers.update(headers)
        return self.request('POST', '/save', json.dumps({'key': key, 'model': model}), request_headers)

    def test_save_permissions_redaction_and_configuration(self):
        status, headers, body = self.save()
        self.assertEqual(status, 200, body)
        self.assertNotIn(FAKE_KEY, body)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(stat.S_IMODE(self.directory.stat().st_mode), 0o700)
        for name in ('openai-api-key', 'provider.json', 'provider.env'):
            self.assertEqual(stat.S_IMODE((self.directory / name).stat().st_mode), 0o600)
        self.assertEqual((self.directory / 'openai-api-key').read_text().strip(), FAKE_KEY)
        env = (self.directory / 'provider.env').read_text()
        self.assertIn('REPAIR_AGENT_KEY_FILE=', env)
        self.assertNotIn(FAKE_KEY, env)
        for path in ('/', '/status', '/setup.js'):
            self.assertNotIn(FAKE_KEY, self.request('GET', path)[2])
        self.assertEqual(self.request('GET', '/openai-api-key')[0], 404)
        self.assertEqual(self.save(key='', model='new-model')[0], 200)
        self.assertEqual((self.directory / 'openai-api-key').read_text().strip(), FAKE_KEY)

    def test_host_origin_csrf_and_body_boundaries(self):
        for headers in ({'Host': 'evil.example'}, {'Origin': 'https://evil.example'},
                        {'X-Setup-Token': 'wrong'}, {'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(self.save(**headers)[0], 403)
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.save(**{'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request('POST', '/save', 'x' * 9000, {
            'Content-Type': 'application/json', 'Origin': 'http://' + self.host,
            'X-Setup-Token': self.csrf})[0], 413)
        self.assertEqual(self.request('POST', '/save', '{}', {'Content-Type': 'application/json'})[0], 403)

    def test_invalid_inputs_are_not_saved_or_echoed(self):
        for key, model in [('hf-dummy-secret-not-openai', ''), (FAKE_KEY, '$(echo secret)'),
                           ('', ''), (123, ''), (FAKE_KEY, None)]:
            status, _, body = self.save(key, model)
            self.assertEqual(status, 400)
            self.assertNotIn(FAKE_KEY, body)
            self.assertFalse(self.directory.exists())

    def test_symlink_destinations_cannot_overwrite_unrelated_files(self):
        target = Path(self.temp.name) / 'keep'
        target.write_text('original')
        self.directory.mkdir()
        (self.directory / 'provider.env').symlink_to(target)
        self.assertEqual(self.save()[0], 400)
        self.assertEqual(target.read_text(), 'original')
        self.assertFalse((self.directory / 'openai-api-key').exists())

    def test_directory_symlink_rejected(self):
        target = Path(self.temp.name) / 'other'
        target.mkdir()
        self.directory.symlink_to(target, target_is_directory=True)
        self.assertEqual(self.save()[0], 400)
        self.assertEqual(list(target.iterdir()), [])

    def action(self, path, data, **headers):
        request_headers = {'Content-Type': 'application/json', 'Origin': 'http://' + self.host,
                           'X-Setup-Token': self.csrf}
        request_headers.update(headers)
        return self.request('POST', path, json.dumps(data), request_headers)

    def test_actions_require_csrf_origin_and_strict_confirmation(self):
        payload = {'provider': 'openai', 'model': 'dummy', 'key': FAKE_KEY}
        for path in ('/models', '/test-connection'):
            for headers in ({'X-Setup-Token': ''}, {'Origin': 'http://evil.example'},
                            {'Host': 'evil.example'}, {'Sec-Fetch-Site': 'cross-site'}):
                self.assertEqual(self.action(path, payload, **headers)[0], 403)
            self.assertEqual(self.request('GET', path)[0], 404)
        with patch.object(self.settings, 'credential', side_effect=AssertionError('Do not read a key')) as credential:
            for confirmed in (None, False, 1, 'true'):
                status, _, body = self.action('/test-connection', {**payload, 'confirmed': confirmed})
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(body)['state'], 'confirmation_required')
            credential.assert_not_called()
        for field in ('url', 'tools', 'max_tokens', 'max_output_tokens', 'retries'):
            status, _, _ = self.action('/test-connection', {**payload, 'confirmed': True, field: 999})
            self.assertEqual(status, 400)
        self.transport.assert_not_called()

    def test_load_and_test_use_selected_dummy_key_without_mutating_settings(self):
        self.save()
        self.settings.save('sk-dummy-router-1234567890', 'router/model', 'openrouter', 'throughput')
        before = {p.name: p.read_bytes() for p in self.directory.iterdir()}
        self.transport.side_effect = None
        self.transport.return_value = {'data': [{'id': 'catalog/model', 'description': FAKE_KEY}]}
        status, headers, body = self.action('/models', {'provider': 'openai'})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn(FAKE_KEY, body)
        self.assertEqual(self.transport.call_args.args[2], FAKE_KEY)
        self.transport.reset_mock()
        self.transport.return_value = {'choices': [{'finish_reason': 'tool_calls', 'message': {
            'tool_calls': [{'type': 'function', 'function': {'name': 'godseye_connection_check', 'arguments': '{}'}}]}}]}
        status, _, body = self.action('/test-connection', {
            'provider': 'openrouter', 'model': 'manual/model', 'routing': 'throughput', 'confirmed': True})
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)['tool_call_verified'])
        self.transport.assert_called_once()
        args = self.transport.call_args.args
        self.assertEqual(args[2], 'sk-dummy-router-1234567890')
        self.assertEqual(args[3]['model'], 'manual/model')
        self.assertEqual(args[3]['provider']['sort'], 'throughput')
        self.assertEqual({p.name: p.read_bytes() for p in self.directory.iterdir()}, before)
        self.assertNotIn(args[2], body)

    def test_unsaved_key_can_load_without_persistence_and_missing_key_does_not_fallback(self):
        self.transport.side_effect = None
        self.transport.return_value = {'data': []}
        status, _, _ = self.action('/models', {'provider': 'openai', 'key': FAKE_KEY})
        self.assertEqual(status, 200)
        self.assertFalse(self.directory.exists())
        self.save()
        self.transport.reset_mock()
        status, _, _ = self.action('/models', {'provider': 'huggingface'})
        self.assertEqual(status, 400)
        self.transport.assert_not_called()

    def test_provider_error_is_sanitized_and_no_retry(self):
        self.transport.side_effect = DiscoveryError('authentication')
        status, _, body = self.action('/models', {'provider': 'openai', 'key': FAKE_KEY})
        self.assertEqual(status, 502)
        self.assertEqual(json.loads(body)['state'], 'authentication')
        self.assertNotIn(FAKE_KEY, body)
        self.transport.assert_called_once()
        self.transport.reset_mock()
        self.transport.side_effect = RuntimeError('Provider echoed secret: ' + FAKE_KEY)
        status, _, body = self.action('/test-connection', {
            'provider': 'openai', 'key': FAKE_KEY, 'model': 'dummy', 'confirmed': True})
        self.assertEqual(status, 502)
        self.assertNotIn(FAKE_KEY, body)
        self.transport.assert_called_once()

    def test_read_actions_reject_symlink_keys_and_invalid_fields(self):
        target = Path(self.temp.name) / 'dummy-secret'
        target.write_text(FAKE_KEY)
        self.directory.mkdir()
        (self.directory / 'openai-api-key').symlink_to(target)
        self.assertEqual(self.action('/models', {'provider': 'openai'})[0], 400)
        for data in ({'provider': []}, {'provider': 'openai', 'key': []},
                     {'provider': 'openai', 'url': 'https://evil.example'}, [],
                     {'provider': 'openai', 'model': None}, {'provider': 'openai', 'routing': {}}):
            self.assertEqual(self.action('/models', data)[0], 400)
        self.transport.assert_not_called()

    def test_unknown_profile_settings_and_legacy_profile_survive_save(self):
        self.save()
        path = self.directory / 'provider.json'
        config = json.loads(path.read_text())
        config['profiles']['openai']['future_setting'] = 'keep'
        config['future_global'] = 'keep'
        path.write_text(json.dumps(config))
        self.settings.save('', 'updated')
        config = json.loads(path.read_text())
        self.assertEqual(config['future_global'], 'keep')
        self.assertEqual(config['profiles']['openai']['future_setting'], 'keep')
        path.write_text(json.dumps({'model': 'legacy-model'}))
        self.settings.save('sk-dummy-router-1234567890', 'router-model', 'openrouter')
        self.assertEqual(self.settings.status('openai')['model'], 'legacy-model')

    def test_page_and_save_never_read_keys_or_call_provider(self):
        self.save()
        with patch.object(self.settings, 'credential', side_effect=AssertionError('No key reads')):
            for path in ('/', '/status', '/status?provider=openai', '/setup.js'):
                self.assertEqual(self.request('GET', path)[0], 200)
            self.assertEqual(self.save(key='')[0], 200)
        self.transport.assert_not_called()
        script = self.request('GET', '/setup.js')[2]
        self.assertNotIn('localStorage', script)
        self.assertNotIn('sessionStorage', script)
        self.assertIn('window.confirm', script)
