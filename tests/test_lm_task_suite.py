"""Synthetic supplied-output evidence, never a model-quality experiment."""
import copy
import unittest

from godseye.lm.task_contract import PHRASES, TaskSpec, canonical, preview, digest
from godseye.lm.task_suite import (
    VARIANTS, cases, dataset_identity, evaluate, freeze_selection, score_output,
    validate_record,
)


def spec():
    return TaskSpec(canonical(preview(PHRASES[0], revision='a' * 40)['spec']))


def records(specification, split, variants, mode='correct'):
    result = []
    for variant in variants:
        for index, case in enumerate(cases(split)):
            output = case['answer'] if case['task'] == 'regression' else canonical(case['answer'])
            if mode == 'dev_gain' and case['task'] != 'regression':
                if variant == 'unchanged' or (variant == 'weight-1' and index < 3):
                    output = 'Answer: ' + output
            result.append({'attempt_id': f'{split}-{variant}-{index}',
                           'spec_sha256': specification.sha256, 'case_id': case['id'],
                           'split': split, 'variant': variant, 'status': 'complete',
                           'output': output, 'input_tokens': 100, 'output_tokens': 20,
                           'elapsed_seconds': 0.1})
    return result


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.spec = spec()
        self.dev = records(self.spec, 'dev', VARIANTS, 'dev_gain')
        self.freeze = freeze_selection(self.spec, self.dev)
        self.heldout = records(self.spec, 'heldout', self.freeze['heldout_variants'])

    def test_fixture_splits_identity_and_reference_answers(self):
        dev, heldout = cases('dev'), cases('heldout')
        self.assertEqual([len(dev), len(heldout)], [14, 14])
        self.assertFalse({r['family'] for r in dev} & {r['family'] for r in heldout})
        self.assertFalse({r['id'] for r in dev} & {r['id'] for r in heldout})
        self.assertFalse({r['prompt'] for r in dev} & {r['prompt'] for r in heldout})
        for split in ('dev', 'heldout'):
            self.assertEqual(sum(c['task'] == 'extraction' for c in cases(split)), 6)
            self.assertEqual(sum(c['task'] == 'classification' for c in cases(split)), 4)
            for case in cases(split):
                output = case['answer'] if case['task'] == 'regression' else canonical(case['answer'])
                self.assertTrue(score_output(case, output)['correct'])
        self.assertEqual(dataset_identity()['sha256'],
                         digest({s: cases(s) for s in ('dev', 'heldout')}))
        # Pin intentional fixture changes to an explicit version/hash review.
        self.assertEqual(dataset_identity()['sha256'], '8fed6ab63c06cb5fe22068695340e4412d2fa2dae3f3d6cd3871017e53819582')
        dev[0]['answer']['owner'] = 'mutated'
        self.assertEqual(cases('dev')[0]['answer']['owner'], 'Mira')

    def test_schema_and_semantics_are_distinct(self):
        case = cases('dev')[0]
        self.assertEqual(score_output(case, '{"owner":"Wrong","badge":17}'),
                         {'schema_ok': True, 'correct': False, 'error': None})
        for raw in ('{"owner":"Mira","badge":true}', '{"owner":"Mira","badge":17.0}',
                    '{"owner":"Mira","badge":17,"extra":0}'):
            self.assertFalse(score_output(case, raw)['schema_ok'])
        self.assertTrue(score_output(case, ' {"badge":17,"owner":"Mira"}\n')['correct'])
        for raw in ('{"owner":"Mira","owner":"Wrong","badge":17}',
                    '```json\n{"owner":"Mira","badge":17}\n```',
                    '{"owner":"Mira","badge":17} Thanks', '{"badge":NaN}', '{"badge":1e999}'):
            self.assertEqual(score_output(case, raw)['error'], 'invalid_json')

    def test_selection_uses_dev_only_and_ties_keep_original(self):
        self.assertEqual(self.freeze['selected_weight'], 'weight-0')
        self.assertTrue(self.freeze['selection_eligible'])
        with self.assertRaises(ValueError):
            freeze_selection(self.spec, self.dev + self.heldout)
        tied = records(self.spec, 'dev', VARIANTS)
        self.assertEqual(freeze_selection(self.spec, tied)['selected_weight'], 'unchanged')
        # Candidate tie is deterministic, with no heldout tie breaker.
        for row in self.dev:
            if row['variant'] == 'weight-1' and row['case_id'].startswith('dev-'):
                row['output'] = next(r['output'] for r in self.dev
                                     if r['variant'] == 'weight-0' and r['case_id'] == row['case_id'])
        self.assertEqual(freeze_selection(self.spec, self.dev)['selected_weight'], 'weight-0')

    def test_selection_blocks_failed_missing_duplicate_or_control_regression(self):
        for mutation in ('failed', 'budget_limited', 'incomplete', 'missing', 'duplicate', 'control'):
            rows = copy.deepcopy(self.dev)
            if mutation == 'missing':
                rows.pop()
            elif mutation == 'duplicate':
                rows.append(dict(rows[0], attempt_id='extra'))
            elif mutation == 'control':
                for row in rows:
                    if row['variant'].startswith('weight') and row['case_id'] == 'dev-copy':
                        row['output'] = 'wrong'
            else:
                rows[0]['status'] = mutation
            self.assertEqual(freeze_selection(self.spec, rows)['selected_weight'], 'unchanged')

    def test_holdout_regression_blocks_an_apparent_schema_gain(self):
        for row in self.heldout:
            if row['variant'] == 'unchanged' and row['case_id'] == 'heldout-museum_label':
                row['output'] = 'not json'
            if row['variant'] == 'weight-0' and row['case_id'] == 'heldout-subtraction':
                row['output'] = '0'
        report = evaluate(self.spec, self.freeze, self.dev + self.heldout)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['verdict'], 'no_improvement')
        self.assertEqual(report['comparisons']['weight-0']['regression_failures'], 1)
        self.assertEqual(report['attempt_count'], 126)
        self.assertEqual(len(report['records']), 126)

    def test_small_observed_gain_is_inconclusive_and_uncertainty_bounded(self):
        for row in self.heldout:
            if row['variant'] == 'unchanged' and row['case_id'] == 'heldout-museum_label':
                row['output'] = 'not json'
        report = evaluate(self.spec, self.freeze, self.dev + self.heldout)
        self.assertEqual(report['verdict'], 'inconclusive')
        comparison = report['comparisons']['weight-0']
        self.assertAlmostEqual(comparison['schema_difference'], 0.1)
        self.assertEqual(comparison['paired_target_n'], 10)
        self.assertLess(comparison['difference_interval'][0], 0)
        self.assertLessEqual(comparison['difference_interval'][1], 1)

    def test_semantic_regression_cannot_be_hidden_by_schema_success(self):
        for row in self.heldout:
            if row['variant'] == 'weight-0' and row['case_id'] == 'heldout-museum_label':
                row['output'] = '{"creator":"Wrong","year":1932}'
        report = evaluate(self.spec, self.freeze, self.dev + self.heldout)
        self.assertEqual(report['comparisons']['weight-0']['semantic_regressions'], 1)
        self.assertEqual(report['verdict'], 'no_improvement')

    def test_semantic_loss_blocks_dev_selection_even_if_schema_improves(self):
        rows = copy.deepcopy(self.dev)
        # Give unchanged one genuinely correct answer and both candidates a typed wrong one.
        for row in rows:
            if row['case_id'] == 'dev-badge':
                row['output'] = ('{"owner":"Mira","badge":17}' if row['variant'] == 'unchanged'
                                 else '{"owner":"Wrong","badge":17}')
        self.assertEqual(freeze_selection(self.spec, rows)['selected_weight'], 'unchanged')

    def test_large_synthetic_gain_has_only_a_narrow_fixture_verdict(self):
        # Branch coverage on invented outputs is NOT a measured Qwen result.
        for row in self.heldout:
            if row['variant'] == 'unchanged' and row['case_id'] not in {
                    c['id'] for c in cases('heldout') if c['task'] == 'regression'}:
                row['output'] = 'not json'
        report = evaluate(self.spec, self.freeze, self.dev + self.heldout)
        self.assertEqual(report['verdict'], 'improved_on_public_fixture')
        self.assertEqual(report['comparisons']['weight-0']['schema_difference'], 1)
        self.assertIn('no private test', report['limitations'])
        for arm in report['heldout'].values():
            for field in ('schema_interval', 'semantic_interval', 'regression_interval'):
                self.assertTrue(0 <= arm[field][0] <= arm[field][1] <= 1)

    def test_all_attempts_retained_but_incomplete_arms_never_improve(self):
        for mutation in ('missing', 'failed', 'budget_limited', 'cancelled', 'incomplete', 'duplicate'):
            heldout = copy.deepcopy(self.heldout)
            if mutation == 'missing':
                heldout.pop()
            elif mutation == 'duplicate':
                heldout.append(dict(heldout[0], attempt_id='retry'))
            else:
                heldout[0]['status'] = mutation
            source = self.dev + heldout
            report = evaluate(self.spec, self.freeze, source)
            self.assertEqual(report['verdict'], 'not_evaluated', mutation)
            self.assertEqual(report['status'], 'incomplete')
            self.assertEqual(report['records'], source)
            self.assertEqual(report['attempt_count'], len(source))
            self.assertTrue(all(c['verdict'] == 'not_evaluated' for c in report['comparisons'].values()))

    def test_freeze_binding_ordering_and_unselected_heldout_guard(self):
        for field in ('selected_weight', 'dev_records_sha256', 'spec_sha256', 'sha256'):
            freeze = copy.deepcopy(self.freeze)
            freeze[field] = 'tampered'
            with self.assertRaises(ValueError):
                evaluate(self.spec, freeze, self.dev + self.heldout)
        with self.assertRaises(ValueError):
            evaluate(self.spec, self.freeze, self.heldout + self.dev)
        changed = copy.deepcopy(self.dev)
        changed[0]['output'] = '{}'
        with self.assertRaises(ValueError):
            evaluate(self.spec, self.freeze, changed + self.heldout)
        extra = records(self.spec, 'heldout', ['weight-1'])
        report = evaluate(self.spec, self.freeze, self.dev + self.heldout + extra)
        self.assertIn('unfrozen_heldout_variant', report['accounting_issues'])
        self.assertEqual(report['verdict'], 'not_evaluated')

    def test_envelope_errors_are_rejected_and_usage_is_not_assumed(self):
        for field, value in [('case_id', 'unknown'), ('variant', 'other'), ('spec_sha256', 'b' * 64),
                             ('status', 'eos'), ('output_tokens', True), ('input_tokens', -1),
                             ('elapsed_seconds', float('nan')), ('elapsed_seconds', -1),
                             ('input_tokens', None), ('output', {})]:
            row = dict(self.dev[0], **{field: value})
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_record(row, self.spec)
        with self.assertRaises(ValueError):
            validate_record(dict(self.dev[0], score=1), self.spec)
        limited = dict(self.heldout[0], status='failed', input_tokens=None)
        rows = self.dev + [limited] + self.heldout[1:]
        report = evaluate(self.spec, self.freeze, rows)
        self.assertIn('unknown_usage', report['accounting_issues'])
        self.assertEqual(report['verdict'], 'not_evaluated')

    def test_budgets_and_duplicate_ids_block_completion(self):
        for field, value in [('output_tokens', 97), ('input_tokens', 513), ('elapsed_seconds', 61),
                             ('attempt_id', self.dev[0]['attempt_id'])]:
            heldout = copy.deepcopy(self.heldout)
            heldout[0][field] = value
            report = evaluate(self.spec, self.freeze, self.dev + heldout)
            self.assertEqual(report['verdict'], 'not_evaluated')
            self.assertTrue(report['accounting_issues'])
        rows = copy.deepcopy(self.dev)
        for row in rows:
            row['elapsed_seconds'] = 30
        self.assertIn('worker_budget', freeze_selection(self.spec, rows)['accounting_issues'])

    def test_no_selection_reports_original_without_fake_weight_arm(self):
        dev = records(self.spec, 'dev', VARIANTS)
        freeze = freeze_selection(self.spec, dev)
        heldout = records(self.spec, 'heldout', freeze['heldout_variants'])
        report = evaluate(self.spec, freeze, dev + heldout)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['verdict'], 'no_improvement')
        self.assertNotIn('weight-0', report['heldout'])


if __name__ == '__main__':
    unittest.main()
