"""Offline service tests: synthetic providers, temporary keys, real evaluator budgets.

The in-process evaluator here is a test fixture, never the production worker.
No Docker, saved user credentials, network provider, or UI changes are needed.
"""
from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error

from fastapi.testclient import TestClient

from godseye.core import Store, load_weights, save_weights
from godseye.evaluator import Evaluator
from godseye.experiment_spec import ContractError, DEFAULT_CEILINGS, validate_message
from godseye.orchestration import (
    AdmissionLimits, DockerWorker, Orchestrator, Stopped, WorkerFailure,
    audit_selections, read_accounting,
)
from godseye.provider_setup import ProviderSettings
from godseye.server import create_app
from godseye.storage import write_json
from isolation.agent_adapter import Evidence, baseline, run_agent


def query(run):
    return dict(schema_version=1, experiment_id=run['experiment_id'])


class FakeWorker:
    capacity = 4

    def __init__(self):
        self.calls = []
        self.providers = []
        self.recovered = []
        self.mode = 'complete'
        self.block = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.active, self.peak = 0, 0
        self.lock = threading.Lock()
        self.after_freeze = None
        self.cleanup_block = None
        self.cleanup_entered = threading.Event()

    def available(self):
        return True

    def recover(self, row, registration, directory):
        self.recovered.append(row['id'])

    def execute(self, row, registration, directory, settings, check, accounting):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.calls.append(row['id'])
        try:
            self._execute(row, registration, directory, settings, check, accounting)
        finally:
            with self.lock:
                self.active -= 1
            if self.cleanup_block:
                self.cleanup_entered.set()
                self.cleanup_block.wait(3)

    def _execute(self, row, registration, directory, settings, check, accounting):
        credential = settings.credential(row['spec']['provider']['name'])
        if credential != 'sk-temporary-orchestration-only':
            raise AssertionError('Test must use its temporary credential')
        evaluator = Evaluator(registration['directory'])

        class Client:
            def __init__(self, role):
                self.role = role

            def call(self, operation, args):
                check()
                return evaluator.dispatch(self.role, operation, args)

        class Log(Evidence):
            def write(self, value):
                super().write(value)
                accounting()

        for role in ('unchanged', 'heuristic'):
            with (directory / 'evidence' / (role + '.jsonl')).open('x') as stream:
                class BaselineLog:
                    def write(self, value):
                        stream.write(json.dumps(value) + '\n')
                baseline(Client(role), role, BaselineLog())
        cases = evaluator.dispatch('agent', 'list', {})['cases']
        pending = []
        for case in cases:
            args = dict(case_id=case['id'], candidate_id=case['root_id'])
            pending.extend([('evaluate', args), ('freeze', args)])

        def provider(body):
            check()
            self.providers.append(body)
            self.entered.set()
            if self.block:
                # Deliberately uninterruptible remote request; cancelled != stopped
                # until this returns and the worker acknowledges quiescence.
                self.release.wait(5)
            if self.mode == '429':
                raise urllib.error.HTTPError('https://private/key', 429, credential, {}, None)
            if self.mode == 'disconnect':
                raise ConnectionError('secret-path/' + credential)
            if self.mode == 'slow':
                time.sleep(1.05)
            if self.mode == 'missing':
                return dict(output=[])
            if self.mode == 'spin':
                return dict(usage=dict(input_tokens=2, output_tokens=3), output=[dict(
                    type='function_call', call_id='spin', name='list', arguments='{}')])
            if pending:
                operation, args = pending.pop(0)
                return dict(usage=dict(input_tokens=2, output_tokens=3), output=[dict(
                    type='function_call', call_id=str(len(pending)), name=operation,
                    arguments=json.dumps(args))])
            return dict(usage=dict(input_tokens=2, output_tokens=3), output=[])

        log = Log(directory / 'evidence' / 'agent.jsonl')
        try:
            check()
            ok = run_agent(Client('agent'), provider, log, model=row['spec']['provider']['model'],
                           **row['spec']['limits'])
        except RuntimeError:
            check()
            raise WorkerFailure('provider_error') from None
        finally:
            log.stream.close()
        check()
        if not ok:
            _, reason, _ = read_accounting(log.path)
            raise WorkerFailure('budget_exhausted' if reason.endswith('_limit') else 'provider_error')
        if self.after_freeze:
            self.after_freeze(evaluator)
        check()
        # This is the real evaluator's global freeze gate and persistent final budget.
        write_json(directory / 'held-out.json', evaluator.report())
        check()


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.worker = FakeWorker()
        self.settings = ProviderSettings(self.path / 'keys')
        self.settings.save('sk-temporary-orchestration-only', 'fake-model')
        self.secret_reads = patch.object(self.settings, 'credential', wraps=self.settings.credential)
        self.read_key = self.secret_reads.start()
        self.addCleanup(self.secret_reads.stop)
        self.service = Orchestrator(self.path / 'service', worker=self.worker, settings=self.settings)
        self.addCleanup(lambda: self.service.close())
        self.addCleanup(self.worker.release.set)
        self.counter = 0
        self.register()

    def register(self):
        self.counter += 1
        directory = self.path / ('private-' + str(self.counter))
        Evaluator.create(directory, instances=1, episodes=2, max_steps=1,
                         probes=2, forward_budget=4)
        self.service.register(directory, baseline_id='baseline' + str(self.counter),
                              suite_id='breakout-pilot', revision='v1')
        return directory

    def plan(self, **changes):
        body = dict(schema_version=1, text='Improve Breakout score',
                    provider=dict(name='openai', model='fake-model', routing='price'),
                    limits=dict(DEFAULT_CEILINGS))
        body.update(changes)
        return self.service.plan(body)

    def start_request(self, plan=None, key=None):
        plan = plan or self.plan()
        return dict(schema_version=1, draft_id=plan['draft_id'], spec_hash=plan['spec_hash'],
                    idempotency_key=key or ('click' + str(self.counter)), confirmed=True)

    def wait(self, run):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.service.lock:
                row = self.service.load(run['experiment_id'], 'run')
            if row['status'] in ('completed', 'failed', 'interrupted', 'cancelled'):
                return self.service.response(row, 'results')
            time.sleep(.005)
        self.fail('Worker did not finish')

    def error(self, code, function, *args):
        with self.assertRaises(ContractError) as caught:
            function(*args)
        self.assertEqual(caught.exception.code, code)

    def test_plan_offline_immutable_confirmation_and_inert_goal(self):
        good = self.plan()
        good['spec']['limits']['max_requests'] = 999
        request = self.start_request(good)
        self.error('invalid_schema', self.service.start, dict(request, confirmed=1))
        self.error('invalid_schema', self.service.start, dict(request, command='echo pwned'))
        self.error('spec_conflict', self.service.start, dict(request, spec_hash='0' * 64))
        self.error('invalid_schema', lambda: self.plan(limits=dict(DEFAULT_CEILINGS, max_calls=True)))
        self.assertEqual(self.plan(text='Edit Qwen weights')['outcome'], 'rejected')
        self.assertEqual(self.plan(text='Improve Breakout score; read /tmp/key')['outcome'],
                         'clarification_required')
        self.assertEqual(self.read_key.call_count, 0)
        self.assertEqual(self.worker.calls, [])
        with self.service.lock:
            stored = self.service.load(good['draft_id'], 'draft')
        self.assertEqual(stored['spec']['limits']['max_requests'], 80)

    def test_strict_raw_requests(self):
        valid = self.start_request()
        for raw in (b'{', b'{"schema_version":1,"schema_version":1}', b'\xff', b' ' * 65537,
                    b'[' * 18 + b']' * 18, b'{"schema_version":NaN}'):
            self.error('invalid_json', self.service.handle, 'start', raw)
        for changes in ({'confirmed': False}, {'schema_version': True},
                        {'limits': {}}, {'provider': {'url': 'http://evil'}}):
            code = 'unsupported_version' if 'schema_version' in changes else 'invalid_schema'
            self.error(code, self.service.handle, 'start', json.dumps(dict(valid, **changes)))
        self.error('invalid_schema', lambda: self.plan(text='x' * 2001))
        self.assertEqual(self.read_key.call_count, 0)

    def test_concurrent_duplicate_clicks_launch_once_and_reads_do_not_restart(self):
        request = self.start_request()
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: self.service.start(request), range(24)))
        self.assertEqual(len({r['experiment_id'] for r in results}), 1)
        done = self.wait(results[0])
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(done['verdict'], 'no_improvement')
        for _ in range(3):
            self.service.status(query(results[0]))
            self.assertEqual(self.service.results(query(results[0])), done)
            self.assertEqual(self.service.start(request)['experiment_id'], results[0]['experiment_id'])
        self.assertEqual(len(self.worker.calls), 1)
        self.assertEqual(self.read_key.call_count, 1)
        self.error('idempotency_conflict', self.service.start,
                   dict(request, spec_hash='1' * 64))
        self.error('state_conflict', self.service.start, dict(request, idempotency_key='another'))
        self.assertEqual(done['phase'], dict(name='unknown', event_sequence=None))
        self.assertTrue(done['usage']['usage_complete'])
        private = json.dumps(done)
        for forbidden in ('sk-temporary', str(self.path), 'held_seed', 'generation_seed', 'family'):
            self.assertNotIn(forbidden, private)
        with self.service.lock:
            saved = self.service.load(results[0]['experiment_id'], 'run')
        self.assertEqual(saved['spec']['limits'], dict(DEFAULT_CEILINGS))
        for field in ('candidate_manifest_id', 'delta_artifact_id', 'report_id'):
            self.assertTrue(Path(saved['artifacts'][done['evidence'][field]]).exists())

    def test_changed_root_and_evaluation_policy_rejected_before_key(self):
        request = self.start_request()
        private = self.path / 'private-1'
        state = json.loads((private / 'agent' / 'private-state.json').read_text())
        root = private / 'agent' / (state['cases'][0]['root_id'] + '.npz')
        weights = load_weights(root)
        weights['b3'][0] += 1
        save_weights(root, weights)
        self.error('spec_conflict', self.service.start, request)
        self.assertEqual(self.read_key.call_count, 0)
        self.register()
        request = self.start_request(key='new')
        config = self.path / 'private-2' / 'experiment.json'
        value = json.loads(config.read_text())
        value['settings']['max_steps'] = 10
        write_json(config, value)
        self.error('spec_conflict', self.service.start, request)
        self.assertEqual(self.read_key.call_count, 0)

    def test_private_suite_changes_and_duplicate_registration_are_rejected(self):
        self.error('state_conflict', lambda: self.service.register(self.path / 'private-1',
                   baseline_id='copied', suite_id='breakout-pilot', revision='v1'))
        request = self.start_request()
        path = self.path / 'private-1' / 'agent' / 'private-state.json'
        state = json.loads(path.read_text())
        state['cases'][0]['held_seed'] += 1
        write_json(path, state)
        self.error('spec_conflict', self.service.start, request)
        self.assertEqual(self.read_key.call_count, 0)

    def test_planning_start_and_read_limits_are_independent(self):
        self.service.limits = AdmissionLimits(plans_per_minute=4, starts_per_minute=1,
                                              reads_per_minute=1)
        self.worker.block = True
        request = self.start_request()
        run = self.service.start(request)
        self.assertTrue(self.worker.entered.wait(2))
        self.error('result_not_ready', self.service.results, query(run))
        self.error('rate_limited', self.service.status, query(run))
        self.register()
        new_request = self.start_request(key='throttled-start')
        self.error('rate_limited', self.service.start, new_request)
        self.assertEqual(self.service.start(request)['experiment_id'], run['experiment_id'])
        # Cancellation remains available despite start/read throttles.
        self.assertEqual(self.service.cancel(query(run))['status'], 'cancelling')
        self.worker.release.set()
        self.assertEqual(self.wait(run)['status'], 'cancelled')
        self.assertEqual(self.read_key.call_count, 1)

    def test_expired_plan_requires_review(self):
        request = self.start_request()
        with patch.object(self.service, 'clock', return_value=time.time() + 901):
            self.error('spec_conflict', self.service.start, request)
        self.assertEqual(self.read_key.call_count, 0)

    def test_queue_exhaustion_replay_and_single_use_registry(self):
        self.service.limits = AdmissionLimits(queue=1)
        self.worker.block = True
        first_request = self.start_request()
        first = self.service.start(first_request)
        self.assertTrue(self.worker.entered.wait(2))
        self.register()
        second = self.service.start(self.start_request(key='second'))
        self.register()
        third_request = self.start_request(key='third')
        self.error('queue_full', self.service.start, third_request)
        self.assertEqual(len(self.service.rows('run')), 2)
        self.assertEqual(self.read_key.call_count, 1)
        self.assertEqual(self.service.start(first_request)['experiment_id'], first['experiment_id'])
        self.service.cancel(query(second))
        self.worker.release.set()
        self.assertEqual(self.wait(second)['status'], 'cancelled')
        self.assertEqual(self.wait(first)['status'], 'completed')
        # Queued cancellation never read a key or claimed the suite.
        self.assertEqual(self.read_key.call_count, 1)
        other = self.plan()
        # A second draft targeting a consumed baseline cannot get a fresh run.
        with self.service.transaction():
            self.service.save('current_registry', 'config', dict(baseline_id='baseline1'))
        self.error('state_conflict', self.service.start, self.start_request(self.plan(), key='reuse'))
        self.assertEqual(len(self.worker.calls), 1)
        self.assertEqual(other['outcome'], 'ready')

    def test_bounded_parallel_workers(self):
        self.service.close()
        self.service = Orchestrator(self.path / 'service', worker=self.worker, settings=self.settings,
                                    limits=AdmissionLimits(workers=2, queue=1))
        self.worker.block = True
        runs = []
        for index in range(3):
            self.register()
            runs.append(self.service.start(self.start_request(key='parallel' + str(index))))
        deadline = time.monotonic() + 2
        while self.worker.active < 2 and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertEqual(self.worker.active, 2)
        self.register()
        self.error('queue_full', self.service.start, self.start_request(key='overflow'))
        self.worker.release.set()
        for run in runs:
            self.assertEqual(self.wait(run)['status'], 'completed')
        self.assertEqual(self.worker.peak, 2)

    def test_cancellation_waits_for_ack_preserves_unknown_usage(self):
        self.worker.block = True
        run = self.service.start(self.start_request())
        self.assertTrue(self.worker.entered.wait(2))
        cancelling = self.service.cancel(query(run))
        self.assertEqual(cancelling['status'], 'cancelling')
        self.assertTrue(cancelling['usage']['request_in_flight'])
        self.assertFalse(cancelling['usage']['usage_complete'])
        self.error('result_not_ready', self.service.results, query(run))
        self.assertEqual(self.service.cancel(query(run))['status'], 'cancelling')
        self.worker.release.set()
        done = self.wait(run)
        self.assertEqual(done['status'], 'cancelled')
        self.assertEqual(done['reason'], 'user_cancelled')
        self.assertIsNone(done['evidence'])
        self.assertEqual(len(self.worker.providers), 1)
        # The response can finish after cancellation; no tools or new inference admitted.
        self.assertEqual(done['usage']['requests'], 1)
        self.assertEqual(self.service.cancel(query(run))['status'], 'cancelled')

    def test_missing_usage_429_disconnect_fail_once_without_leaks(self):
        for index, mode in enumerate(('missing', '429', 'disconnect')):
            if index:
                self.register()
            self.worker.mode = mode
            run = self.service.start(self.start_request(key=mode))
            done = self.wait(run)
            self.assertEqual(done['status'], 'failed')
            # Adapter redacts transport metadata, so 429 cannot safely be distinguished.
            self.assertEqual(done['reason'], 'provider_error')
            self.assertFalse(done['usage']['usage_complete'])
            self.assertEqual(done['usage']['requests'], 1)
            self.assertEqual(done['usage']['request_in_flight'], mode != 'missing')
            self.assertNotIn('sk-temporary', json.dumps(done))
            state = json.loads((self.path / ('private-' + str(self.counter)) /
                                'agent' / 'private-state.json').read_text())
            self.assertFalse(any(c['attempts'] or c['finalized'] for c in state['cases']))
        self.assertEqual(len(self.worker.providers), 3)

    def test_provider_limits_are_adapter_limits(self):
        self.worker.mode = 'spin'
        for index, override in enumerate((dict(max_requests=1), dict(max_input_tokens=2),
                                          dict(max_total_output_tokens=3), dict(max_calls=1),
                                          dict(max_rounds=1))):
            if index:
                self.register()
            limits = dict(DEFAULT_CEILINGS, **override)
            run = self.service.start(self.start_request(self.plan(limits=limits), key='budget' + str(index)))
            done = self.wait(run)
            self.assertEqual(done['reason'], 'budget_exhausted')
            self.assertEqual(done['status'], 'failed')
            self.assertEqual(done['usage']['requests'], 1)

    def test_evaluator_reservations_and_missing_report_cannot_complete(self):
        def break_final(evaluator):
            # A non-completed measurement must never be summarized as zero.
            original = evaluator.report
            def broken_report():
                report = original()
                path = evaluator.directory / 'agent' / 'private-state.json'
                state = json.loads(path.read_text())
                state['cases'][0]['final']['status'] = 'failed'
                write_json(path, state)
                return report
            evaluator.report = broken_report
        self.worker.after_freeze = break_final
        run = self.service.start(self.start_request())
        done = self.wait(run)
        self.assertEqual(done['status'], 'failed')
        self.assertEqual(done['reason'], 'evaluation_error')
        self.assertEqual(done['verdict'], 'not_evaluated')
        self.assertIsNone(done['evidence'])
        state = json.loads((self.path / 'private-1' / 'agent' / 'private-state.json').read_text())
        self.assertEqual(state['cases'][0]['forward_reserved'], 2)
        self.assertEqual(state['cases'][0]['final']['forward_reserved'], 6)

    def test_changed_selection_requires_earlier_root_and_no_tie(self):
        for attempts in ([], [dict(candidate_id='edit', status='completed', result=dict(mean_score=2)),
                              dict(candidate_id='root', status='completed', result=dict(mean_score=1))],
                         [dict(candidate_id='root', status='completed', result=dict(mean_score=1)),
                          dict(candidate_id='edit', status='completed', result=dict(mean_score=1))]):
            state = dict(cases=[dict(root_id='root', finalized=True,
                                    final=dict(candidate_id='edit'), candidates=[dict(id='edit')],
                                    attempts=attempts)])
            with self.assertRaises(WorkerFailure) as caught:
                audit_selections({'agent': state})
            self.assertEqual(caught.exception.reason, 'evaluation_error')

    def test_restart_marks_admitted_work_interrupted_never_resumes(self):
        request = self.start_request()
        with patch.object(self.service.pool, 'submit'):
            run = self.service.start(request)
        path = self.service.evidence_path(run['experiment_id'])
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(dict(event='request', cumulative=dict(
            requests=1, input_tokens=0, output_tokens=0, calls=0, elapsed_seconds=1,
            usage_complete=True, request_in_flight=True))) + '\n')
        self.service.close()
        self.service = Orchestrator(self.path / 'service', worker=self.worker, settings=self.settings)
        self.assertEqual(self.worker.recovered, [run['experiment_id']])
        done = self.service.results(query(run))
        self.assertEqual(done['status'], 'interrupted')
        self.assertEqual(done['reason'], 'process_lost')
        self.assertFalse(done['usage']['usage_complete'])
        self.assertTrue(done['usage']['request_in_flight'])
        self.assertEqual(self.service.start(request)['experiment_id'], run['experiment_id'])
        self.assertEqual(self.worker.calls, [])
        self.assertEqual(self.read_key.call_count, 0)
        self.error('state_conflict', self.service.start, self.start_request(key='new-run'))

    def test_second_service_owner_is_refused(self):
        self.error('unavailable', Orchestrator, self.path / 'service')

    def test_no_worker_means_no_admission_or_key(self):
        self.service.worker = None
        self.error('worker_unavailable', self.service.start, self.start_request())
        self.assertEqual(self.service.rows('run'), [])
        self.assertEqual(self.read_key.call_count, 0)

    def test_http_contract_boundary_throttles_and_disconnect_reconciliation(self):
        self.service.limits = AdmissionLimits(plans_per_minute=1)
        app = create_app(Store(self.path / 'store'), token='local-token', orchestration=self.service)
        with TestClient(app) as client:
            headers = {'Authorization': 'Bearer local-token'}
            plan_body = dict(schema_version=1, text='Improve Breakout score',
                             provider=dict(name='openai', model='fake-model', routing='price'),
                             limits=dict(DEFAULT_CEILINGS))
            base = '/api/v1/experiments/'
            for extra in ({'Host': 'evil.example'}, {'Origin': 'http://evil.example'},
                          {'Sec-Fetch-Site': 'cross-site'}):
                response = client.post(base + 'plan', json=plan_body, headers=dict(headers, **extra))
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()['error']['code'], 'not_authorized')
            self.assertEqual(client.post(base + 'plan', json=plan_body).status_code, 403)
            for content in ('x' * 65537, '{"a":1,"a":2}', '{'):
                response = client.post(base + 'plan', content=content,
                                       headers=dict(headers, **{'Content-Type': 'application/json'}))
                self.assertEqual(response.status_code, 400)
                validate_message('error_response', response.json())
            response = client.post(base + 'plan', json=plan_body, headers=headers)
            self.assertEqual(response.status_code, 200)
            request = self.start_request(response.json())
            limited = client.post(base + 'plan', json=plan_body, headers=headers)
            self.assertEqual(limited.status_code, 429)
            self.assertEqual(limited.headers['Retry-After'], '5')
            self.assertEqual(limited.json(), ContractError('rate_limited').response())
            self.worker.block = True
            start = client.post(base + 'start', json=request, headers=headers).json()
            self.assertTrue(self.worker.entered.wait(2))
            pending = client.post(base + 'results', json=query(start), headers=headers)
            self.assertEqual(pending.status_code, 409)
            self.assertEqual(pending.json()['retry']['action'], 'poll_status')
            self.assertNotIn('Retry-After', pending.headers)
            self.worker.release.set()
            self.wait(start)
            # A new browser session reads/replays the durable identity, no new work.
            with TestClient(app) as reloaded:
                same = reloaded.post(base + 'start', json=request, headers=headers)
                self.assertEqual(same.json()['experiment_id'], start['experiment_id'])
                status = reloaded.post(base + 'status', json=query(start), headers=headers)
                self.assertEqual(status.json()['status'], 'completed')
                self.assertEqual(status.headers['cache-control'], 'no-store')
            self.assertEqual(len(self.worker.calls), 1)

    def test_cancellation_wins_before_terminal_publication(self):
        cleanup = threading.Event()
        self.addCleanup(cleanup.set)
        self.worker.cleanup_block = cleanup
        run = self.service.start(self.start_request())
        self.assertTrue(self.worker.cleanup_entered.wait(2))
        self.assertEqual(self.service.cancel(query(run))['status'], 'cancelling')
        cleanup.set()
        done = self.wait(run)
        self.assertEqual(done['status'], 'cancelled')
        self.assertEqual(done['verdict'], 'not_evaluated')
        self.assertIsNone(done['evidence'])

    def test_worker_rechecks_registry_after_waiting_in_queue(self):
        self.worker.block = True
        first = self.service.start(self.start_request())
        self.assertTrue(self.worker.entered.wait(2))
        directory = self.register()
        second = self.service.start(self.start_request(key='queued-change'))
        state_path = directory / 'agent' / 'private-state.json'
        state = json.loads(state_path.read_text())
        state['episodes'] = 8
        write_json(state_path, state)
        self.worker.release.set()
        self.wait(first)
        failed = self.wait(second)
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['reason'], 'evaluation_error')
        self.assertEqual(self.read_key.call_count, 1)

    def test_elapsed_deadline_and_output_parameter(self):
        self.worker.mode = 'slow'
        limits = dict(DEFAULT_CEILINGS, max_seconds=1, max_output_tokens=17)
        run = self.service.start(self.start_request(self.plan(limits=limits)))
        done = self.wait(run)
        self.assertEqual(done['reason'], 'budget_exhausted')
        self.assertEqual(done['usage']['requests'], 1)
        self.assertEqual(done['usage']['tool_calls'], 0)
        self.assertEqual(self.worker.providers[0]['max_output_tokens'], 17)

    def test_failed_recovery_fences_new_admission_without_reading_keys(self):
        with patch.object(self.service.pool, 'submit'):
            run = self.service.start(self.start_request())
        self.service.close()
        with patch.object(self.worker, 'recover', side_effect=WorkerFailure('process_lost')):
            self.service = Orchestrator(self.path / 'service', worker=self.worker,
                                        settings=self.settings)
        self.assertEqual(self.service.status(query(run))['status'], 'interrupted')
        self.register()
        self.error('worker_unavailable', self.service.start, self.start_request(key='blocked'))
        self.assertEqual(self.read_key.call_count, 0)
        self.service.close()
        self.service = Orchestrator(self.path / 'service', worker=self.worker, settings=self.settings)
        # A later startup can establish quiescence; it never runs the old adapter.
        self.assertFalse(self.service.recovery_blocked)
        self.assertEqual(self.worker.calls, [])

    def test_asgi_disconnect_before_body_and_after_committed_start(self):
        app = create_app(Store(self.path / 'disconnect-store'), orchestration=self.service)
        self.addCleanup(app.state.jobs.close)
        request = self.start_request()
        body = json.dumps(request).encode()
        scope = dict(type='http', asgi=dict(version='3.0'), http_version='1.1',
                     method='POST', scheme='http', path='/api/v1/experiments/start',
                     raw_path=b'/api/v1/experiments/start', query_string=b'', root_path='',
                     headers=[(b'host', b'testserver'), (b'content-type', b'application/json')],
                     client=('127.0.0.1', 1234), server=('testserver', 80))
        async def disconnected_body():
            messages = iter([dict(type='http.request', body=body[:8], more_body=True),
                             dict(type='http.disconnect')])
            async def receive():
                return next(messages)
            async def send(message):
                self.fail('Incomplete body should not send or admit anything')
            await app(scope, receive, send)
        asyncio.run(disconnected_body())
        self.assertEqual(self.service.rows('run'), [])
        async def lost_response():
            async def receive():
                return dict(type='http.request', body=body, more_body=False)
            async def send(message):
                raise ConnectionError('Browser lost response')
            await app(scope, receive, send)
        with self.assertRaises(ConnectionError):
            asyncio.run(lost_response())
        runs = self.service.rows('run')
        self.assertEqual(len(runs), 1)
        replay = self.service.start(request)
        self.assertEqual(replay['experiment_id'], runs[0]['id'])
        self.assertEqual(self.wait(replay)['status'], 'completed')
        self.assertEqual(len(self.worker.calls), 1)

    def test_unknown_worker_stop_fences_live_admission(self):
        with patch.object(self.worker, 'execute', side_effect=WorkerFailure('process_lost')):
            run = self.service.start(self.start_request())
            done = self.wait(run)
        self.assertEqual(done['status'], 'interrupted')
        self.register()
        self.error('worker_unavailable', self.service.start, self.start_request(key='no-overlap'))
        self.assertEqual(self.read_key.call_count, 0)

    def test_docker_worker_full_lifecycle_with_fake_daemon_and_provider(self):
        from isolation.agent_adapter import Client
        worker = DockerWorker(Path(__file__).resolve().parents[1])
        self.service.worker = worker
        evaluator = Evaluator(self.path / 'private-1')
        def rpc(client, operation, args):
            role = evaluator.authenticate(client.token)
            return evaluator.dispatch(role, operation, args)
        def launch(arguments, **options):
            env = options['env']
            client = Client('http://127.0.0.1:8790', (self.path / 'private-1' /
                                                     'agent.token').read_text())
            for case in client.call('list', {})['cases']:
                args = dict(case_id=case['id'], candidate_id=case['root_id'])
                client.call('evaluate', args)
                client.call('freeze', args)
            def provider(body):
                self.assertEqual(body['model'], 'fake-model')
                self.assertEqual({t['name'] for t in body['tools']},
                                 {'list', 'read', 'patch', 'evaluate', 'freeze'})
                self.assertNotIn('sk-temporary', json.dumps(body))
                return dict(output=[], usage=dict(input_tokens=2, output_tokens=3))
            evidence = Evidence(Path(env['REPAIR_EVIDENCE_DIR']) / 'agent.jsonl')
            try:
                self.assertTrue(run_agent(client, provider, evidence,
                                          model=env['REPAIR_AGENT_MODEL'],
                                          **{k: int(env['REPAIR_AGENT_' + k.upper()])
                                             for k in DEFAULT_CEILINGS}))
            finally:
                evidence.stream.close()
            process = Mock(returncode=0)
            process.poll.return_value = 0
            return process
        with patch.object(worker, 'available', return_value=True), \
                patch('godseye.orchestration.subprocess.run') as command, \
                patch('godseye.orchestration.subprocess.Popen', side_effect=launch), \
                patch('isolation.agent_adapter.Client.call', new=rpc), \
                patch('isolation.agent_adapter.post', side_effect=lambda *a: evaluator.report()):
            command.return_value.returncode = 0
            command.return_value.stdout = b''
            run = self.service.start(self.start_request())
            done = self.wait(run)
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(done['usage']['requests'], 1)
        self.assertTrue(done['usage']['usage_complete'])
        self.assertFalse((self.service.directory / run['experiment_id'] / 'provider.key').exists())
        self.assertTrue((self.service.evidence_path(run['experiment_id']).parent /
                         '.agent-run.claim').exists())

    def test_docker_worker_maps_only_confirmed_settings_and_pins_images(self):
        worker = DockerWorker(Path(__file__).resolve().parents[1])
        plan = self.plan(limits=dict(DEFAULT_CEILINGS, max_output_tokens=17))
        row = dict(id='f' * 32, spec=plan['spec'])
        directory = self.path / 'mock-docker-run'
        (directory / 'evidence').mkdir(parents=True)
        registration = self.service.registration('baseline1')
        process = Mock(returncode=1)
        process.poll.return_value = 1
        with patch('godseye.orchestration.subprocess.run') as command, \
                patch('godseye.orchestration.subprocess.Popen', return_value=process) as launch, \
                patch('isolation.agent_adapter.Client.call', return_value=dict(cases=[])), \
                patch('isolation.agent_adapter.baseline'):
            command.return_value.returncode = 0
            command.return_value.stdout = b''
            with self.assertRaises(WorkerFailure) as caught:
                worker.execute(row, registration, directory, self.settings, lambda: None,
                               lambda: None)
            self.assertEqual(caught.exception.reason, 'agent_incomplete')
        arguments = launch.call_args.args[0]
        self.assertIn(str(worker.compose), arguments)
        self.assertIn(str(directory / 'compose-images.json'), arguments)
        self.assertIn('--no-deps', arguments)
        self.assertIn('never', arguments)
        env = launch.call_args.kwargs['env']
        for key, value in plan['spec']['limits'].items():
            self.assertEqual(env['REPAIR_AGENT_' + key.upper()], str(value))
        self.assertEqual(env['REPAIR_AGENT_MODEL'], 'fake-model')
        self.assertEqual(env['REPAIR_AGENT_PROVIDER'], 'openai')
        self.assertEqual(env['REPAIR_AGENT_ROUTING'], 'price')
        self.assertNotIn('sk-temporary', json.dumps(env))
        self.assertNotIn('sk-temporary', json.dumps(arguments))
        self.assertFalse((directory / 'provider.key').exists())
        overrides = json.loads((directory / 'compose-images.json').read_text())
        self.assertEqual(overrides, dict(services={name: dict(image='isolation-' + name)
                         for name in ('evaluator', 'agent', 'gateway')}))

    def test_docker_worker_fixed_isolation_and_mapping(self):
        worker = DockerWorker(Path(__file__).resolve().parents[1])
        self.assertEqual(worker.capacity, 1)
        with patch('godseye.orchestration.subprocess.run') as execute:
            execute.return_value.returncode = 0
            self.assertTrue(worker.available())
            self.assertEqual(execute.call_args_list[0].args[0],
                             ['docker', 'version', '--format', '{{.Server.Version}}'])
            self.assertEqual(execute.call_args.args[0], ['docker', 'image', 'inspect',
                             'isolation-evaluator', 'isolation-agent', 'isolation-gateway'])
        with self.assertRaises(ValueError):
            Orchestrator(self.path / 'bad-workers', worker=worker, limits=AdmissionLimits(workers=2))


if __name__ == '__main__':
    unittest.main()
