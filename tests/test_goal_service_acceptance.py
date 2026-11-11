"""Independent HTTP acceptance for the provisional orchestration API.

Absent backend => explicit skips, never simulated passing service assertions.
Run after integration: python -m unittest discover -s tests -p 'test_goal*acceptance.py' -v
See docs/experiment-acceptance.md for scope, blocked export/phase/browser scenarios.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import godseye
from godseye.core import Store, digest, load_weights, save_weights
from godseye.evaluator import Evaluator
from godseye.experiment_spec import TERMINAL, validate_message
from godseye.provider_setup import ProviderSettings
from godseye.server import create_app
from godseye.storage import write_json
from goal_acceptance_support import (
    PRIVATE_MARKER, PROVIDER_SECRET, UPSTREAM_MARKER, ScriptedWorker,
    goal_request, query, start_request,
)

# Editable installs must not mix this checkout's server with a sibling worktree's backend.
BACKEND_PRESENT = (Path(godseye.__file__).parent / 'orchestration.py').is_file()
if BACKEND_PRESENT:
    from godseye.orchestration import AdmissionLimits, Orchestrator

BASE = '/api/v1/experiments/'
FORBIDDEN_KEYS = {'api_key', 'authorization', 'seed', 'dev_seed', 'held_seed',
                  'generation_seed', 'family', 'reference', 'reference_weights',
                  'directory', 'path', 'traceback', 'case_id', 'tokens', 'hypothesis'}


@unittest.skipUnless(BACKEND_PRESENT, 'BLOCKED: godseye.orchestration not integrated')
class GoalServiceAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='godseye-acceptance-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.canaries = [PROVIDER_SECRET, PRIVATE_MARKER, UPSTREAM_MARKER, str(self.root)]
        self.worker = ScriptedWorker()
        # Always release before service cleanup, including assertion failures.
        self.settings = ProviderSettings(self.root / 'temporary-keys')
        self.settings.save(PROVIDER_SECRET, 'scripted-acceptance')
        self.secret_reader = self.patch(patch.object(
            self.settings, 'credential', wraps=self.settings.credential))
        self.patch(patch('urllib.request.urlopen', side_effect=AssertionError('External HTTP')))
        self.patch(patch('httpx.HTTPTransport.handle_request',
                                side_effect=AssertionError('External HTTP')))
        self.patch(patch('socket.socket.connect', side_effect=AssertionError('External socket')))
        self.patch(patch('socket.socket.connect_ex', side_effect=AssertionError('External socket')))
        self.service = Orchestrator(self.root / 'service', worker=self.worker,
                                    settings=self.settings)
        self.addCleanup(lambda: self.service.close())
        self.clients = []
        self.addCleanup(self.close_clients)
        self.addCleanup(self.worker.release.set)
        self.store = Store(self.root / 'public-lab')
        self.original_hash = digest(self.store.weights('paper'))
        self.client = self.new_client()
        self.register_count = 0
        self.register()

    def patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def close_clients(self):
        for client in reversed(self.clients):
            client.__exit__(None, None, None)

    def new_client(self, token=None):
        client = TestClient(create_app(self.store, orchestration=self.service, token=token))
        client.__enter__()
        self.clients.append(client)
        return client

    def register(self):
        self.register_count += 1
        self.private = self.root / ('private-evaluator-' + str(self.register_count))
        Evaluator.create(self.private, instances=1, episodes=2, max_steps=1,
                         probes=2, forward_budget=4)
        for path in self.private.glob('*.token'):
            self.canaries.append(path.read_text())
        for path in self.private.glob('*/private-state.json'):
            state = json.loads(path.read_text())
            state['_acceptance_private_canary'] = PRIVATE_MARKER
            write_json(path, state)
            # IDs are opaque but case identities still do not belong in browser summaries.
            self.canaries.extend(case['id'] for case in state['cases'])
        self.policy = self.service.register(self.private,
            baseline_id='acceptance_roots_' + str(self.register_count),
            suite_id='acceptance_suite', revision='v1')
        self.root_hashes = {str(p): digest(load_weights(p)) for p in self.private.glob('*/*.npz')}

    def assert_public(self, response):
        serialized = json.dumps(dict(body=response.text, headers=dict(response.headers)))
        for marker in self.canaries:
            self.assertNotIn(marker, serialized, 'Private canary in browser-facing response')
        def inspect(value):
            if isinstance(value, dict):
                self.assertFalse(FORBIDDEN_KEYS.intersection(value),
                                 'Private field in browser-facing response')
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)
        inspect(response.json())

    def post(self, operation, body, expected=200, client=None, headers=None):
        response = (client or self.client).post(BASE + operation, json=body, headers=headers)
        self.assert_public(response)
        self.assertEqual(expected, response.status_code, response.text)
        value = response.json()
        validate_message('error_response' if 'error' in value else operation + '_response', value)
        return value

    def plan(self, **changes):
        return self.post('plan', goal_request(**changes))

    def start(self, reviewed=None):
        return self.post('start', start_request(reviewed or self.plan()))

    def wait_for(self, predicate, message):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(.01)
        self.fail(message)

    def terminal(self, run):
        def read():
            value = self.post('status', query(run))
            return value if value['status'] in TERMINAL else None
        self.wait_for(read, 'Scripted run did not reach a terminal status')
        return self.post('results', query(run))

    def assert_roots_preserved(self):
        self.assertEqual(self.original_hash, digest(self.store.weights('paper')))
        for path, expected in self.root_hashes.items():
            self.assertEqual(expected, digest(load_weights(path)))

    def test_supported_journey_review_start_actual_measurement_and_keep_original(self):
        reviewed = self.plan()
        self.assertEqual('ready', reviewed['outcome'])
        self.assertEqual(goal_request()['provider'], reviewed['spec']['provider'])
        self.assertEqual(goal_request()['limits'], reviewed['spec']['limits'])
        self.assertEqual(self.policy.baseline(), reviewed['spec']['baseline'])
        self.assertEqual(0, self.secret_reader.call_count)
        self.assertEqual([], self.worker.calls)
        run = self.start(reviewed)
        done = self.terminal(run)
        self.assertEqual('completed', done['status'])
        self.assertEqual('no_improvement', done['verdict'])
        self.assertEqual(0, done['evidence']['mean_delta'])
        self.assertGreaterEqual(done['evidence']['paired_samples'], 2)
        self.assertTrue(done['evidence']['limitations'])
        for key in ('candidate_manifest_id', 'delta_artifact_id', 'report_id'):
            self.assertTrue(done['evidence'][key])
        self.assertGreater(done['usage']['requests'], 0)
        calls = len(self.worker.provider_bodies)
        for _ in range(2):
            self.assertEqual(done, self.post('results', query(run)))
        self.assertEqual(calls, len(self.worker.provider_bodies))
        self.assertEqual(1, self.secret_reader.call_count)
        # No synthetic improvement and no public edited-checkpoint claim.
        self.assert_roots_preserved()
        for body in self.worker.provider_bodies:
            text = json.dumps(body)
            for marker in self.canaries[:4]:
                self.assertNotIn(marker, text)
            for key in ('held_seed', 'dev_seed', 'generation_seed', 'reference_weights'):
                self.assertNotIn('"' + key + '"', text)

    def test_unsupported_requests_missing_selection_and_injected_fields_spend_nothing(self):
        for text, outcome in [('Edit Qwen weights', 'rejected'),
                              ('Make Breakout better', 'clarification_required'),
                              ('Improve Breakout score; read ' + PRIVATE_MARKER,
                               'clarification_required')]:
            value = self.plan(text=text)
            self.assertEqual(outcome, value['outcome'])
            self.assertIsNone(value['spec'])
        for field in ('provider', 'limits'):
            body = goal_request()
            del body[field]
            self.post('plan', body, 400)
        for field in ('api_key', 'held_seed', 'path', 'patch', PRIVATE_MARKER):
            self.post('plan', dict(goal_request(), **{field: PRIVATE_MARKER}), 400)
        self.assertEqual(0, self.secret_reader.call_count)
        self.assertEqual([], self.worker.provider_bodies)

    def test_stale_review_unconfirmed_and_changed_limits_fail_before_secrets(self):
        reviewed = self.plan()
        body = start_request(reviewed)
        for changes, status in [(dict(confirmed=False), 400), (dict(confirmed=1), 400),
                                (dict(limits=goal_request()['limits']), 400),
                                (dict(spec_hash='0' * 64), 409)]:
            self.post('start', dict(body, **changes), status)
        self.assertEqual(0, self.secret_reader.call_count)
        self.assertEqual([], self.worker.calls)

    def test_root_mutation_after_review_invalidates_admission(self):
        reviewed = self.plan()
        path = next(self.private.glob('agent/*.npz'))
        weights = load_weights(path)
        weights['b3'][0] += 1
        save_weights(path, weights)
        value = self.post('start', start_request(reviewed), 409)
        self.assertEqual('spec_conflict', value['error']['code'])
        self.assertEqual(0, self.secret_reader.call_count)

    def test_double_click_start_and_concurrent_replays_admit_once(self):
        self.worker.block = True
        reviewed = self.plan()
        body = start_request(reviewed)
        # Direct calls exercise simultaneous server admission without serializing ASGI clients.
        with ThreadPoolExecutor(max_workers=8) as pool:
            replies = list(pool.map(lambda _: self.service.start(body), range(16)))
        self.assertEqual(1, len({reply['experiment_id'] for reply in replies}))
        run = replies[0]
        self.assertTrue(self.worker.entered.wait(3))
        self.assertEqual(run['experiment_id'], self.post('start', body)['experiment_id'])
        value = self.post('start', dict(body, idempotency_key='different_click'), 409)
        self.assertEqual('state_conflict', value['error']['code'])
        self.assertEqual(1, len(self.worker.calls))
        self.register()
        other_plan = self.plan()
        conflict = self.post('start', start_request(other_plan), 409)
        self.assertEqual('idempotency_conflict', conflict['error']['code'])
        self.worker.release.set()
        self.assertEqual('completed', self.terminal(run)['status'])
        self.assertEqual(run['experiment_id'], self.post('start', body)['experiment_id'])
        self.assertEqual(1, len(self.worker.calls))

    def test_service_rate_limit_has_bounded_same_action_retry_and_no_admission(self):
        self.service.limits = AdmissionLimits(plans_per_minute=1)
        self.plan()
        response = self.client.post(BASE + 'plan', json=goal_request())
        self.assert_public(response)
        self.assertEqual(429, response.status_code)
        self.assertEqual('5', response.headers['Retry-After'])
        error = validate_message('error_response', response.json())
        self.assertEqual('rate_limited', error['error']['code'])
        self.assertEqual(dict(action='same_request', after_seconds=5, max_attempts=3), error['retry'])
        self.assertEqual(0, self.secret_reader.call_count)
        self.assertEqual([], self.worker.calls)

    def test_held_out_report_is_blocked_until_every_selection_freezes(self):
        checked = []
        def check_gate(evaluator):
            with self.assertRaises(ValueError):
                evaluator.report()
            state = json.loads((evaluator.directory / 'agent' / 'private-state.json').read_text())
            self.assertTrue(any(not c['finalized'] for c in state['cases']))
            self.assertTrue(all(c['final'] is None or c['final']['status'] == 'frozen'
                                for c in state['cases']))
            checked.append(True)
        self.worker.at_root = check_gate
        done = self.terminal(self.start())
        self.assertEqual('completed', done['status'])
        self.assertTrue(checked)

    def test_queued_cancellation_does_not_load_a_second_key_or_refund_admission(self):
        self.worker.block = True
        first = self.start()
        self.assertTrue(self.worker.entered.wait(3))
        self.register()
        reviewed = self.plan()
        body = start_request(reviewed, key='queued_click')
        queued = self.post('start', body)
        self.assertEqual('queued', queued['status'])
        self.assertEqual('cancelling', self.post('cancel', query(queued))['status'])
        self.worker.release.set()
        self.assertEqual('completed', self.terminal(first)['status'])
        done = self.terminal(queued)
        self.assertEqual('cancelled', done['status'])
        self.assertEqual(0, done['usage']['requests'])
        self.assertEqual(1, self.secret_reader.call_count)
        self.assertEqual(1, len(self.worker.calls))
        self.assertFalse((self.private / '.orchestration.claim').exists())
        # Even an unexecuted admitted run is not silently recycled into fresh spend.
        self.assertEqual(queued['experiment_id'], self.post('start', body)['experiment_id'])
        self.post('start', start_request(self.plan(), key='fresh_key_same_roots'), 409)

    def test_provider_rate_limit_is_terminal_and_has_no_inference_retry(self):
        self.worker.mode = 'provider_429'
        done = self.terminal(self.start())
        self.assertEqual('failed', done['status'])
        self.assertIn(done['reason'], ('provider_rate_limited', 'provider_error'))
        self.assertEqual('not_evaluated', done['verdict'])
        self.assertIsNone(done['evidence'])
        self.assertEqual(1, len(self.worker.provider_bodies))
        # Current adapter can redact HTTP status: generic provider_error is honest.

    def test_provider_exception_cannot_echo_credentials_or_upstream_text(self):
        self.worker.mode = 'provider_error'
        done = self.terminal(self.start())
        self.assertEqual('failed', done['status'])
        self.assertEqual('not_evaluated', done['verdict'])
        self.assertIsNone(done['evidence'])
        self.assertEqual(1, len(self.worker.provider_bodies))

    def test_budget_exhaustion_preserves_usage_without_completed_result(self):
        self.worker.mode = 'spin'
        limits = dict(goal_request()['limits'], max_requests=1)
        done = self.terminal(self.start(self.plan(limits=limits)))
        self.assertEqual(('failed', 'budget_exhausted', 'not_evaluated'),
                         (done['status'], done['reason'], done['verdict']))
        self.assertIsNone(done['evidence'])
        self.assertEqual(1, done['usage']['requests'])
        self.assertEqual(1, len(self.worker.provider_bodies))
        self.assert_roots_preserved()

    def test_cancel_waits_for_worker_ack_and_preserves_reservations(self):
        self.worker.block = True
        run = self.start()
        self.assertTrue(self.worker.entered.wait(3))
        before = self.post('status', query(run))
        cancelled = self.post('cancel', query(run))
        self.assertEqual('cancelling', cancelled['status'])
        self.assertTrue(cancelled['usage']['request_in_flight'])
        self.assertFalse(cancelled['usage']['usage_complete'])
        self.assertEqual('cancelling', self.post('cancel', query(run))['status'])
        self.assertEqual('not_evaluated', cancelled['verdict'])
        self.worker.release.set()
        done = self.terminal(run)
        self.assertEqual(('cancelled', 'user_cancelled'), (done['status'], done['reason']))
        self.assertGreaterEqual(done['usage']['requests'], before['usage']['requests'])
        self.assertIsNone(done['evidence'])
        self.assertTrue((self.private / '.orchestration.claim').exists())
        self.assertEqual(done['status'], self.post('cancel', query(run))['status'])
        self.assertEqual(1, len(self.worker.provider_bodies))
        self.assert_roots_preserved()

    def test_reload_reconciles_existing_identity_and_never_restarts_work(self):
        self.worker.block = True
        run = self.start()
        self.assertTrue(self.worker.entered.wait(3))
        other_tab = self.new_client()
        current = self.post('status', query(run), client=other_tab)
        self.assertEqual(run['experiment_id'], current['experiment_id'])
        self.assertEqual('running', current['status'])
        self.assertEqual('unknown', current['phase']['name'])
        self.assertIsInstance(current['phase']['event_sequence'], int)
        self.post('results', query(run), 409, client=other_tab)
        self.assertEqual(1, len(self.worker.calls))
        self.register()
        other_plan = self.plan()
        conflict = self.post('start', start_request(other_plan), 409)
        self.assertEqual('idempotency_conflict', conflict['error']['code'])
        self.worker.release.set()
        self.assertEqual('completed', self.terminal(run)['status'])
        # New HTTP client is reconnection, not proof of a browser reload UX.

    def test_incomplete_selections_never_produce_measured_success(self):
        self.worker.mode = 'missing_selections'
        done = self.terminal(self.start())
        self.assertEqual('failed', done['status'])
        self.assertEqual('not_evaluated', done['verdict'])
        self.assertIsNone(done['evidence'])

    def test_missing_final_scores_are_not_filled_with_zero(self):
        original_report = Evaluator.report
        def remove_scores(evaluator):
            result = original_report(evaluator)
            path = evaluator.directory / 'agent' / 'private-state.json'
            state = json.loads(path.read_text())
            state['cases'][0]['final']['selected']['scores'] = []
            write_json(path, state)
            return result
        with patch.object(Evaluator, 'report', remove_scores):
            done = self.terminal(self.start())
        self.assertEqual(('failed', 'evaluation_error', 'not_evaluated'),
                         (done['status'], done['reason'], done['verdict']))
        self.assertIsNone(done['evidence'])

    def test_missing_provider_usage_stops_and_stays_unknown(self):
        self.worker.mode = 'unknown_usage'
        done = self.terminal(self.start())
        self.assertEqual('failed', done['status'])
        self.assertEqual('not_evaluated', done['verdict'])
        self.assertIsNone(done['evidence'])
        self.assertFalse(done['usage']['usage_complete'])
        self.assertGreater(done['usage']['requests'], 0)
        self.assertEqual(0, done['usage']['input_tokens'])  # known total, not a zero-cost claim

    def test_auth_origin_and_wrong_scope_errors_are_redacted(self):
        token = 'temporary-browser-auth-237823'
        self.canaries.append(token)
        authorized = self.new_client(token=token)
        self.post('plan', goal_request(), 403, client=authorized)
        self.post('plan', goal_request(), 403, headers={'Origin': 'https://foreign.invalid'})
        self.post('plan', goal_request(), 403, headers={'Sec-Fetch-Site': 'cross-site'})
        self.post('plan', goal_request(), 403, headers={'Host': 'foreign.invalid'})
        reviewed = self.post('plan', goal_request(), client=authorized,
                             headers={'Authorization': 'Bearer ' + token})
        self.assertEqual('ready', reviewed['outcome'])
        value = self.post('status', dict(schema_version=1, experiment_id='outside_scope'), 404)
        self.assertEqual('not_found', value['error']['code'])
        self.assertEqual(0, self.secret_reader.call_count)

    def test_abrupt_server_process_loss_interrupts_without_refund_or_resume(self):
        # Actual process death: no mocked persisted status and no graceful worker shutdown.
        crash_root = self.root / 'crash-process'
        code = r'''
import json, os, pathlib, socket, sys, threading, urllib.request
from fastapi.testclient import TestClient
from godseye.core import Store
from godseye.evaluator import Evaluator
from godseye.orchestration import Orchestrator
from godseye.provider_setup import ProviderSettings
from godseye.server import create_app
from goal_acceptance_support import PROVIDER_SECRET, ScriptedWorker, goal_request, start_request

def forbid(*args, **kwargs):
    raise AssertionError('External transport forbidden in crash fixture')
socket.socket.connect = socket.socket.connect_ex = urllib.request.urlopen = forbid
root = pathlib.Path(sys.argv[1])
root.mkdir()
settings = ProviderSettings(root / 'keys')
settings.save(PROVIDER_SECRET, 'scripted-acceptance')
worker = ScriptedWorker()
# Terminate only after a real root development probe has persisted its reservation/result.
worker.at_root = lambda evaluator: os._exit(73)
service = Orchestrator(root / 'service', worker=worker, settings=settings)
Evaluator.create(root / 'private', instances=1, episodes=2, max_steps=1, probes=2, forward_budget=4)
service.register(root / 'private', baseline_id='crash_roots', suite_id='acceptance_suite', revision='v1')
with TestClient(create_app(Store(root / 'public-lab'), orchestration=service)) as client:
    plan = client.post('/api/v1/experiments/plan', json=goal_request()).json()
    request = start_request(plan)
    (root / 'start.json').write_text(json.dumps(request))
    client.post('/api/v1/experiments/start', json=request)
    threading.Event().wait(10)
    os._exit(74)
'''
        env = {'PYTHONPATH': os.pathsep.join(sys.path), 'PYTHONDONTWRITEBYTECODE': '1'}
        completed = subprocess.run([sys.executable, '-c', code, str(crash_root)], env=env,
                                   capture_output=True, text=True, timeout=15)
        self.assertEqual(73, completed.returncode, completed.stderr)
        state_path = crash_root / 'private' / 'agent' / 'private-state.json'
        before = json.loads(state_path.read_text())
        reservations = [(len(c['attempts']), c['forward_reserved']) for c in before['cases']]
        self.assertTrue(any(probes > 0 for probes, forwards in reservations))
        claim = (crash_root / 'private' / '.orchestration.claim').read_text()
        worker = ScriptedWorker()
        settings = ProviderSettings(crash_root / 'keys')
        with patch.object(settings, 'credential', side_effect=AssertionError('Restart read key')):
            resumed = Orchestrator(crash_root / 'service', worker=worker, settings=settings)
            try:
                run = dict(experiment_id=claim)
                with TestClient(create_app(Store(crash_root / 'public-lab'),
                                           orchestration=resumed)) as client:
                    status = self.post('status', query(run), client=client)
                    result = self.post('results', query(run), client=client)
                    replay = self.post('start', json.loads((crash_root / 'start.json').read_text()),
                                       client=client)
                self.assertEqual(('interrupted', 'process_lost', 'not_evaluated'),
                                 (status['status'], status['reason'], status['verdict']))
                self.assertEqual('unknown', status['phase']['name'])
                self.assertIsNone(result['evidence'])
                self.assertEqual(claim, replay['experiment_id'])
                self.assertEqual([], worker.calls)
                self.assertEqual([], worker.provider_bodies)
                self.assertIn(claim, worker.recovered)
            finally:
                resumed.close()
        after = json.loads(state_path.read_text())
        self.assertEqual(reservations, [(len(c['attempts']), c['forward_reserved'])
                                        for c in after['cases']])
        self.assertEqual(claim, (crash_root / 'private' / '.orchestration.claim').read_text())


if __name__ == '__main__':
    unittest.main()
