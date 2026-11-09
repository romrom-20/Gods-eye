import tempfile
import unittest

import numpy as np

from godseye.core import (ROOT, Store, apply_patch, compare, digest, difference,
                          forward, load_weights, observation)


class WeightSpaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.weights = load_weights(ROOT / 'fixtures/breakout/paper.npz')

    def test_released_fixture_contract(self):
        self.assertEqual(sum(v.size for v in self.weights.values()), 20486)
        self.assertEqual(sum(np.count_nonzero(v) for v in self.weights.values()), 815)
        self.assertEqual(digest(self.weights), '38c50a4f4d7185697176687792834d50970e239f452b764ccd1ec6d8439db128')

    def test_sparse_forward_matches_dense_equations(self):
        rng = np.random.RandomState(54)
        x = (rng.rand(600) < .15).astype(np.float32)
        w = self.weights
        # Independent dense arithmetic in float64; avoids Accelerate BLAS flags
        # on this platform and checks the sparse implementation against all rows.
        h1 = np.tanh((x[:, None] * w['W1'].astype(float)).sum(axis=0) + w['b1'])
        h2 = np.tanh((h1[:, None] * w['W2']).sum(axis=0) + w['b2'])
        logits = (h2[:, None] * w['W3']).sum(axis=0) + w['b3']
        expected = np.exp((logits-logits.max()).astype(float))
        expected /= expected.sum()
        actual, actual_h1, _ = forward(w, x)
        np.testing.assert_allclose(actual, expected, atol=1e-6)
        np.testing.assert_allclose(actual_h1, h1, atol=1e-6)

    def test_observation_contract_preserves_each_channel(self):
        state = np.zeros((10,10,4), dtype=bool)
        for i in range(4): state[i, i+1, i] = True
        x = observation(state).reshape(10,10,6)
        for official, unified in [(0,0),(1,3),(2,4),(3,2)]:
            np.testing.assert_array_equal(state[:,:,official], x[:,:,unified])
        self.assertFalse(x[:,:,1].any())
        self.assertFalse(x[:,:,5].any())

    def test_patch_is_transactional_and_restorable(self):
        original_hash = digest(self.weights)
        ablated = apply_patch(self.weights, 'W3[0:8:2, 1] = 0')
        self.assertEqual(difference(self.weights, ablated)[0]['changed'], 4)
        restored = apply_patch(ablated, 'W3[0:8:2, 1] = 30')
        self.assertEqual(digest(restored), original_hash)
        with self.assertRaises(ValueError):
            apply_patch(self.weights, 'b3[0] = 1\nW3[:, 1] = [1, 2]')
        self.assertEqual(digest(self.weights), original_hash)

    def test_patch_rejects_execution_nonfinite_and_empty_edits(self):
        for code in ["__import__('os').system('id')", 'W3[0,0] = float(1)',
                     'b3[0] = 1e309', 'b3[0] = -9223372036854775808', 'W3[:,1] *= 1000000',
                     'b3[0:0] = 1', 'b3[0] = True', 'W3[0,0] = 0']:
            with self.subTest(code=code), self.assertRaises((ValueError, SyntaxError)):
                apply_patch(self.weights, code)

    def test_paired_identical_checkpoints_match_every_episode(self):
        run = compare(self.weights, self.weights, episodes=2, seed=830, max_steps=180)
        self.assertEqual(run['paired_mean_delta'], 0)
        self.assertEqual(run['paired_se'], 0)
        self.assertEqual(run['base']['episodes'], run['candidate']['episodes'])
        self.assertEqual(run['base']['trace'], run['candidate']['trace'])
        self.assertEqual(run['base']['forward_calls'], sum(e['steps'] for e in run['base']['episodes']))

    def test_checkpoint_roundtrip_retains_lineage(self):
        with tempfile.TemporaryDirectory() as path:
            store = Store(path)
            report = store.patch('paper', 'W3[0:8:2, 1] = 0', 'Ablate left-action circuit')
            self.assertEqual(digest(store.weights(report['id'])), report['sha256'])
            self.assertEqual(report['parent_sha256'], digest(store.weights('paper')))
            self.assertEqual(len(Store(path).checkpoints()), 3)

    def test_evaluation_bounds(self):
        for kwargs in [dict(episodes=0),dict(episodes=1.5),dict(seed=-1),dict(max_steps=0)]:
            with self.assertRaises(ValueError): compare(self.weights, self.weights, **kwargs)


if __name__ == '__main__':
    unittest.main()
