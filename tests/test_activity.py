"""Offline actual adapter/evaluator journal checks; no operator credentials/provider calls."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from godseye.activity import Journal
from godseye.benchmark import RepairBenchmark
from godseye.core import Store
from godseye.evaluator import Evaluator
from godseye.orchestration import Orchestrator
from godseye.provider_setup import ProviderSettings
from godseye.server import create_app
from goal_acceptance_support import ScriptedWorker, PROVIDER_SECRET, goal_request, start_request, query


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / 'private'
        Evaluator.create(self.private, instances=1, episodes=2, max_steps=1, probes=2, forward_budget=4)
        self.settings = ProviderSettings(self.root / 'keys')
        self.settings.save(PROVIDER_SECRET, 'scripted-acceptance')
        self.worker = ScriptedWorker()
        self.service = Orchestrator(self.root / 'service', worker=self.worker, settings=self.settings)
        self.addCleanup(self.service.close)
        self.service.register(self.private, baseline_id='activity', suite_id='suite', revision='v1')
        self.app = create_app(Store(self.root / 'lab'), orchestration=self.service, token='test-auth')
        self.client = TestClient(self.app, headers={'Authorization': 'Bearer test-auth'})
        self.addCleanup(self.client.close)
        self.outbound = patch('urllib.request.urlopen', side_effect=AssertionError('No provider transport'))
        self.outbound.start()
        self.addCleanup(self.outbound.stop)

    def start(self):
        return self.service.start(start_request(self.service.plan(goal_request())))

    def wait(self, run):
        for _ in range(1000):
            result = self.service.status(query(run))
            if result['status'] in ('completed', 'failed', 'cancelled', 'interrupted'):
                return result
            time.sleep(.005)
        self.fail('worker did not settle')

    def read(self, run, after=0, limit=100):
        return self.client.post('/api/v1/experiments/activity', json=dict(
            schema_version=1, experiment_id=run['experiment_id'], spec_hash=run['spec_hash'],
            after=after, limit=limit))

    def test_actual_worker_evaluator_order_pagination_redaction_and_old_runs(self):
        run = self.start()
        self.assertEqual(self.wait(run)['status'], 'completed')
        self.assertIn('/api/v1/experiments/activity',self.app.openapi()['paths'])
        response = self.read(run, limit=7)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['cache-control'])
        events, cursor = [], 0
        while True:
            body = self.read(run, cursor, 7).json()
            self.assertTrue(body['available'])
            self.assertLessEqual(len(body['events']), 7)
            events.extend(body['events'])
            cursor = body['next_cursor']
            if not body['has_more']:
                break
        self.assertEqual([e['sequence'] for e in events], list(range(1, cursor + 1)))
        self.assertEqual(events[0]['kind'], 'worker_started')
        self.assertEqual(events[-1]['kind'], 'worker_finished')
        for i, e in enumerate(events):
            if e['kind'] in ('root_probe_reserved', 'candidate_probe_reserved'):
                self.assertEqual(events[i + 1]['kind'], 'activity_finished')
        freezes = [e['sequence'] for e in events if e['kind'] == 'selection_frozen']
        held = [e['sequence'] for e in events if e['kind'] == 'held_out_reserved']
        self.assertTrue(freezes and held)
        self.assertLess(max(freezes), min(held))
        public = json.dumps(body) + json.dumps(events)
        config = json.loads((self.private / 'experiment.json').read_text())
        private_state = json.loads((self.private / 'agent/private-state.json').read_text())
        forbidden = [PROVIDER_SECRET, str(self.root), *config['tokens'].values(),
                     *[p.read_text() for p in self.private.glob('*.token')],
                     *[c['id'] for c in private_state['cases']]]
        for secret in forbidden:
            self.assertNotIn(secret, public)
        self.assertEqual(body['phase']['name'], 'unknown')
        self.assertEqual(body['phase']['event_sequence'], cursor)
        self.assertEqual(self.read(run, 0, 7).json()['events'], events[:7])
        self.assertTrue(self.read(run, cursor + 1).json()['gap'])
        self.assertLess(len(self.read(run).content), 40000)
        Journal(self.private).path.unlink()
        lost = self.read(run).json()
        self.assertEqual(lost['phase']['event_sequence'],cursor)
        self.assertFalse(lost['available'])
        # Simulate a genuine pre-journal run: it has neither file nor persisted fence.
        with self.service.transaction():
            row = self.service.load(run['experiment_id'],'run')
            row.pop('activity_fence',None)
            row.pop('activity_gap_fence',None)
            self.service.save(row['id'],'run',row)
        old = self.read(run).json()
        self.assertFalse(old['available'])
        self.assertEqual(old['events'], [])
        self.assertEqual(old['phase'], dict(name='unknown', event_sequence=None))

    def test_browser_fixture_uses_actual_export_and_independent_reload(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('activity_browser_fixture',
            Path(__file__).parent / 'browser/activity_backend.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        run = self.start(); self.wait(run)
        app = fixture.create_app(Store(self.root / 'fixture-lab'), orchestration=self.service)
        client = TestClient(app)
        self.addCleanup(client.close)
        expected = client.post('/__fixture/checkpoint-hashes',json=query(run)).json()
        result = self.service.results(query(run))
        request = dict(schema_version=1,experiment_id=run['experiment_id'],
                       artifact_id=result['evidence']['candidate_manifest_id'])
        self.assertEqual(client.post('/__fixture/export-mode',json=dict(query(run),ok=False)).status_code,200)
        failure = client.post('/api/v1/experiments/export',json=request)
        self.assertEqual(failure.status_code,404)
        self.assertEqual(failure.json()['error']['code'],'not_found')
        self.assertEqual(client.post('/__fixture/export-mode',json=dict(query(run),ok=True)).status_code,200)
        download = client.post('/api/v1/experiments/export',json=request)
        self.assertEqual(download.status_code,200)
        self.assertIn('attachment',download.headers['content-disposition'])
        artifact = download.json()
        path = self.root / 'browser-export.json'; path.write_bytes(download.content)
        script = """
import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from godseye.checkpoint_artifact import reload_artifact
from godseye.core import digest
pairs=reload_artifact(Path(sys.argv[2]).read_bytes(),expected_sha256=sys.argv[3])
print(json.dumps([[digest(a),digest(b)] for a,b in pairs]))
"""
        process = subprocess.run([expected['python_executable'],'-I','-c',script,
            expected['source_root'],str(path),artifact['content_sha256']],
            capture_output=True,text=True,timeout=20,check=True)
        self.assertEqual(json.loads(process.stdout),expected['hashes'])
        self.assertEqual(expected['hashes'],[[r['original_sha256'],r['selected_sha256']]
                                           for r in artifact['checkpoints']])
        self.assertEqual(len(self.worker.calls),1)
        self.assertEqual(self.worker.key_reads,1)

    def test_live_reservation_and_finish_reset_before_next_provider_request(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        actual = RepairBenchmark._evaluate
        blocked = [False]
        def evaluate(weights, seed, state):
            if not blocked[0]:
                blocked[0] = True
                entered.set()
                if not release.wait(5):
                    raise AssertionError('barrier timeout')
            return actual(weights, seed, state)
        with patch.object(RepairBenchmark, '_evaluate', side_effect=evaluate):
            run = self.start()
            self.assertTrue(entered.wait(5))
            live = self.service.status(query(run))
            self.assertEqual(live['phase']['name'], 'checking_original')
            self.assertIsInstance(live['phase']['event_sequence'], int)
            release.set()
            self.wait(run)
        # Standalone evaluator proves an operation reset immediately on return.
        fresh = self.root / 'journal-only'; fresh.mkdir()
        journal = Journal(fresh); journal.initialize(run['experiment_id'],run['spec_hash'])
        journal.emit('root_probe_reserved', 'evaluate', 'agent')
        self.assertEqual(journal.read(run['experiment_id'], run['spec_hash'], 'running')['phase']['name'], 'checking_original')
        journal.emit('activity_finished', 'evaluate', 'agent')
        self.assertEqual(journal.read(run['experiment_id'], run['spec_hash'], 'running')['phase']['name'], 'unknown')

    def test_missing_rows_replay_scope_and_boundary_fail_closed(self):
        run = self.start(); self.wait(run)
        original = self.read(run).json()
        self.assertEqual(self.client.post('/api/v1/experiments/activity', json={}).status_code, 400)
        body = dict(schema_version=1, experiment_id=run['experiment_id'], spec_hash=run['spec_hash'], after=0, limit=100)
        for change in ({'limit':101}, {'after':True}, {'limit':False}, {'extra':'private'}):
            self.assertEqual(self.client.post('/api/v1/experiments/activity', json=dict(body, **change)).status_code,400)
        self.assertEqual(self.client.post('/api/v1/experiments/activity',json=dict(body,spec_hash='0'*64)).status_code,409)
        self.assertEqual(self.client.post('/api/v1/experiments/activity',json=dict(body,experiment_id='foreign')).status_code,404)
        self.assertEqual(self.client.post('/api/v1/experiments/activity',json=body,headers={'Authorization':'Bearer wrong'}).status_code,403)
        self.assertEqual(self.client.post('/api/v1/experiments/activity',json=body,headers={'Origin':'https://other.invalid'}).status_code,403)
        readonly = create_app(Store(self.root / 'readonly'), readonly=True, orchestration=self.service)
        client = TestClient(readonly)
        self.addCleanup(client.close)
        self.assertEqual(client.post('/api/v1/experiments/activity',json=body).status_code,403)
        with sqlite3.connect(Journal(self.private).path) as db:
            db.execute('DELETE FROM events WHERE sequence=2')
        gap = self.read(run).json()
        self.assertTrue(gap['gap']); self.assertFalse(gap['available'])
        self.assertEqual(gap['phase']['name'], 'unknown')
        self.assertEqual(gap['phase']['event_sequence'], original['high_water'])
        self.assertEqual(gap['events'], [])

    def test_observer_failure_after_reservation_keeps_consumed_budget(self):
        # Controlled observer fault after actual persistent reservation, before rollout.
        journal = Journal(self.private); journal.initialize('run', 'a'*64)
        evaluator = Evaluator(self.private)
        case = evaluator.dispatch('agent','list',{})['cases'][0]
        emit = journal.emit
        def fail(kind, *a, **kw):
            if kind == 'root_probe_reserved':
                journal.lost.touch()
                raise OSError('private fake failure')
            return emit(kind,*a,**kw)
        with patch.object(Journal, 'emit', side_effect=fail):
            with self.assertRaises(OSError):
                evaluator.dispatch('agent','evaluate',dict(case_id=case['id'],candidate_id=case['root_id']))
        state = json.loads((self.private / 'agent/private-state.json').read_text())
        self.assertEqual(len(state['cases'][0]['attempts']),1)
        self.assertEqual(state['cases'][0]['forward_reserved'],2)
        self.assertEqual(state['cases'][0]['attempts'][0]['status'],'reserved')
        self.assertFalse(journal.read('run','a'*64,'running')['available'])
        self.assertTrue(journal.read('run','a'*64,'running')['gap'])

    def test_abrupt_evaluator_crash_retains_reservation_and_terminal_fence(self):
        journal = Journal(self.private); journal.initialize('run', 'a'*64)
        script = """
import os, sys
from godseye.evaluator import Evaluator
from godseye.benchmark import RepairBenchmark
evaluator=Evaluator(sys.argv[1])
case=evaluator.dispatch('agent','list',{})['cases'][0]
RepairBenchmark._evaluate=staticmethod(lambda *a: os._exit(91))
evaluator.dispatch('agent','evaluate',dict(case_id=case['id'],candidate_id=case['root_id']))
"""
        process = subprocess.run([sys.executable, '-c', script, str(self.private)],
                                 capture_output=True, timeout=20)
        self.assertEqual(process.returncode,91,process.stderr.decode())
        state = json.loads((self.private / 'agent/private-state.json').read_text())
        self.assertEqual(state['cases'][0]['forward_reserved'],2)
        live = journal.read('run','a'*64,'running')
        self.assertEqual(live['events'][-1]['kind'],'root_probe_reserved')
        fence = live['high_water']
        self.assertEqual(journal.read('run','a'*64,'interrupted')['phase'],
                         dict(name='unknown',event_sequence=fence))
        journal.emit('worker_failed','worker','worker')
        terminal = journal.read('run','a'*64,'interrupted')
        journal.emit('root_probe_reserved','evaluate','agent')
        self.assertEqual(journal.read('run','a'*64,'interrupted'),terminal)
        with journal.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM active').fetchone()[0],0)
        # Reopening recovers only accounting state; it cannot execute or refund.
        bench = RepairBenchmark(self.private / 'agent')
        recovered = bench.cases()
        self.assertEqual(recovered[0]['probes_used'],1)
        self.assertEqual(recovered[0]['forward_reserved'],2)

    def test_gap_consumes_fence_and_later_contiguous_observation_can_recover(self):
        journal = Journal(self.private); journal.initialize('run','a'*64)
        journal.emit('operation_started','evaluate','agent')
        journal.emit('root_probe_reserved','evaluate','agent')
        with journal.connection() as db:
            db.execute('DELETE FROM events WHERE sequence=1')
        gap = journal.read('run','a'*64,'running')
        self.assertTrue(gap['gap'])
        self.assertEqual(gap['phase'],dict(name='unknown',event_sequence=2))
        self.assertEqual(gap['next_cursor'],2)
        journal.emit('root_probe_reserved','evaluate','agent')
        recovered = journal.read('run','a'*64,'running',2,gap_fence=2)
        self.assertTrue(recovered['available'])
        self.assertEqual(recovered['phase'],dict(name='checking_original',event_sequence=3))
        self.assertEqual([e['sequence'] for e in recovered['events']],[3])

    def test_cancellation_remains_in_history(self):
        self.worker.block = True
        run = self.start()
        self.assertTrue(self.worker.entered.wait(5))
        self.service.cancel(query(run))
        self.worker.release.set()
        self.assertEqual(self.wait(run)['status'],'cancelled')
        body = self.read(run).json()
        self.assertEqual(body['events'][-1]['kind'],'worker_cancelled')
        self.assertEqual(body['phase']['name'],'unknown')
        # Provider prose/errors are never translated into an edit or test claim.
        self.assertFalse(any(e['arm']=='agent' and e['kind']=='edit_started' for e in body['events']))

    def test_queued_cancellation_records_only_observed_acknowledgment(self):
        self.worker.block = True
        first = self.start()
        self.addCleanup(self.worker.release.set)
        self.assertTrue(self.worker.entered.wait(5))
        private = self.root / 'queued-private'
        Evaluator.create(private,instances=1,episodes=2,max_steps=1,probes=2,forward_budget=4)
        self.service.register(private,baseline_id='queued',suite_id='suite',revision='v1')
        request = start_request(self.service.plan(goal_request()),key='second-click')
        second = self.service.start(request)
        self.assertEqual(self.service.cancel(query(second))['status'],'cancelling')
        self.worker.release.set()
        self.wait(first)
        self.assertEqual(self.wait(second)['status'],'cancelled')
        body = self.read(second).json()
        self.assertEqual([e['kind'] for e in body['events']],['worker_cancelled'])
        self.assertEqual(len(self.worker.calls),1)
        self.assertEqual(self.worker.key_reads,1)
        self.assertFalse((private / '.orchestration.claim').exists())

    def test_provider_failure_retained_without_private_prose(self):
        self.worker.mode = 'provider_error'
        run = self.start()
        result = self.wait(run)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['reason'],'provider_error')
        body = self.read(run).json()
        self.assertEqual(body['events'][-1]['kind'],'worker_failed')
        self.assertEqual(body['phase']['name'],'unknown')
        self.assertNotIn(PROVIDER_SECRET,json.dumps(body))
        self.assertNotIn('PRIVATE_UPSTREAM',json.dumps(body))
        self.assertFalse(any(e['arm']=='agent' and e['kind'] in
            ('edit_started','root_probe_reserved','held_out_reserved') for e in body['events']))

    def test_validated_read_patch_freeze_and_failure_are_evidenced(self):
        journal = Journal(self.private); journal.initialize('run','a'*64)
        evaluator = Evaluator(self.private)
        case = evaluator.dispatch('agent','list',{})['cases'][0]
        args = dict(case_id=case['id'],candidate_id=case['root_id'],tensor='b3',start=0,count=2)
        evaluator.dispatch('agent','read',args)
        with self.assertRaises(ValueError):
            evaluator.dispatch('agent','read',dict(args,count=257))
        with self.assertRaises((ValueError,SyntaxError)):
            evaluator.dispatch('agent','patch',dict(case_id=case['id'],parent_id=case['root_id'],patch='b3[0] = 1/0',hypothesis='PRIVATE BAD PATCH'))
        edited = evaluator.dispatch('agent','patch',dict(case_id=case['id'],parent_id=case['root_id'],patch='b3[0] += 0.01',hypothesis='PRIVATE HYPOTHESIS'))
        evaluator.dispatch('agent','evaluate',dict(case_id=case['id'],candidate_id=edited['id']))
        with self.assertRaises(ValueError):
            evaluator.report()  # All-freezes gate remains enforced; no held-out event.
        body = journal.read('run','a'*64,'running',limit=100)
        events = body['events']
        self.assertTrue(any(e['kind']=='edit_started' and e['count']==2 for e in events))
        self.assertTrue(any(e['kind']=='activity_failed' and e['operation']=='read' for e in events))
        self.assertTrue(any(e['kind']=='activity_failed' and e['operation']=='patch' for e in events))
        self.assertTrue(any(e['kind']=='candidate_probe_reserved' for e in events))
        self.assertFalse(any(e['kind']=='held_out_reserved' for e in events))
        self.assertNotIn('PRIVATE HYPOTHESIS',json.dumps(body))
