"""No-key HTTP export, independently reloaded and evaluated real checkpoint fixtures."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

import numpy as np
from fastapi.testclient import TestClient

from godseye.checkpoint_artifact import canonical, content_hash, reload_artifact
from godseye.checkpoint_export import weights
from godseye.checkpoint_example import NumericWorker
from godseye.core import Store, compare, digest, load_weights, save_weights
from godseye.evaluator import Evaluator
from godseye.experiment_spec import TERMINAL
from godseye.orchestration import Orchestrator
from godseye.provider_setup import ProviderSettings
from godseye.server import create_app
from goal_acceptance_support import ScriptedWorker, PROVIDER_SECRET, goal_request, start_request

BASE = '/api/v1/experiments/'


class CheckpointExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = ProviderSettings(self.root / 'keys')
        self.settings.save(PROVIDER_SECRET, 'scripted-acceptance')
        self.store = Store(self.root / 'lab')
        self.immutable_sources = {}
        self.paper = digest(self.store.weights('paper'))
        self.services = []
        self.addCleanup(lambda: [s.close() for s in self.services])
        self.clients = []
        self.addCleanup(lambda: [c.close() for c in self.clients])
        for target in ('urllib.request.urlopen', 'httpx.HTTPTransport.handle_request',
                       'socket.socket.connect', 'socket.socket.connect_ex'):
            p = patch(target, side_effect=AssertionError('External network prohibited'))
            p.start()
            self.addCleanup(p.stop)

    def completed(self, changed=False, worker_override=None, expected='completed'):
        index = len(self.services)
        worker = worker_override or (NumericWorker() if changed else ScriptedWorker())
        service = Orchestrator(self.root / ('service%d' % index), worker=worker, settings=self.settings)
        self.services.append(service)
        private = self.root / ('private%d' % index)
        Evaluator.create(private, instances=1, episodes=2, max_steps=200 if changed else 1,
                         probes=2, forward_budget=800 if changed else 4)
        for state_file in private.glob('*/private-state.json'):
            state = json.loads(state_file.read_text())
            state['_export_private_canary'] = 'SECRET_PRIVATE_REPORT_CANARY'
            state_file.write_text(json.dumps(state))
        service.register(private, baseline_id='export_roots', suite_id='export_suite', revision='v1')
        self.immutable_sources.update({p: p.read_bytes() for p in private.glob('*/*.npz')})
        client = self.client(service)
        plan = client.post(BASE + 'plan', json=goal_request()).json()
        run = client.post(BASE + 'start', json=start_request(plan)).json()
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            result = service.status(dict(schema_version=1, experiment_id=run['experiment_id']))
            if result['status'] in TERMINAL:
                break
            time.sleep(.02)
        self.assertEqual(expected, result['status'], result)
        result = service.results(dict(schema_version=1, experiment_id=run['experiment_id']))
        request = dict(schema_version=1, experiment_id=run['experiment_id'],
                       artifact_id=result['evidence']['candidate_manifest_id'] if result['evidence'] else '0'*32)
        return service, worker, client, private, request

    def client(self, service, **kwargs):
        client = TestClient(create_app(self.store, orchestration=service, **kwargs))
        self.clients.append(client)
        return client

    def export(self, client, request):
        response = client.post(BASE + 'export', json=request)
        self.assertEqual(200, response.status_code, response.text[:300])
        self.assertIn('attachment;', response.headers['content-disposition'])
        self.assertEqual('no-store', response.headers['cache-control'])
        data = response.json()
        self.assertNotIn(PROVIDER_SECRET, response.text)
        self.assertNotIn('SECRET_PRIVATE_REPORT_CANARY', response.text)
        self.assertNotIn(str(self.root), response.text)
        forbidden = {'case_id', 'family', 'seed', 'dev_seed', 'held_seed', 'reference',
                     'path', 'directory', 'hypothesis', 'participants'}
        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(forbidden.intersection(value))
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        inspect(data)
        return response, data

    def test_unchanged_repeat_reads_no_worker_provider_or_evaluator(self):
        service, worker, client, private, request = self.completed()
        originals = {p: p.read_bytes() for p in private.glob('*/*.npz')}
        with patch.object(worker, 'execute', side_effect=AssertionError('Worker on read')), \
             patch.object(Evaluator, 'dispatch', side_effect=AssertionError('Evaluation on read')), \
             patch.object(Evaluator, 'report', side_effect=AssertionError('Reveal on read')), \
             patch.object(self.settings, 'credential', side_effect=AssertionError('Secret on read')):
            first, value = self.export(client, request)
            second, _ = self.export(client, request)
            self.assertEqual(first.content, second.content)
            reloaded = reload_artifact(first.content, expected_sha256=value['content_sha256'])
        self.assertTrue(all(r['outcome'] == 'unchanged' and r['delta'] == [] for r in value['checkpoints']))
        self.assertTrue(all(digest(a) == digest(b) for a, b in reloaded))
        self.assertEqual(originals, {p: p.read_bytes() for p in originals})
        self.assertEqual(self.paper, digest(self.store.weights('paper')))

    def test_changed_selection_independent_process_reload_hash_and_paired_evaluation(self):
        service, worker, client, private, request = self.completed(changed=True)
        response, value = self.export(client, request)
        self.assertTrue(any(r['outcome'] == 'changed' for r in value['checkpoints']),
                        'Fixture must produce a real dev improvement; never fabricate one')
        path = self.root / 'download.json'
        path.write_bytes(response.content)
        script = '''import json,sys
from pathlib import Path
from godseye.checkpoint_artifact import reload_artifact
from godseye.core import digest,save_weights
pairs=reload_artifact(Path(sys.argv[1]).read_bytes(),expected_sha256=sys.argv[2])
for i,(a,b) in enumerate(pairs):
 save_weights(Path(sys.argv[3])/('selected%d.npz'%i),b)
 save_weights(Path(sys.argv[3])/('original%d.npz'%i),a)
print(json.dumps([[digest(a),digest(b)] for a,b in pairs]))
'''
        process = subprocess.run([sys.executable, '-c', script, str(path),
                                  value['content_sha256'], str(self.root)],
                                 capture_output=True, text=True, check=True)
        hashes = json.loads(process.stdout)
        state = json.loads((private / 'agent/private-state.json').read_text())
        for slot, case in enumerate(state['cases']):
            row = value['checkpoints'][slot]
            self.assertEqual(hashes[slot], [row['original_sha256'], row['selected_sha256']])
            original = load_weights(private / 'agent' / (case['root_id'] + '.npz'))
            selected = load_weights(private / 'agent' / (case['final']['candidate_id'] + '.npz'))
            loaded = load_weights(self.root / ('selected%d.npz' % slot))
            rollback = load_weights(self.root / ('original%d.npz' % slot))
            self.assertEqual(digest(original), digest(rollback))
            self.assertEqual(digest(selected), digest(loaded))
            actual = compare(original, loaded, episodes=2, seed=case['held_seed'], max_steps=200)
            self.assertEqual([e['score'] for e in actual['base']['episodes']], case['final']['corrupted']['scores'])
            self.assertEqual([e['score'] for e in actual['candidate']['episodes']], case['final']['selected']['scores'])
            if row['outcome'] == 'changed':
                attempts = case['attempts']
                self.assertEqual(case['root_id'], attempts[0]['candidate_id'])
                self.assertEqual(case['final']['candidate_id'], attempts[1]['candidate_id'])
                self.assertGreater(attempts[1]['result']['mean_score'], attempts[0]['result']['mean_score'])
        self.assertEqual(self.paper, digest(self.store.weights('paper')))
        self.assertEqual(self.immutable_sources, {p: p.read_bytes() for p in self.immutable_sources})
        changed = next(c for c in state['cases'] if c['root_id'] != c['final']['candidate_id'])
        selected_path = private / 'agent' / (changed['final']['candidate_id'] + '.npz')
        original_bytes = selected_path.read_bytes()
        tampered = load_weights(selected_path)
        tampered['W1'][0, 0] += 1
        save_weights(selected_path, tampered)
        self.assertEqual(404, client.post(BASE + 'export', json=request).status_code)
        selected_path.write_bytes(original_bytes)

    def test_http_authorization_readonly_foreign_and_traversal(self):
        service, worker, client, private, request = self.completed()
        secured = self.client(service, token='operator-test-token')
        self.assertEqual(403, secured.post(BASE + 'export', json=request).status_code)
        self.assertEqual(200, secured.post(BASE + 'export', json=request,
                         headers={'Authorization': 'Bearer operator-test-token'}).status_code)
        for headers in ({'Host': 'evil.invalid'}, {'Origin': 'https://evil.invalid'},
                        {'Sec-Fetch-Site': 'cross-site'}):
            self.assertEqual(403, client.post(BASE + 'export', json=request, headers=headers).status_code)
        self.assertEqual(403, self.client(service, readonly=True).post(BASE + 'export', json=request).status_code)
        for change in (dict(artifact_id='0'*32), dict(artifact_id='../private-state'),
                       dict(experiment_id='0'*32), dict(experiment_id='../private')):
            bad = client.post(BASE + 'export', json=dict(request, **change))
            self.assertEqual(404, bad.status_code, bad.text)
            self.assertEqual('none', bad.json()['retry']['action'])
            self.assertNotIn(str(self.root), bad.text)
        other, _, _, _, foreign = self.completed()
        self.assertEqual(404, client.post(BASE + 'export', json=dict(request,
            artifact_id=foreign['artifact_id'])).status_code)
        self.assertEqual(404, self.client(other).post(BASE + 'export', json=request).status_code)

    def test_missing_tampered_symlink_and_private_artifact_membership(self):
        service, worker, client, private, request = self.completed()
        row = service.load(request['experiment_id'], 'run')
        for field in ('candidate_manifest_id', 'delta_artifact_id', 'report_id'):
            path = Path(row['artifacts'][row['evidence'][field]])
            original = path.read_bytes()
            path.write_text('[]')
            self.assertEqual(404, client.post(BASE + 'export', json=request).status_code)
            path.unlink()
            self.assertEqual(404, client.post(BASE + 'export', json=request).status_code)
            foreign = self.root / 'foreign.json'
            foreign.write_bytes(original)
            path.symlink_to(foreign)
            self.assertEqual(404, client.post(BASE + 'export', json=request).status_code)
            path.unlink()
            path.write_bytes(original)
        state = json.loads((private / 'agent/private-state.json').read_text())
        path = private / 'agent' / (state['cases'][0]['root_id'] + '.npz')
        original = path.read_bytes()
        altered = load_weights(path)
        altered['W1'][0, 0] += 1
        save_weights(path, altered)
        self.assertEqual(404, client.post(BASE + 'export', json=request).status_code)
        path.write_bytes(original)
        with service.transaction():
            row['artifacts'][request['artifact_id']] = str(self.root / 'foreign.json')
            service.save(row['id'], 'run', row)
        self.assertEqual(404, client.post(BASE + 'export', json=request).status_code)

    def test_independent_loader_rejects_corruption_even_with_rehashed_payload(self):
        _, _, client, _, request = self.completed()
        response, value = self.export(client, request)
        for mutate in (
            lambda v: v['checkpoints'][0]['original']['W1'].pop(),
            lambda v: v['checkpoints'][0]['original']['W1'].__setitem__(0, float('inf')),
            lambda v: v['checkpoints'][0].__setitem__('selected_sha256', '0'*64),
            lambda v: v['checkpoints'][0]['delta'].append(dict(tensor='W1', index=0, before=999., after=1.)),
            lambda v: v['checkpoints'][0].__setitem__('outcome', 'changed'),
            lambda v: v.__setitem__('provider_text', 'private'),
        ):
            altered = copy.deepcopy(value)
            mutate(altered)
            with self.assertRaises(ValueError):
                altered['content_sha256'] = content_hash(altered)
                reload_artifact(canonical(altered), expected_sha256=altered['content_sha256'])
        # Replacement deltas retain signed zero, unlike subtract/add reconstruction.
        signed = copy.deepcopy(value)
        original, selected = reload_artifact(response.content, expected_sha256=value['content_sha256'])[0]
        original['W1'].flat[0] = np.float32(0.)
        selected['W1'].flat[0] = np.float32(-0.)
        row = signed['checkpoints'][0]
        row['original']['W1'][0] = 0.
        row['original_sha256'], row['selected_sha256'] = digest(original), digest(selected)
        row['outcome'] = 'changed'
        row['delta'] = [dict(tensor='W1', index=0, before=0., after=-0.)]
        signed['content_sha256'] = content_hash(signed)
        a, b = reload_artifact(canonical(signed), expected_sha256=signed['content_sha256'])[0]
        self.assertFalse(np.signbit(a['W1'].flat[0]))
        self.assertTrue(np.signbit(b['W1'].flat[0]))
        with self.assertRaises(ValueError):
            reload_artifact(response.content, expected_sha256='0'*64)
        with self.assertRaises(ValueError):
            reload_artifact(b'{"schema_version":1,"schema_version":1}', expected_sha256='0'*64)

    def test_invalid_requests_and_incomplete_run_never_export(self):
        service, worker, client, private, request = self.completed()
        for body in (dict(request, schema_version=2), dict(request, schema_version=True),
                     dict(request, path='/private'), {'schema_version': 1}):
            self.assertEqual(400, client.post(BASE + 'export', json=body).status_code)
        duplicate = b'{"schema_version":1,"schema_version":1}'
        self.assertEqual(400, client.post(BASE + 'export', content=duplicate,
                         headers={'Content-Type': 'application/json'}).status_code)
        with service.transaction():
            row = service.load(request['experiment_id'], 'run')
            row['status'] = 'failed'
            row['evidence'] = None
            service.save(row['id'], 'run', row)
        response = client.post(BASE + 'export', json=request)
        self.assertEqual(409, response.status_code)
        self.assertEqual('result_not_ready', response.json()['error']['code'])

    def test_changed_candidate_without_prior_root_probe_is_never_trusted(self):
        class InvalidSelectionWorker(NumericWorker):
            def execute(self, row, registration, directory, settings, check, accounting):
                evaluator = Evaluator(registration['directory'])
                for role in ('unchanged', 'heuristic', 'agent'):
                    for case in evaluator.dispatch(role, 'list', {})['cases']:
                        chosen = case['root_id']
                        if role == 'agent':
                            candidate = evaluator.dispatch(role, 'patch', dict(case_id=case['id'],
                                parent_id=chosen, patch='W3[:, :] *= -1', hypothesis='Invalid order fixture'))
                            chosen = candidate['id']
                        args = dict(case_id=case['id'], candidate_id=chosen)
                        evaluator.dispatch(role, 'evaluate', args)
                        evaluator.dispatch(role, 'freeze', args)
                # Production assembler must reject this selection, despite complete real scores.
                evaluator.report()
        service, _, client, _, request = self.completed(worker_override=InvalidSelectionWorker(), expected='failed')
        self.assertIsNone(service.load(request['experiment_id'], 'run')['evidence'])
        self.assertEqual(409, client.post(BASE + 'export', json=request).status_code)

    def test_npz_header_size_dtype_and_finite_bounds(self):
        private = self.root / 'bounded'
        (private / 'agent').mkdir(parents=True)
        identifier = '1'*32
        path = private / 'agent' / (identifier + '.npz')
        source = self.store.weights('paper')
        save_weights(path, source)
        self.assertEqual(digest(source), digest(weights(private, 'agent', identifier)))
        original_archive = path.read_bytes()
        for shape, descriptor in (((10**12, 32), '<f4'), ((600, 32), '|O')):
            header = io.BytesIO()
            np.lib.format.write_array_header_1_0(header, dict(descr=descriptor,
                fortran_order=False, shape=shape))
            rewritten = io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(original_archive)) as source_zip, \
                 zipfile.ZipFile(rewritten, 'w') as target_zip:
                for member in source_zip.infolist():
                    data = header.getvalue() if member.filename == 'actor/dense1/kernel.npy' else source_zip.read(member)
                    target_zip.writestr(member.filename, data)
            path.write_bytes(rewritten.getvalue())
            with self.assertRaises(ValueError):
                weights(private, 'agent', identifier)
        source['W1'][0, 0] = np.nan
        save_weights(path, source)
        with self.assertRaises(ValueError):
            weights(private, 'agent', identifier)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('actor/dense1/kernel.npy', b'0' * 110000)
        path.write_bytes(buffer.getvalue())
        with self.assertRaises(ValueError):
            weights(private, 'agent', identifier)


if __name__ == '__main__':
    unittest.main()
