import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from godseye.benchmark import RepairBenchmark


class RepairBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bench = RepairBenchmark(self.temp.name)
        self.cases = self.bench.create(probes=2, forward_budget=10, episodes=1, max_steps=10)

    def test_budget_persists_after_failure_and_reload(self):
        case = self.cases[0]
        with patch.object(self.bench, '_evaluate', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.bench.probe(case['id'], case['root_id'])
        reloaded = RepairBenchmark(self.temp.name)
        with self.assertRaisesRegex(ValueError, 'budget'):
            reloaded.probe(case['id'], case['root_id'])
        private = json.loads(self.bench.state_path.read_text())
        self.assertEqual(private['cases'][0]['attempts'][0]['status'], 'failed')
        self.assertEqual(reloaded.cases()[0]['forward_reserved'], 10)

    def test_no_private_labels_or_seeds_before_report_and_control_integrity(self):
        case = self.cases[0]
        public = [self.cases, self.bench.inspect(case['id'], 'W3'),
                  self.bench.probe(case['id'], case['root_id'])]
        serialized = json.dumps(public)
        for name in ('family', 'dev_seed', 'held_seed', 'reference_id', '"seed"'):
            self.assertNotIn(name, serialized)
        with self.assertRaises(ValueError):
            self.bench.report()
        for case in self.cases:
            result = self.bench.finalize(case['id'], case['root_id'])
            self.assertNotIn('mean_score', json.dumps(result))
            with self.assertRaises(ValueError):
                self.bench.probe(case['id'], case['root_id'])
            with self.assertRaises(ValueError):
                self.bench.finalize(case['id'], case['root_id'])
        report = self.bench.report()
        self.assertEqual({r['family'] for r in report['cases']},
                         {'control', 'sign_flip', 'channel_ablation', 'bias_shift'})
        for row in report['cases']:
            self.assertEqual(row['final']['delta_from_corrupted'], 0)
            if row['family'] == 'control':
                self.assertEqual(row['final']['reference'], row['final']['selected'])
        private = json.loads(self.bench.state_path.read_text())
        for case in private['cases']:
            self.assertNotEqual(case['dev_seed'], case['held_seed'])

    def test_case_ownership_and_immutable_lineage(self):
        case, other = self.cases[:2]
        before = self.bench.inspect(case['id'], 'b3')
        candidate = self.bench.patch(case['id'], case['root_id'], 'b3[0] += 1', 'Probe bias')
        self.assertEqual(candidate['patch'], 'b3[0] += 1')
        self.assertNotEqual(candidate['sha256'], candidate['parent_sha256'])
        self.assertEqual(before, self.bench.inspect(case['id'], 'b3'))
        with self.assertRaises(ValueError):
            self.bench.inspect(other['id'], 'b3', candidate['id'])
        with self.assertRaises(ValueError):
            self.bench.inspect(case['id'], 'b3', '../../private-state')

    def test_final_failure_still_freezes_and_reserves(self):
        case = self.cases[0]
        with patch.object(self.bench, '_evaluate', side_effect=RuntimeError('failed')):
            with self.assertRaises(RuntimeError):
                self.bench.finalize(case['id'], case['root_id'])
        with self.assertRaises(ValueError):
            self.bench.patch(case['id'], case['root_id'], 'b3[0] += 1', 'Retry')
        state = json.loads(self.bench.state_path.read_text())
        self.assertEqual(state['cases'][0]['final']['forward_reserved'], 30)
        self.assertEqual(state['cases'][0]['final']['status'], 'failed')

    def test_crash_reservation_is_not_refunded(self):
        state = json.loads(self.bench.state_path.read_text())
        case = state['cases'][0]
        case['attempts'].append(dict(status='reserved', reserved=10, candidate_id=case['root_id']))
        case['forward_reserved'] = 10
        self.bench.state_path.write_text(json.dumps(state))
        self.assertEqual(RepairBenchmark(self.temp.name).cases()[0]['forward_reserved'], 10)
        recovered = json.loads(self.bench.state_path.read_text())
        self.assertEqual(recovered['cases'][0]['attempts'][0]['status'], 'interrupted')

    def test_probe_count_limit_independent_of_forward_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            bench = RepairBenchmark(directory)
            case = bench.create(probes=1, forward_budget=100, episodes=1, max_steps=10)[0]
            bench.probe(case['id'], case['root_id'])
            with self.assertRaisesRegex(ValueError, 'Probe limit'):
                bench.probe(case['id'], case['root_id'])

    def test_creation_rejects_existing_data_and_invalid_settings(self):
        with self.assertRaises(ValueError):
            self.bench.create()
        with tempfile.TemporaryDirectory() as directory:
            bench = RepairBenchmark(directory)
            with self.assertRaises(ValueError):
                bench.create(episodes=True)
            (Path(directory) / 'keep.txt').write_text('keep')
            with self.assertRaises(ValueError):
                bench.create()
