import concurrent.futures
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import HTTPServer
from unittest.mock import patch

from godseye.benchmark import RepairBenchmark
from godseye.evaluator import Evaluator, handler
from isolation.agent_adapter import Client, Evidence, post, run_agent


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.ev = Evaluator.create(self.path, instances=2, probes=2,
                                   forward_budget=16, episodes=1, max_steps=8)
        self.server = HTTPServer(('127.0.0.1', 0), handler(self.ev))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = 'http://127.0.0.1:' + str(self.server.server_port)
        self.token = (self.path / 'agent.token').read_text()
        self.client = Client(self.url, self.token)
        self.case = self.client.call('list', {})['cases'][0]

    def args(self, candidate=None):
        return dict(case_id=self.case['id'], candidate_id=candidate or self.case['root_id'])

    def test_auth_private_artifacts_and_allowlist(self):
        import urllib.error
        for path in ('/rpc', '/private-state.json', '/report'):
            with self.assertRaises(urllib.error.HTTPError) as error:
                post(self.url + path, 'wrong', {})
            self.assertEqual(error.exception.code, 401)
        for op in ('report', 'exec', 'open', '../../private-state.json'):
            with self.assertRaises(ValueError):
                self.ev.dispatch('agent', op, {})
        for tensor in ('private-state.json', '../../paper.npz', 'generation_seed'):
            result = self.client.call('read', dict(**self.args(), tensor=tensor, start=0, count=1))
            self.assertIn('error', result)
        with self.assertRaises(urllib.error.HTTPError) as error:
            post(self.url + '/report', self.token, {})
        self.assertEqual(error.exception.code, 403)
        public = json.dumps(self.client.call('list', {}))
        for key in ('family', 'seed', 'reference_id', 'token', 'held_seed'):
            self.assertNotIn(key, public)

    def test_bounded_reads_and_cross_experiment_ids(self):
        valid = dict(**self.args(), tensor='W1', start=0, count=256)
        self.assertEqual(len(self.client.call('read', valid)['values']), 256)
        for delta in ({'count': 257}, {'count': True}, {'start': -1}, {'start': 19200},
                      {'candidate_id': '../private-state'}, {'extra': 'path'}):
            self.assertIn('error', self.client.call('read', dict(valid, **delta)))
        other = Evaluator.create(self.path / 'other', instances=1, episodes=1, max_steps=1)
        foreign = other.dispatch('agent', 'list', {})['cases'][0]
        for operation, args in (
            ('read', dict(valid, candidate_id=foreign['root_id'])),
            ('read', dict(valid, case_id=foreign['id'])),
            ('evaluate', self.args(foreign['root_id'])),
            ('freeze', self.args(foreign['root_id'])),
            ('patch', dict(case_id=self.case['id'], parent_id=foreign['root_id'],
                           patch='b3[0] += 1', hypothesis='test'))):
            self.assertIn('error', self.client.call(operation, args))
        # A valid ID from another participant is also unusable.
        foreign = self.ev.dispatch('heuristic', 'list', {})['cases'][0]
        self.assertIn('error', self.client.call('evaluate', self.args(foreign['root_id'])))

    def test_invalid_patches_and_immutable_lineage(self):
        args = dict(case_id=self.case['id'], parent_id=self.case['root_id'], hypothesis='test')
        for code in ('import os', 'b3[0] = __import__("os").getcwd()',
                     'b3[0] = 1e309', 'b3[999] = 0', 'W1[:] = [1, 2]', 'b3[0] = True'):
            self.assertIn('error', self.client.call('patch', dict(args, patch=code)))
        before = self.client.call('read', dict(**self.args(), tensor='b3', start=0, count=6))
        result = self.client.call('patch', dict(args, patch='b3[0] += 1'))
        self.assertIn('id', result)
        self.assertEqual(before, self.client.call('read', dict(**self.args(), tensor='b3', start=0, count=6)))
        self.client.call('freeze', self.args(result['id']))
        self.assertIn('error', self.client.call('freeze', self.args()))
        self.assertIn('error', self.client.call('patch', dict(args, patch='b3[0] += 2')))
        self.assertIn('error', self.client.call('evaluate', self.args()))
        reload = Evaluator(self.path)
        with self.assertRaises(ValueError):
            reload.dispatch('agent', 'freeze', self.args())

    def test_concurrent_probe_reservations_never_overspend(self):
        bench = RepairBenchmark(self.path / 'agent')
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(self.client.call, 'evaluate', self.args()) for _ in range(8)]
        self.assertEqual(sum('result' in f.result() for f in futures), 2)
        case = bench.cases()[0]
        self.assertEqual((case['probes_used'], case['forward_reserved']), (2, 16))

    def test_independent_processes_share_admission_lock(self):
        code = """import sys
from godseye.benchmark import RepairBenchmark
try:
    RepairBenchmark(sys.argv[1]).probe(sys.argv[2],sys.argv[3])
except ValueError:
    sys.exit(17)
"""
        command = [sys.executable, '-c', code, str(self.path / 'agent'),
                   self.case['id'], self.case['root_id']]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(subprocess.run, command, capture_output=True) for _ in range(4)]
        self.assertEqual(sorted(f.result().returncode for f in futures), [0, 0, 17, 17])
        case = Evaluator(self.path).dispatch('agent', 'list', {})['cases'][0]
        self.assertEqual((case['probes_remaining'], case['forwards_remaining']), (0, 0))

    def test_deferred_final_failure_is_retained_without_retry(self):
        for role in ('unchanged', 'heuristic', 'agent'):
            for case in self.ev.dispatch(role, 'list', {})['cases']:
                self.ev.dispatch(role, 'freeze', dict(case_id=case['id'], candidate_id=case['root_id']))
        with patch.object(RepairBenchmark, '_evaluate', side_effect=RuntimeError('synthetic')):
            with self.assertRaises(RuntimeError):
                self.ev.report()
        report = Evaluator(self.path).report()
        first = report['participants']['unchanged']['cases'][0]
        self.assertEqual(first['final']['status'], 'failed')
        self.assertEqual(first['final']['forward_reserved'], 24)
        with self.assertRaises(ValueError):
            self.ev.dispatch('unchanged', 'freeze', dict(case_id=first['id'], candidate_id=first['root_id']))

    def test_provider_failure_is_recorded_without_credentials(self):
        evidence = Evidence(self.path / 'failure.jsonl')
        def respond(body):
            raise RuntimeError('Provider failure ' + self.token)
        try:
            with self.assertRaises(RuntimeError) as error:
                run_agent(self.client, respond, evidence, model='scripted-test')
        finally:
            evidence.stream.close()
        self.assertNotIn(self.token, str(error.exception))
        saved = (self.path / 'failure.jsonl').read_text()
        self.assertNotIn(self.token, saved)
        self.assertEqual(json.loads(saved.splitlines()[-1])['event'], 'failed')

    def test_failure_and_process_death_preserve_budgets(self):
        bench = RepairBenchmark(self.path / 'agent')
        with patch.object(RepairBenchmark, '_evaluate', side_effect=RuntimeError('private/path')):
            result = self.client.call('evaluate', self.args())
        self.assertEqual(result['status'], 500)
        self.assertNotIn('private', json.dumps(result))
        code = '''import os,sys
from godseye.benchmark import RepairBenchmark
b=RepairBenchmark(sys.argv[1])
b._evaluate=lambda *args: os._exit(23)
b.probe(sys.argv[2],sys.argv[3])
'''
        result = subprocess.run([sys.executable, '-c', code, str(self.path / 'agent'),
                                 self.case['id'], self.case['root_id']], capture_output=True)
        self.assertEqual(result.returncode, 23)
        case = Evaluator(self.path).dispatch('agent', 'list', {})['cases'][0]
        self.assertEqual((case['probes_remaining'], case['forwards_remaining']), (0, 0))
        state = json.loads(bench.state_path.read_text())['cases'][0]
        self.assertEqual([a['status'] for a in state['attempts']], ['failed', 'interrupted'])
        self.assertIn('error', self.client.call('evaluate', self.args()))

    def test_global_reveal_gate_and_multiple_instances(self):
        # Freeze two participants and all but one agent case: no held-out work.
        cases = []
        for role in ('unchanged', 'heuristic', 'agent'):
            for case in self.ev.dispatch(role, 'list', {})['cases']:
                cases.append((role, case))
        last_role, last = cases.pop()
        for role, case in cases:
            self.ev.dispatch(role, 'freeze', dict(case_id=case['id'], candidate_id=case['root_id']))
        with self.assertRaises(ValueError):
            self.ev.report()
        private = json.loads((self.path / 'agent/private-state.json').read_text())
        self.assertFalse(any('selected' in (c['final'] or {}) for c in private['cases']))
        self.ev.dispatch(last_role, 'freeze', dict(case_id=last['id'], candidate_id=last['root_id']))
        report = self.ev.report()
        self.assertEqual(report, self.ev.report())
        for participant in report['participants'].values():
            families = [c['family'] for c in participant['cases']]
            self.assertEqual({f: families.count(f) for f in families},
                             dict(control=2, sign_flip=2, channel_ablation=2, bias_shift=2))
            for case in participant['cases']:
                self.assertEqual(case['final']['delta_from_corrupted'], 0)

    def test_scripted_agent_uses_real_http_and_retains_failed_attempts(self):
        cases = self.client.call('list', {})['cases']
        calls = [('list', {}), ('exec', {'code': 'open("private-state.json")'})]
        for case in cases:
            args = dict(case_id=case['id'], candidate_id=case['root_id'])
            calls.extend([('read', dict(args, tensor='b3', start=0, count=6)),
                          ('evaluate', args),
                          ('patch', dict(case_id=case['id'], parent_id=case['root_id'],
                                         patch='import os', hypothesis='invalid attempt')),
                          ('patch', dict(case_id=case['id'], parent_id=case['root_id'],
                                         patch='b3[0] += 1', hypothesis='Scripted valid integration edit')),
                          ('evaluate', dict(args, candidate_id='$candidate')),
                          ('freeze', dict(args, candidate_id='$candidate'))])
        def respond(body):
            self.assertFalse(any(t['type'] != 'function' for t in body['tools']))
            self.assertNotIn(self.token, json.dumps(body))
            if not calls:
                return {'output': [], 'status': 'completed'}
            name, args = calls.pop(0)
            if args.get('candidate_id') == '$candidate':
                candidate = next(json.loads(m['output'])['id'] for m in reversed(body['input'])
                                 if m.get('type') == 'function_call_output'
                                 and 'diff' in json.loads(m['output']))
                args = dict(args, candidate_id=candidate)
            return {'output': [dict(type='function_call', name=name,
                                    arguments=json.dumps(args), call_id=str(len(calls)))]}
        evidence = Evidence(self.path / 'evidence.jsonl')
        try:
            self.assertTrue(run_agent(self.client, respond, evidence, model='scripted-test'))
        finally:
            evidence.stream.close()
        rows = [json.loads(line) for line in (self.path / 'evidence.jsonl').read_text().splitlines()]
        self.assertTrue(any(r.get('name') == 'patch' and 'error' in r['result'] for r in rows))
        self.assertTrue(any(r.get('name') == 'patch' and 'id' in r['result'] for r in rows))
        self.assertNotIn(self.token, json.dumps(rows))
        self.assertTrue(all(c['finalized'] for c in self.client.call('list', {})['cases']))

    def test_adapter_ceiling_does_not_silently_freeze(self):
        evidence = Evidence(self.path / 'ceiling.jsonl')
        try:
            self.assertFalse(run_agent(self.client, lambda body: {'output': [dict(
                type='function_call', name='list', arguments='{}', call_id='one')]},
                evidence, model='scripted-test', max_calls=1))
        finally:
            evidence.stream.close()
        self.assertFalse(any(c['finalized'] for c in self.client.call('list', {})['cases']))
