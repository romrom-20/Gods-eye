import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from godseye.core import Store, digest
from godseye.export import export_demo
from godseye.jobs import JobQueue, QueueFull
from godseye.server import create_app
from godseye.storage import write_json


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = Store(self.directory.name)
        self.app = create_app(self.store)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.edit = {'base_id': 'paper', 'patch': 'W3[0:8:2, 1] = 0', 'hypothesis': 'Ablate left circuit'}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.directory.cleanup()

    def wait(self, job):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            row = self.client.get('/api/v1/jobs/' + job['id']).json()
            if row['status'] not in ('queued', 'running', 'cancelling'):
                return row
            time.sleep(.01)
        self.fail('Job did not terminate')

    def test_preview_is_read_only_and_hash_guard_is_enforced(self):
        before = list(Path(self.directory.name).iterdir())
        result = self.client.post('/api/v1/patches/preview', json=self.edit)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['changed'], 4)
        self.assertEqual(list(Path(self.directory.name).iterdir()), before)
        bad = dict(self.edit, expected_parent_sha256='0' * 64)
        self.assertEqual(self.client.post('/api/v1/checkpoints', json=bad).status_code, 409)
        good = dict(self.edit, expected_parent_sha256=result.json()['parent_sha256'])
        checkpoint = self.client.post('/api/v1/checkpoints', json=good)
        self.assertEqual(checkpoint.status_code, 201)
        self.assertEqual(checkpoint.json()['sha256'], result.json()['sha256'])
        self.assertEqual(digest(self.store.weights('paper')), result.json()['parent_sha256'])

    def test_actual_evaluation_progress_idempotency_and_persistence(self):
        branch = self.client.post('/api/v1/checkpoints', json=self.edit).json()
        body = dict(base_id='paper', candidate_id=branch['id'], episodes=2, max_steps=80, seed=20)
        first = self.client.post('/api/v1/jobs', json=body, headers={'Idempotency-Key': 'trial'})
        self.assertEqual(first.status_code, 202)
        second = self.client.post('/api/v1/jobs', json=body, headers={'Idempotency-Key': 'trial'})
        self.assertEqual(first.json()['id'], second.json()['id'])
        self.assertEqual(self.client.post('/api/v1/jobs', json=dict(body, seed=21), headers={'Idempotency-Key': 'trial'}).status_code, 409)
        done = self.wait(first.json())
        self.assertEqual(done['status'], 'succeeded')
        self.assertEqual(done['completed'], 4)
        run = self.client.get('/api/v1/runs/' + done['run_id']).json()
        self.assertEqual(run['candidate_sha256'], branch['sha256'])
        self.assertEqual(run['base_sha256'], branch['parent_sha256'])
        self.assertLessEqual(run['base']['forward_calls'] + run['candidate']['forward_calls'], 320)
        self.assertEqual(self.store.read_run(done['run_id'])['id'], run['id'])

    def test_rejects_executable_malformed_and_nonfinite_edits(self):
        for code in ["__import__('os').system('id')", 'b3[0] = 1e309', 'W1[::0, 0] = 1',
                     'W1[0, 0] = 1\nb3[9] = 1', 'b3[0] = True']:
            response = self.client.post('/api/v1/checkpoints', json=dict(self.edit, patch=code))
            self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(len(self.store.checkpoints()), 2)

    def test_mixed_boolean_literals_rejected_without_writes(self):
        before = {p.name: p.read_bytes() for p in Path(self.directory.name).iterdir()}
        original_hash = digest(self.store.weights('paper'))
        for code in ['b3[0:2] = [True, 2]', 'b3[0:2] += (1.0, False)',
                     'W3[0:2, 0:2] = [[1, 2], [3, True]]',
                     'b3[0] = 1\nb3[0:2] *= [False, 2]']:
            for route in ('patches/preview', 'checkpoints'):
                with self.subTest(code=code, route=route):
                    response = self.client.post('/api/v1/' + route,
                                                json=dict(self.edit, patch=code))
                    self.assertEqual(response.status_code, 400, response.text)
                    self.assertEqual(self.store.checkpoints(), [
                        {'id': 'paper', 'name': self.store.backend.initial_name, 'parent': None},
                        {'id': 'zero', 'name': 'Zero initialization', 'parent': None}])
                    self.assertEqual({p.name: p.read_bytes()
                                      for p in Path(self.directory.name).iterdir()}, before)
                    self.assertEqual(digest(self.store.weights('paper')), original_hash)

    def test_strict_inputs_budget_and_missing_artifacts(self):
        for change in [dict(episodes=True), dict(episodes='8'), dict(seed=-1),
                       dict(episodes=64, max_steps=10000), dict(unknown=2)]:
            body = dict(base_id='paper', candidate_id='zero', **change)
            self.assertEqual(self.client.post('/api/v1/jobs', json=body).status_code, 422)
        response = self.client.post('/api/v1/jobs', json={'base_id': 'paper', 'candidate_id': '0'*16})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get('/api/v1/tensor?id=../../secret').status_code, 400)
        self.assertEqual(self.client.get('/api/v1/jobs/missing').status_code, 404)

    def test_http_security_boundary(self):
        self.assertEqual(self.client.get('/api/v1/state', headers={'Host': 'evil.example'}).status_code, 403)
        for host in ['evil@testserver', 'testserver/evil', '[broken', 'testserver.evil']:
            self.assertEqual(self.client.get('/api/v1/state', headers={'Host': host}).status_code, 403)
        for headers in [{'Origin': 'https://evil.example'}, {'Origin': 'null'}, {'Sec-Fetch-Site': 'cross-site'}]:
            self.assertEqual(self.client.post('/api/v1/checkpoints', json=self.edit, headers=headers).status_code, 403)
        self.assertEqual(self.client.post('/api/v1/checkpoints', content='{}', headers={'Content-Type': 'text/plain'}).status_code, 415)
        self.assertEqual(self.client.post('/api/v1/checkpoints', content='x' * 70000, headers={'Content-Type': 'application/json'}).status_code, 413)
        self.assertEqual(self.client.post('/api/v1/checkpoints', content='{', headers={'Content-Type': 'application/json'}).status_code, 422)
        response = self.client.get('/')
        self.assertEqual(response.headers['x-frame-options'], 'DENY')
        self.assertIn("script-src 'self'", response.headers['content-security-policy'])
        self.assertNotIn('access-control-allow-origin', response.headers)

    def test_optional_token_and_demo_mode(self):
        with TestClient(create_app(readonly=True, token='secret')) as client:
            self.assertEqual(client.get('/api/v1/state').status_code, 401)
            headers = {'Authorization': 'Bearer secret'}
            state = client.get('/api/v1/state', headers=headers).json()
            self.assertEqual(state['mode'], 'recorded-demo')
            self.assertEqual(client.post('/api/v1/checkpoints', json=self.edit, headers=headers).status_code, 403)
            self.assertEqual(client.get('/api/v1/runs', headers=headers).status_code, 200)

    def test_schema_and_packaged_preset(self):
        schema = self.client.get('/api/v1/openapi.json').json()
        self.assertIn('/api/v1/jobs', schema['paths'])
        self.assertNotIn('/api/patch', schema['paths'])
        self.assertIn('W1[', self.client.get('/api/v1/presets/ball-chaser').json()['patch'])


class QueueTests(unittest.TestCase):
    def test_capacity_cancel_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            started, release = threading.Event(), threading.Event()
            original = store.run
            def blocked(**settings):
                started.set()
                release.wait(5)
                return original(**settings)
            with patch.object(store, 'run', side_effect=blocked):
                jobs = JobQueue(store, capacity=2)
                settings = dict(base_id='paper', candidate_id='paper', episodes=1, seed=20, max_steps=50)
                try:
                    first = jobs.submit(settings)
                    self.assertTrue(started.wait(2))
                    second = jobs.submit(settings)
                    with self.assertRaises(QueueFull):
                        jobs.submit(settings)
                    self.assertEqual(jobs.cancel(second['id'])['status'], 'cancelled')
                    jobs.cancel(first['id'])
                    release.set()
                finally:
                    release.set()
                    jobs.close()
                self.assertEqual(jobs.get(first['id'])['status'], 'cancelled')
                self.assertEqual(store.runs(), [])
            write_json(Path(directory) / 'job-dead.json', dict(id='dead', status='running', created=0))
            resumed = JobQueue(store)
            try:
                self.assertEqual(resumed.get('dead')['status'], 'interrupted')
                self.assertEqual(resumed.get(first['id'])['status'], 'cancelled')
            finally:
                resumed.close()

    def test_export_contains_only_bundled_public_data(self):
        with tempfile.TemporaryDirectory() as directory:
            output = export_demo(Path(directory) / 'site')
            data = json.loads((output / 'demo.json').read_text())
            self.assertEqual(data['state']['mode'], 'recorded-demo')
            self.assertEqual(len(data['runs']), 2)
            self.assertEqual(len(data['state']['checkpoints']), 4)
            self.assertEqual(set(data['tensors']), {'paper', 'zero',
                             'bba6b79c8ba04971', '86bbfe9d4157446f'})
            self.assertEqual({p.name for p in output.iterdir()}, {
                'index.html', 'lab.html', 'app.js', 'style.css', 'landing.css',
                'landing.js', 'api.html', 'LICENSE.txt', 'THIRD_PARTY_NOTICES.md',
                'demo.json', '.nojekyll', 'NETWORK-LICENSE.txt', 'NETWORK-PROVENANCE.md'})
            lab = (output / 'lab.html').read_text()
            self.assertNotIn('id="goal-form"', lab)
            self.assertIn('RECORDED PUBLIC DEMO', lab)
            self.assertNotIn('provider-setup.js', lab)
            self.assertIn('data-static-demo="true"', (output / 'lab.html').read_text())
            for run in data['traces'].values():
                self.assertIn(run['candidate_id'], data['tensors'])
            with self.assertRaises(ValueError):
                export_demo(output)


if __name__ == '__main__':
    unittest.main()
