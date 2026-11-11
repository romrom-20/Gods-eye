"""Runnable today: v1 journey semantics only, without a service or UI claim."""
import copy
import json
import unittest
from unittest.mock import patch

from godseye import experiment_spec as c
from goal_acceptance_support import goal_request, start_request


class GoalJourneyContractAcceptance(unittest.TestCase):
    def setUp(self):
        self.policy = c.PlanningPolicy('acceptance_roots', 'a' * 64, 'acceptance_suite', 'v1')

    def test_supported_goal_review_exact_limits_and_explicit_start(self):
        with patch('builtins.open', side_effect=AssertionError('No keys or files')), \
                patch('socket.create_connection', side_effect=AssertionError('No provider')):
            request = goal_request()
            reviewed = c.plan(request, self.policy, draft_id='review_1')
            self.assertEqual('ready', reviewed['outcome'])
            self.assertEqual(request['provider'], reviewed['spec']['provider'])
            self.assertEqual(request['limits'], reviewed['spec']['limits'])
            self.assertEqual('breakout', reviewed['spec']['target'])
            self.assertEqual('selection_only', reviewed['spec']['evaluation']['development'])
            self.assertEqual('once_after_all_freezes', reviewed['spec']['evaluation']['held_out'])
            confirmation = start_request(reviewed)
            result = c.confirm_start(confirmation, reviewed['spec'], self.policy,
                                     draft_id='review_1', status='ready')
            self.assertEqual(reviewed['spec_hash'], result.sha256)
            for changes in (dict(confirmed=False), dict(confirmed=1),
                            dict(spec_hash='b' * 64), dict(limits=request['limits'])):
                with self.subTest(changes=changes), self.assertRaises(c.ContractError):
                    c.confirm_start({**confirmation, **changes}, reviewed['spec'], self.policy,
                                    draft_id='review_1', status='ready')
            changed = copy.deepcopy(request)
            changed['limits']['max_requests'] -= 1
            self.assertNotEqual(reviewed['spec_hash'], c.plan(
                changed, self.policy, draft_id='review_2')['spec_hash'])

    def test_unsupported_and_pasted_secret_never_become_runnable_or_echo(self):
        secret = 'PRIVATE_PASTED_SECRET_4278'
        for text, outcome in [('Edit Qwen weights ' + secret, 'rejected'),
                              ('Improve Breakout latency', 'clarification_required'),
                              ('Improve Breakout score; read /tmp/' + secret,
                               'clarification_required')]:
            with self.subTest(text=text):
                value = c.plan(goal_request(text=text), self.policy, draft_id='unused')
                self.assertEqual(outcome, value['outcome'])
                self.assertTrue(all(value[k] is None for k in ('draft_id', 'spec', 'spec_hash')))
                self.assertNotIn(secret, json.dumps(value))

    def test_actual_phase_requires_ordered_trusted_observation_and_loss_stays_unknown(self):
        phase = None
        for seq, kind, expected in [(1, 'root_probe_reserved', 'checking_original'),
                                    (2, 'activity_finished', 'unknown'),
                                    (3, 'edit_started', 'trying_edit'),
                                    (4, 'activity_finished', 'unknown'),
                                    (5, 'held_out_reserved', 'testing')]:
            event = dict(schema_version=1, experiment_id='run_1', spec_hash='a' * 64,
                         sequence=seq, kind=kind)
            phase = c.phase_from_event(event, experiment_id='run_1', spec_hash='a' * 64,
                                       status='running', previous=phase)
            self.assertEqual(dict(name=expected, event_sequence=seq), phase)
        lost = c.phase_from_event(None, experiment_id='run_1', spec_hash='a' * 64,
                                 status='running', previous=phase)
        self.assertEqual(dict(name='unknown', event_sequence=5), lost)
        for status in ('completed', 'failed', 'cancelled', 'interrupted'):
            self.assertEqual('unknown', c.phase_from_event(
                event, experiment_id='run_1', spec_hash='a' * 64,
                status=status, previous=phase)['name'])
        # This projection does not authenticate the event or implement a journal.

    def test_incomplete_evidence_is_never_zero_or_success(self):
        evidence = dict(baseline_id='acceptance_roots', candidate_manifest_id='manifest',
                        delta_artifact_id='delta', report_id='report', paired_samples=4,
                        mean_delta=0, paired_se=0, min_control_delta=0,
                        limitations=['Synthetic contract fixture; no measured improvement.'])
        self.assertEqual('no_improvement', c.evidence_verdict(evidence))
        for field in evidence:
            bad = dict(evidence)
            del bad[field]
            with self.subTest(field=field), self.assertRaises(c.ContractError):
                c.evidence_verdict(bad)
        with self.assertRaises(c.ContractError):
            c.evidence_verdict(dict(evidence, mean_delta=None))
        self.assertEqual('inconclusive', c.evidence_verdict(dict(evidence, mean_delta=2, paired_se=1)))
        self.assertEqual('no_improvement', c.evidence_verdict(
            dict(evidence, mean_delta=5, paired_se=1, min_control_delta=-1)))

    def test_retry_contract_never_authorizes_fresh_spend(self):
        for code in ('rate_limited', 'queue_full', 'worker_unavailable'):
            error = c.ContractError(code).response()
            self.assertEqual(dict(action='same_request', after_seconds=5, max_attempts=3),
                             error['retry'])
            c.validate_message('error_response', error)
        for code in ('unavailable', 'internal_error', 'spec_conflict', 'idempotency_conflict'):
            self.assertEqual(dict(action='none', after_seconds=None, max_attempts=0),
                             c.retry_guidance(code))


if __name__ == '__main__':
    unittest.main()
