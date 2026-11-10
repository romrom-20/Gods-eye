import http.client
import json
from pathlib import Path
import re
import stat
import tempfile
import threading
import unittest

from godseye.provider_setup import ProviderSettings, create_server

FAKE_KEY = 'sk-test-only-not-a-real-provider-key'


class ProviderSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'private'
        self.settings = ProviderSettings(self.directory)
        self.server = create_server(self.settings)
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
