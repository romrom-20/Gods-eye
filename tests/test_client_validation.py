"""Regression checks for the independent HTTP acceptance evidence."""
from copy import deepcopy
import unittest

from experiments.validate_client import compact_run


class ClientEvidenceTests(unittest.TestCase):
    def run_record(self):
        side = {'mean': 7, 'episodes': [{'seed': 10000, 'score': 7, 'steps': 80}],
                'trace': [{'step': 0, 'action': 1, 'score': 0}]}
        return {'base': deepcopy(side), 'candidate': deepcopy(side)}

    def test_replay_difference_fails_despite_identical_episode_metadata(self):
        run = self.run_record()
        run['candidate']['trace'][0]['action'] = 2
        with self.assertRaisesRegex(AssertionError, 'Recorded replays differ'):
            compact_run(run, require_identical=True)

    def test_matching_replay_is_verified_before_compaction(self):
        run = self.run_record()
        compact, verified = compact_run(run, require_identical=True)
        self.assertTrue(verified)
        self.assertNotIn('trace', compact['base'])
        self.assertEqual(compact['base'], compact['candidate'])
        self.assertTrue(run['base']['trace'])

    def test_missing_replay_cannot_count_as_verified(self):
        run = self.run_record()
        run['base']['trace'] = run['candidate']['trace'] = []
        with self.assertRaisesRegex(AssertionError, 'Missing replay evidence'):
            compact_run(run, require_identical=True)
