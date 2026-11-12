"""Synthetic mechanism tests; never represented as pretrained quality evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from godseye.lm import local_delta as d
from godseye.lm import local_runtime as r

HAS_TORCH = importlib.util.find_spec('torch') is not None


class PlanningTests(unittest.TestCase):
    def test_stdlib_dry_run(self):
        code = """
import socket, sys
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network'))
from experiments.local_lm import main
main()
assert 'torch' not in sys.modules and 'transformers' not in sys.modules
"""
        result = subprocess.run([sys.executable, '-S', '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['revision'], r.REVISION)

    def test_execution_opt_in(self):
        result = subprocess.run([sys.executable, '-S', '-m', 'experiments.local_lm',
                                 '--download', '/unused'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('require --execute', result.stderr)

    def test_accounting_reasons(self):
        self.assertEqual(r.termination([1], [1], 1, 2, 1),
                         dict(termination='eos', deadline_exceeded=True))
        self.assertEqual(r.termination([2], [1], 1, .1, 1)['termination'], 'token_cap')
        self.assertEqual(r.termination([], [1], 4, 2, 1)['termination'], 'walltime')


@unittest.skipUnless(HAS_TORCH, 'optional Torch not installed')
class NumericTests(unittest.TestCase):
    def setUp(self):
        import torch
        torch.set_num_threads(2)
        torch.manual_seed(17)
        p = torch.nn.Parameter(torch.randn(*d.SHAPE))
        self.model = SimpleNamespace(model=SimpleNamespace(layers=[SimpleNamespace(
            mlp=SimpleNamespace(down_proj=SimpleNamespace(weight=p)))]))
        self.p = p
        self.a = d.make_delta(self.model)

    def signed(self, a):
        a['content_sha256'] = d.digest({k: v for k, v in a.items() if k != 'content_sha256'})
        return a

    def test_exact_rollback_exception_and_reload(self):
        base = d.tensor_hash(self.p)
        with self.assertRaisesRegex(RuntimeError, 'probe'):
            with d.applied(self.model, self.a):
                self.assertEqual(d.tensor_hash(self.p), self.a['edited_tensor_sha256'])
                raise RuntimeError('probe')
        self.assertEqual(d.tensor_hash(self.p), base)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'delta.json'
            d.save_delta(path, self.a)
            with d.applied(self.model, d.load_delta(path)):
                pass
        self.assertEqual(d.tensor_hash(self.p), base)

    def test_tamper_and_precondition(self):
        bad = copy.deepcopy(self.a)
        bad['after'][0] = 123.0
        with self.assertRaises(ValueError):
            d.validate(bad)
        import torch
        with torch.no_grad():
            self.p[0, 2] += 1
        with self.assertRaisesRegex(ValueError, 'base tensor'):
            with d.applied(self.model, self.a):
                self.fail('invalid base accepted')

    def test_nonfinite_shape_path_precision(self):
        for key, value in [('shape', [1, 2]), ('parameter', '__dict__'),
                           ('column', True), ('scale', True)]:
            bad = copy.deepcopy(self.a)
            bad[key] = value
            with self.assertRaises(ValueError):
                d.validate(self.signed(bad))
        for value in [float('nan'), float('inf'), 1e100, 0.1]:
            bad = copy.deepcopy(self.a)
            bad['before'][0] = value
            with self.assertRaises(ValueError):
                d.validate(bad)
        import torch
        with torch.no_grad():
            self.p[0, 0] = float('nan')
        with self.assertRaisesRegex(ValueError, 'nonfinite'):
            d.make_delta(self.model)

    def test_signed_zero_precondition(self):
        import torch
        with torch.no_grad():
            self.p[0, 0] = -0.0
        a = d.make_delta(self.model)
        a['before'][0] = 0.0
        a['after'][0] = 0.0
        self.signed(a)
        base = d.tensor_hash(self.p)
        with self.assertRaisesRegex(ValueError, 'column precondition'):
            with d.applied(self.model, a):
                self.fail('signed zero tamper accepted')
        self.assertEqual(d.tensor_hash(self.p), base)

    def test_wrong_edited_hash_rolls_back(self):
        bad = copy.deepcopy(self.a)
        bad['edited_tensor_sha256'] = '0' * 64
        base = d.tensor_hash(self.p)
        with self.assertRaisesRegex(ValueError, 'edited tensor'):
            with d.applied(self.model, self.signed(bad)):
                self.fail('wrong edited hash accepted')
        self.assertEqual(d.tensor_hash(self.p), base)

    def test_loader_duplicate_and_bound(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'bad.json'
            p.write_text('{"format":1,"format":2}')
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                d.load_delta(p)
            p.write_text(' ' * 100001)
            with self.assertRaises(ValueError):
                d.load_delta(p)
        import torch
        self.model.model.layers[0].mlp.down_proj.weight = torch.zeros(1, 2)
        with self.assertRaises(ValueError):
            d.target(self.model)

    def test_generation_limits_accounting_and_failure_reservation(self):
        import torch
        from transformers import BatchEncoding
        runtime = r.Runtime.__new__(r.Runtime)
        class Tokenizer:
            def apply_chat_template(self, *a, **k):
                return 'rendered'
            def __call__(self, *a, **k):
                return BatchEncoding({'input_ids': torch.tensor([[3, 4]]),
                                      'attention_mask': torch.tensor([[1, 1]])})
            def decode(self, tokens, **kwargs):
                return '5'
        runtime.tokenizer = Tokenizer()
        runtime.model = SimpleNamespace(generate=lambda **kwargs: torch.tensor([[3, 4, 9, 151645]]))
        with patch.object(r, '_generations', 0):
            out = runtime.generate('x', max_new_tokens=4, seconds=1)
            self.assertEqual(out['generated_tokens'], 2)
            self.assertEqual(out['input_tokens'], 2)
            self.assertEqual(out['termination'], 'eos')
            self.assertGreaterEqual(out['latency_seconds'], 0)
            for kwargs in [{'prompt': 'x' * 513}, {'prompt': 'x', 'seconds': float('nan')},
                           {'prompt': 'x', 'max_new_tokens': 33}]:
                with self.assertRaises(ValueError):
                    runtime.generate(**kwargs)
            def fail(**kwargs):
                raise RuntimeError('native failure')
            runtime.model.generate = fail
            with self.assertRaisesRegex(RuntimeError, 'native failure'):
                runtime.generate('x')
            self.assertEqual(r._generations, 2)
        def timed(**kwargs):
            criterion = kwargs['stopping_criteria'][0]
            self.assertTrue(criterion(torch.tensor([[3, 4, 9]]), None))
            return torch.tensor([[3, 4, 9]])
        runtime.model.generate = timed
        with patch.object(r, '_generations', 0), patch.object(r.time, 'monotonic',
                                                            side_effect=[0, 0, 2, 2]):
            out = runtime.generate('x', max_new_tokens=4, seconds=1)
        self.assertEqual(out['termination'], 'walltime')
        self.assertTrue(out['deadline_exceeded'])
        self.assertEqual(out['generated_tokens'], 1)
        with patch.object(r, '_generations', 8):
            with self.assertRaisesRegex(RuntimeError, 'budget'):
                runtime.generate('x')


if __name__ == '__main__':
    unittest.main()
