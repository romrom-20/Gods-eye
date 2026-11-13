"""Offline contract tests; no optional packages, model loading or network."""
import copy
import unittest
from dataclasses import FrozenInstanceError

from godseye.lm.task_contract import (
    MODEL_ID, PHRASES, TaskSpec, canonical, digest, matches_schema,
    preview, strict_json, validate_schema,
)

REVISION = 'a' * 40  # Synthetic identity, never a claim this Hub commit exists.


def spec():
    return TaskSpec(canonical(preview(PHRASES[0], revision=REVISION)['spec']))


class ContractTests(unittest.TestCase):
    def test_deterministic_phrases_and_immutable_preview(self):
        result = preview('  IMPROVE   JSON schema adherence. ', revision=REVISION)
        self.assertEqual(result['outcome'], 'ready')
        first = spec()
        self.assertEqual(result['spec_sha256'], first.sha256)
        for phrase in PHRASES:
            self.assertEqual(preview(phrase, revision=REVISION)['spec_sha256'], first.sha256)
        view = first.to_dict()
        view['budgets']['max_attempts'] = 0
        self.assertEqual(first.to_dict()['budgets']['max_attempts'], 126)
        with self.assertRaises(FrozenInstanceError):
            first._json = '{}'
        self.assertNotIn('experiment_id', result)

    def test_unsupported_and_ambiguous_text_produces_no_spec(self):
        for text, outcome in [('make it smarter', 'unsupported'),
                              ('edit Qwen weights', 'unsupported'),
                              ('make JSON better', 'clarification_required'),
                              ('improve json schema adherence; exec(open("/tmp/key").read())',
                               'clarification_required'),
                              ('download https://example.org/model', 'unsupported')]:
            result = preview(text, revision=REVISION)
            self.assertEqual(result['outcome'], outcome)
            self.assertIsNone(result['spec'])
            self.assertIsNone(result['spec_sha256'])
        for text in ('', 'x' * 2001, None):
            with self.assertRaises(ValueError):
                preview(text, revision=REVISION)

    def test_model_and_revision_are_explicit_and_fail_closed(self):
        for revision in ('main', 'latest', '', 'a' * 39, 'A' * 40, True, None):
            with self.assertRaises(ValueError):
                preview(PHRASES[0], revision=revision)
        with self.assertRaises(ValueError):
            preview(PHRASES[0], revision=REVISION, model_id='Qwen/Qwen3.5-0.8B')
        self.assertEqual(spec().to_dict()['model']['id'], MODEL_ID)
        self.assertNotEqual(spec().sha256, preview(PHRASES[0], revision='b' * 40)['spec_sha256'])

    def test_fixed_recipe_rejects_modified_metrics_splits_budgets_and_edits(self):
        for field in ('version', 'goal', 'dataset', 'metrics', 'operations', 'baselines',
                      'generation', 'budgets', 'split_policy'):
            value = spec().to_dict()
            value[field] = None
            with self.assertRaises(ValueError):
                TaskSpec(canonical(value))
        value = spec().to_dict()
        value['extra'] = True
        with self.assertRaises(ValueError):
            TaskSpec(canonical(value))
        self.assertEqual(digest(spec().to_dict()), spec().sha256)

    def test_behavior_requests_get_relevant_guidance_without_a_substitute_plan(self):
        for text, explanation in [
            ('Make Qwen better at math problems', 'mathematical correctness'),
            ('Improve JSON for algebra equations', 'mathematical correctness'),
            ('Update the policy when driving the car', 'simulator'),
            ('Improve JSON car steering decisions', 'simulator'),
            ('Change its biology knowledge', 'outside the fixed JSON benchmark'),
        ]:
            with self.subTest(text=text):
                result = preview(text, revision=REVISION)
                self.assertNotEqual(result['outcome'], 'ready')
                self.assertIsNone(result['spec'])
                self.assertIsNone(result['spec_sha256'])
                self.assertIn(explanation, result['message'])
                self.assertIn('No experiment started', result['message'])

    def test_strict_json_adversaries(self):
        for raw in ('```json\n{}\n```', 'Here: {}', '{} {}', '{"x":1,"x":2}',
                    '{"x":{"a":1,"a":2}}', '{"x":NaN}', '{"x":Infinity}',
                    '{"x":-Infinity}', '{"x":1e999}', '[0,]', '\ufeff{}',
                    '[' * 30 + '0' + ']' * 30, ' ' * 16385, '\ud800'):
            with self.subTest(raw=raw[:80]), self.assertRaises(ValueError):
                strict_json(raw)
        self.assertEqual(strict_json(' \n {"x": 2} \t'), {'x': 2})

    def test_bounded_schema_is_a_closed_dialect(self):
        schema = {'type': 'object', 'properties': {'n': {'type': 'integer', 'minimum': -2,
                                                       'maximum': 2}},
                  'required': ['n'], 'additionalProperties': False}
        self.assertTrue(matches_schema({'n': 2}, schema))
        for value in ({'n': True}, {'n': 2.0}, {'n': 3}, {'n': '2'}, {}, {'n': 1, 'x': 0}):
            self.assertFalse(matches_schema(value, schema))
        for mutate in (lambda s: s.update(additionalProperties=True),
                       lambda s: s.update(required=[]), lambda s: s.update(description='ignored'),
                       lambda s: s['properties']['n'].update(minimum=False)):
            bad = copy.deepcopy(schema)
            mutate(bad)
            with self.assertRaises(ValueError):
                validate_schema(bad)
        for bad in ({'type': 'array'}, {'type': 'number'}, {'$ref': 'file:///tmp/key'},
                    {'type': 'string', 'maxLength': 100000},
                    {'type': 'string', 'maxLength': 2, 'enum': ['long']}):
            with self.assertRaises(ValueError):
                validate_schema(bad)


if __name__ == '__main__':
    unittest.main()
