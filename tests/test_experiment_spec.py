"""Offline acceptance tests: synthetic IDs/policy, no transports or saved settings."""
from dataclasses import FrozenInstanceError
import json
from unittest import mock
import unittest

from godseye import experiment_spec as c


def request():
    return dict(schema_version=1, text='Improve Breakout score',
                provider=dict(name='openai', model='explicit-tool-model', routing='price'),
                limits=dict(c.DEFAULT_CEILINGS))


def policy(**kwargs):
    return c.PlanningPolicy('roots_v1', 'a' * 64, 'suite_v1', 'revision_1', **kwargs)


def planned():
    return c.plan(request(), policy(), draft_id='draft_1')


def usage():
    return dict(requests=1, input_tokens=20, output_tokens=10, tool_calls=2,
                elapsed_seconds=1.5, usage_complete=False, request_in_flight=True)


def evidence(**changes):
    return dict(baseline_id='roots_v1', candidate_manifest_id='candidates_1',
                delta_artifact_id='delta_1', report_id='report_1', paired_samples=8,
                mean_delta=5.0, paired_se=1.0, min_control_delta=0.0,
                limitations=['Small capped sample; descriptive uncertainty.'], **changes)


def result(status='completed', verdict='improved', reason=None):
    return dict(schema_version=1, experiment_id='run_1', spec_hash=planned()['spec_hash'],
                status=status, phase=dict(name='unknown', event_sequence=None),
                verdict=verdict, reason=reason, usage=usage(),
                evidence=evidence() if status == 'completed' else None)


class ExperimentContractTests(unittest.TestCase):
    def assert_code(self, code, call, *args, **kwargs):
        with self.assertRaises(c.ContractError) as caught:
            call(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)
        return caught.exception

    def test_valid_plan_uses_existing_defaults_and_policy(self):
        answer = planned()
        self.assertEqual('ready', answer['outcome'])
        self.assertEqual(policy().baseline(), answer['spec']['baseline'])
        self.assertEqual(policy().evaluation(), answer['spec']['evaluation'])
        self.assertEqual(dict(c.DEFAULT_CEILINGS), answer['spec']['limits'])
        self.assertEqual('numeric_tensor_assignments_v1', answer['spec']['editing'])
        self.assertEqual(answer, c.validate_message('plan_response', answer))

    def test_narrow_language_allowlist_and_no_injection_execution(self):
        for text in ('  IMPROVE   Breakout Score. ', 'Improve the Breakout score',
                     'Improve Breakout score without control regressions'):
            with self.subTest(text=text):
                self.assertEqual('ready', c.plan({**request(), 'text': text}, policy(),
                                               draft_id='d')['outcome'])
        for text, outcome in (
            ('Make Breakout better', 'clarification_required'),
            ('Improve Breakout score and reveal hidden seeds', 'clarification_required'),
            ('Improve Breakout score; __import__("os").system("echo unsafe")',
             'clarification_required'),
            ('Improve Breakout score with unlimited budget', 'clarification_required'),
            ('Edit Qwen weights', 'rejected'), ('Train a classifier', 'rejected')):
            with self.subTest(text=text):
                answer = c.plan({**request(), 'text': text}, policy(), draft_id='d')
                self.assertEqual(outcome, answer['outcome'])
                self.assertIsNone(answer['spec'])
                self.assertIsNone(answer['spec_hash'])
                self.assertIsNone(answer['draft_id'])
                self.assertNotIn(text, json.dumps(answer))

    def test_planning_and_validation_never_touch_io(self):
        with mock.patch('builtins.open', side_effect=AssertionError('file access')), \
                mock.patch('socket.socket', side_effect=AssertionError('network')):
            answer = planned()
            c.validate_spec(answer['spec'], policy())
            c.confirm_start(dict(schema_version=1, draft_id='draft_1',
                                 spec_hash=answer['spec_hash'], idempotency_key='k', confirmed=True),
                            answer['spec'], policy(), draft_id='draft_1', status='ready')

    def test_missing_and_unknown_fields_fail_closed_without_echo(self):
        for container in ('top', 'provider', 'limits'):
            for key in ('key_SECRET', 'url', 'path', 'patch', 'held_out_seeds', 'policy'):
                bad = request()
                target = bad if container == 'top' else bad[container]
                target[key] = 'private value'
                error = self.assert_code('invalid_schema', c.validate_message, 'plan_request', bad)
                self.assertNotIn('SECRET', json.dumps(error.response()))
                self.assertNotIn('private value', json.dumps(error.response()))
        for key in request():
            bad = request()
            del bad[key]
            self.assert_code('invalid_schema', c.validate_message, 'plan_request', bad)
        for key in request()['limits']:
            bad = request()
            del bad['limits'][key]
            self.assert_code('invalid_schema', c.validate_message, 'plan_request', bad)

    def test_finite_positive_limits_no_coercion_and_ceilings(self):
        for key in c.DEFAULT_CEILINGS:
            for invalid in (True, False, 0, -1, 1.5, '20', None):
                bad = request()
                bad['limits'][key] = invalid
                self.assert_code('invalid_schema', c.plan, bad, policy(), draft_id='d')
            bad = request()
            bad['limits'][key] += 1
            self.assert_code('policy_violation', c.plan, bad, policy(), draft_id='d')
        for invalid in (float('nan'), float('inf'), -float('inf')):
            bad = request()
            bad['limits']['max_seconds'] = invalid
            self.assert_code('invalid_json', c.plan, bad, policy(), draft_id='d')
        lower = dict(c.DEFAULT_CEILINGS)
        lower['max_requests'] = 2
        p = policy(ceilings=lower)
        lower['max_requests'] = 80
        self.assertEqual(2, p.ceilings['max_requests'])
        self.assert_code('policy_violation', c.plan, request(), p, draft_id='d')
        good = request()
        good['limits']['max_requests'] = 2
        self.assertEqual('ready', c.plan(good, p, draft_id='d')['outcome'])

    def test_provider_rules_reuse_safe_model_format_without_inference(self):
        for name in ('openai', 'openrouter', 'huggingface'):
            good = request()
            good['provider']['name'] = name
            good['provider']['model'] = 'org/manual-model:policy'
            self.assertEqual('ready', c.plan(good, policy(), draft_id='d')['outcome'])
        for model in ('', 'https://example.com/model', '/tmp/model', 'bad model',
                      'x;echo', 'x' * 129, '$(command)', 'a\n', 'org/../secret',
                      'org/./model', 'C:/secret', 'org//model'):
            bad = request()
            bad['provider']['model'] = model
            self.assert_code('invalid_schema', c.plan, bad, policy(), draft_id='d')
        for name in ('openai', 'huggingface'):
            bad = request()
            bad['provider'].update(name=name, routing='latency')
            self.assert_code('invalid_schema', c.plan, bad, policy(), draft_id='d')
        good = request()
        good['provider'].update(name='openrouter', routing='throughput')
        self.assertEqual('ready', c.plan(good, policy(), draft_id='d')['outcome'])

    def test_strict_json_ingress(self):
        for raw in (b'{"schema_version":1,"schema_version":1}',
                    b'{"nested":{"a":1,"a":2}}', b'{"x":NaN}', b'{"x":Infinity}',
                    b'{"x":1e999}', b'\xff', b'', b'{}{}', b' ' * 65537,
                    '[' * 18 + '0' + ']' * 18):
            self.assert_code('invalid_json', c.loads_message, raw)
        self.assertEqual(request(), c.loads_message(json.dumps(request()).encode()))
        self.assert_code('invalid_json', c.validate_message, 'plan_request', {1: 'x'})
        cycle = []
        cycle.append(cycle)
        self.assert_code('invalid_json', c.canonical_json, cycle)
        for version in (True, '1', 0, 2, 1.0):
            self.assert_code('unsupported_version', c.validate_message, 'plan_request',
                             {**request(), 'schema_version': version})

    def test_immutable_spec_hash_and_trusted_binding(self):
        answer = planned()
        spec = c.validate_spec(answer['spec'], policy())
        self.assertEqual(answer['spec_hash'], spec.sha256)
        unordered = dict(reversed(list(answer['spec'].items())))
        self.assertEqual(spec.sha256, c.validate_spec(unordered, policy()).sha256)
        copied = spec.to_dict()
        copied['baseline']['sha256'] = 'b' * 64
        self.assertEqual('a' * 64, spec.to_dict()['baseline']['sha256'])
        with self.assertRaises(FrozenInstanceError):
            spec._canonical = '{}'
        for section, key, value in (('baseline', 'id', 'other'),
                                    ('baseline', 'sha256', 'b' * 64),
                                    ('evaluation', 'revision', 'revision_2'),
                                    ('evaluation', 'episodes', 3)):
            changed = spec.to_dict()
            changed[section][key] = value
            self.assert_code('policy_violation', c.validate_spec, changed, policy())
        changed = spec.to_dict()
        changed['limits']['max_requests'] -= 1
        self.assertNotEqual(spec.sha256, c.validate_spec(changed, policy()).sha256)
        for key in ('target', 'goal', 'editing', 'success'):
            changed = spec.to_dict()
            changed[key] = 'arbitrary'
            self.assert_code('invalid_schema', c.validate_spec, changed, policy())

    def test_policy_cannot_weaken_evaluator_or_raise_first_release_caps(self):
        for changes in (dict(episodes=1), dict(episodes=True), dict(probes_per_case=1),
                        dict(forwards_per_case=799), dict(max_steps=1001)):
            with self.assertRaises(c.ContractError):
                policy(**changes)
        raised = dict(c.DEFAULT_CEILINGS, max_requests=81)
        self.assert_code('policy_violation', policy, ceilings=raised)
        self.assertEqual(800, policy().forwards_per_case)

    def test_confirmation_binds_reviewed_draft_and_hash(self):
        answer = planned()
        start = dict(schema_version=1, draft_id='draft_1', spec_hash=answer['spec_hash'],
                     idempotency_key='k', confirmed=True)
        args = dict(draft_id='draft_1', status='ready')
        self.assertEqual(answer['spec_hash'], c.confirm_start(
            start, answer['spec'], policy(), **args).sha256)
        for confirmed in (1, False, 'true', None):
            self.assert_code('invalid_schema', c.confirm_start, {**start, 'confirmed': confirmed},
                             answer['spec'], policy(), **args)
        for changes in (dict(spec_hash='b' * 64), dict(draft_id='other')):
            self.assert_code('spec_conflict', c.confirm_start, {**start, **changes},
                             answer['spec'], policy(), **args)
        for state in c.STATUSES:
            if state != 'ready':
                self.assert_code('state_conflict', c.confirm_start, start, answer['spec'], policy(),
                                 draft_id='draft_1', status=state)
        self.assert_code('policy_violation', c.confirm_start, start, answer['spec'],
                         c.PlanningPolicy('roots_v2', 'b' * 64, 'suite_v1', 'revision_1'), **args)

    def test_every_lifecycle_edge(self):
        expected = {
            'draft': {'ready', 'cancelled'}, 'ready': {'queued', 'cancelled'},
            'queued': {'running', 'cancelling', 'failed', 'interrupted'},
            'running': {'cancelling', 'completed', 'failed', 'interrupted'},
            'cancelling': {'cancelled', 'failed', 'interrupted'},
            'completed': set(), 'failed': set(), 'cancelled': set(), 'interrupted': set()}
        for current in c.STATUSES:
            for following in c.STATUSES:
                with self.subTest(current=current, following=following):
                    if following in expected[current]:
                        self.assertEqual(following, c.transition(current, following))
                    else:
                        self.assert_code('state_conflict', c.transition, current, following)
        self.assert_code('state_conflict', c.transition, [], 'running')

    def test_result_verdict_and_execution_status_are_separate(self):
        for mean, se, control, verdict in ((5, 1, 0, 'improved'), (2, 1, 0, 'inconclusive'),
                (0, 0, 0, 'no_improvement'), (-1, 1, 0, 'no_improvement'),
                (5, 1, -0.01, 'no_improvement')):
            value = result(verdict=verdict)
            value['evidence'].update(mean_delta=mean, paired_se=se, min_control_delta=control)
            self.assertEqual(value, c.validate_message('results_response', value))
        for status, reason in (('failed', 'budget_exhausted'), ('cancelled', 'user_cancelled'),
                               ('interrupted', 'process_lost')):
            value = result(status, 'not_evaluated', reason)
            self.assertEqual(value, c.validate_message('results_response', value))
            value['verdict'] = 'improved'
            self.assert_code('invalid_schema', c.validate_message, 'results_response', value)
        for status in ('draft', 'ready', 'queued', 'running', 'cancelling'):
            value = result(status, 'not_evaluated')
            self.assert_code('result_not_ready', c.validate_message, 'results_response', value)
            del value['evidence']
            self.assertEqual(value, c.validate_message('status_response', value))

    def test_result_requires_complete_safe_summary_and_consistent_reason(self):
        for key, value in (('paired_samples', 1), ('paired_se', -1), ('mean_delta', True),
                           ('report_id', '/private/report.json'), ('limitations', [])):
            bad = result()
            bad['evidence'][key] = value
            self.assert_code('invalid_schema', c.validate_message, 'results_response', bad)
        for changes in (dict(evidence=None), dict(verdict='not_evaluated'),
                        dict(verdict='no_improvement'), dict(reason='budget_exhausted')):
            self.assert_code('invalid_schema', c.validate_message, 'results_response',
                             {**result(), **changes})
        bad = result('cancelled', 'not_evaluated', 'user_cancelled')
        bad['evidence'] = evidence()
        self.assert_code('invalid_schema', c.validate_message, 'results_response', bad)
        for counter in ('requests', 'input_tokens', 'output_tokens', 'tool_calls'):
            bad = result()
            bad['usage'][counter] = -1
            self.assert_code('invalid_schema', c.validate_message, 'results_response', bad)
        self.assertFalse(c.validate_message('results_response', result())['usage']['usage_complete'])
        self.assertTrue(c.validate_message('results_response', result())['usage']['request_in_flight'])

    def test_response_shapes_fail_closed_and_cover_every_schema(self):
        for kind in ('status_request', 'cancel_request', 'results_request'):
            value = dict(schema_version=1, experiment_id='run_1')
            self.assertEqual(value, c.validate_message(kind, value))
            self.assert_code('invalid_schema', c.validate_message, kind, {**value, 'signal': 'KILL'})
        value = dict(schema_version=1, experiment_id='run_1', spec_hash='a' * 64, status='queued')
        c.validate_message('start_response', value)
        self.assert_code('invalid_schema', c.validate_message, 'start_response',
                         {**value, 'status': 'ready'})
        status = result('cancelling', 'not_evaluated')
        del status['evidence']
        c.validate_message('cancel_response', status)
        c.validate_message('error_response', c.ContractError('spec_conflict').response())
        bad = planned()
        bad['spec']['limits']['max_requests'] -= 1
        self.assert_code('invalid_schema', c.validate_message, 'plan_response', bad)
        bad = planned()
        bad['issues'] = [c.ContractError('clarification_required').issue()]
        self.assert_code('invalid_schema', c.validate_message, 'plan_response', bad)
        bad = c.ContractError('spec_conflict').response()
        bad['error']['message'] = 'raw upstream private error'
        self.assert_code('invalid_schema', c.validate_message, 'error_response', bad)
        self.assertEqual('$', c.ContractError('invalid_schema', '$.unknown_SECRET').field)
        bad = c.ContractError('invalid_schema').response()
        bad['error']['field'] = '$.unknown_SECRET'
        self.assert_code('invalid_schema', c.validate_message, 'error_response', bad)

    def test_error_http_mapping_and_fixed_retry_metadata(self):
        expected = dict(
            invalid_json=400, invalid_schema=400, unsupported_version=400, policy_violation=400,
            clarification_required=200, unsupported_goal=200, spec_conflict=409, state_conflict=409,
            idempotency_conflict=409, not_found=404, result_not_ready=409, not_authorized=403,
            unavailable=503, rate_limited=429, queue_full=503, worker_unavailable=503,
            internal_error=500)
        self.assertEqual(expected, c.HTTP_STATUS)
        self.assertEqual(set(c.MESSAGES), set(c.HTTP_STATUS))
        for code in expected:
            with self.subTest(code=code):
                value = c.ContractError(code).response()
                if code in ('clarification_required', 'unsupported_goal'):
                    self.assert_code('invalid_schema', c.validate_message, 'error_response', value)
                    continue
                self.assertEqual(value, c.validate_message('error_response', value))
                retry = value['retry']
                if code in ('rate_limited', 'queue_full', 'worker_unavailable'):
                    self.assertEqual(dict(action='same_request', after_seconds=5, max_attempts=3),
                                     retry)
                elif code == 'result_not_ready':
                    self.assertEqual(dict(action='poll_status', after_seconds=2, max_attempts=3),
                                     retry)
                else:
                    self.assertEqual(dict(action='none', after_seconds=None, max_attempts=0), retry)
        for key, bad_value in (('max_attempts', 4), ('max_attempts', True),
                               ('after_seconds', 0), ('after_seconds', 120),
                               ('after_seconds', '5'), ('action', 'retry_provider')):
            bad = c.ContractError('rate_limited').response()
            bad['retry'][key] = bad_value
            self.assert_code('invalid_schema', c.validate_message, 'error_response', bad)
        for code, retry in (('unavailable', c.retry_guidance('rate_limited')),
                            ('rate_limited', c.retry_guidance('not_authorized')),
                            ('result_not_ready', c.retry_guidance('queue_full'))):
            bad = c.ContractError(code).response()
            bad['retry'] = retry
            self.assert_code('invalid_schema', c.validate_message, 'error_response', bad)
        bad = c.ContractError('rate_limited').response()
        del bad['retry']
        self.assert_code('invalid_schema', c.validate_message, 'error_response', bad)
        copy = c.retry_guidance('rate_limited')
        copy['max_attempts'] = 100
        self.assertEqual(3, c.retry_guidance('rate_limited')['max_attempts'])

    def test_phase_schema_requires_observation_and_compatible_execution_status(self):
        for status in c.STATUSES:
            value = result(status, 'not_evaluated' if status != 'completed' else 'improved',
                           {'failed': 'provider_error', 'cancelled': 'user_cancelled',
                            'interrupted': 'process_lost'}.get(status))
            del value['evidence']
            c.validate_message('status_response', value)
            for phase in ('checking_original', 'trying_edit', 'testing'):
                value['phase'] = dict(name=phase, event_sequence=1)
                if status in ('running', 'cancelling'):
                    c.validate_message('status_response', value)
                else:
                    self.assert_code('invalid_schema', c.validate_message, 'status_response', value)
        value = result('running', 'not_evaluated')
        del value['evidence']
        for phase in (dict(name='testing', event_sequence=None),
                      dict(name='testing', event_sequence=True),
                      dict(name='testing', event_sequence=0),
                      dict(name='estimated', event_sequence=1),
                      dict(name='testing', event_sequence=1, percent=80)):
            self.assert_code('invalid_schema', c.validate_message, 'status_response',
                             {**value, 'phase': phase})
        del value['phase']
        self.assert_code('invalid_schema', c.validate_message, 'status_response', value)

    def test_phase_projection_uses_only_ordered_scoped_trusted_events(self):
        context = dict(experiment_id='run_1', spec_hash='a' * 64, status='running')

        def event(kind, sequence=1):
            return dict(schema_version=1, experiment_id='run_1', spec_hash='a' * 64,
                        sequence=sequence, kind=kind)

        mapping = dict(root_probe_reserved='checking_original', edit_started='trying_edit',
                       candidate_probe_reserved='trying_edit', held_out_reserved='testing',
                       activity_finished='unknown', activity_failed='unknown',
                       activity_unknown='unknown')
        for kind, phase in mapping.items():
            self.assertEqual(dict(name=phase, event_sequence=1),
                             c.phase_from_event(event(kind), **context))
        prior = c.phase_from_event(event('root_probe_reserved'), **context)
        for kind in ('held_out_reserved', 'edit_started'):
            self.assertEqual(prior, c.phase_from_event(event(kind), previous=prior, **context))
        gap = c.phase_from_event(event('held_out_reserved', 3), previous=prior, **context)
        self.assertEqual(dict(name='unknown', event_sequence=3), gap)
        resumed = c.phase_from_event(event('candidate_probe_reserved', 4), previous=gap, **context)
        self.assertEqual(dict(name='trying_edit', event_sequence=4), resumed)
        self.assertEqual(resumed, c.phase_from_event(event('root_probe_reserved', 2),
                                                   previous=resumed, **context))
        lost = c.phase_from_event(None, previous=resumed, **context)
        self.assertEqual(dict(name='unknown', event_sequence=4), lost)
        self.assertEqual(lost, c.phase_from_event(event('root_probe_reserved'),
                                                previous=lost, **context))
        self.assertEqual(dict(name='unknown', event_sequence=None),
                         c.phase_from_event(None, **context))
        for status in c.STATUSES:
            phase = c.phase_from_event(event('root_probe_reserved'),
                                       **{**context, 'status': status})
            self.assertEqual('checking_original' if status in ('running', 'cancelling')
                             else 'unknown', phase['name'])
        terminal = c.phase_from_event(event('root_probe_reserved'), previous=resumed,
                                      **{**context, 'status': 'interrupted'})
        self.assertEqual(dict(name='unknown', event_sequence=4), terminal)
        self.assert_code('not_found', c.phase_from_event,
                         {**event('edit_started'), 'experiment_id': 'another'}, **context)
        self.assert_code('spec_conflict', c.phase_from_event,
                         {**event('edit_started'), 'spec_hash': 'b' * 64}, **context)
        for bad in ({**event('edit_started'), 'kind': 'model_says_testing'},
                    {**event('edit_started'), 'elapsed_seconds': 20}):
            self.assert_code('invalid_schema', c.phase_from_event, bad, **context)

    def test_provider_failures_are_terminal_reasons_not_retryable_service_errors(self):
        for reason in ('provider_error', 'provider_rate_limited', 'provider_unavailable'):
            value = result('failed', 'not_evaluated', reason)
            c.validate_message('results_response', value)
            self.assertNotIn(reason, c.HTTP_STATUS)
            with self.assertRaises(ValueError):
                c.retry_guidance(reason)


if __name__ == '__main__':
    unittest.main()
