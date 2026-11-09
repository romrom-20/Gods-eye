"""Tensor edits and actual MinAtar rollouts. No training or optimizer code."""
import ast
import hashlib
import json
import math
from pathlib import Path
import time
import uuid

import numpy as np
from minatar import Environment

ROOT = Path(__file__).resolve().parent.parent
NAMES = {
    'W1': ('actor/dense1/kernel', (600, 32)),
    'b1': ('actor/dense1/bias', (32,)),
    'W2': ('actor/dense2/kernel', (32, 32)),
    'b2': ('actor/dense2/bias', (32,)),
    'W3': ('actor/logits/kernel', (32, 6)),
    'b3': ('actor/logits/bias', (6,)),
}
ACTIONS = ['no-op', 'left', 'up', 'right', 'down', 'fire']


def load_weights(path):
    with np.load(path, allow_pickle=False) as source:
        result = {name: np.array(source[key], dtype=np.float32)
                  for name, (key, _) in NAMES.items()}
    for name, (_, shape) in NAMES.items():
        if result[name].shape != shape or not np.isfinite(result[name]).all():
            raise ValueError('Invalid tensor: ' + name)
    return result


def save_weights(path, weights):
    np.savez_compressed(path, **{NAMES[n][0]: v for n, v in weights.items()})


def digest(weights):
    h = hashlib.sha256()
    for name in NAMES:
        h.update(name.encode())
        h.update(weights[name].astype('<f4').tobytes())
    return h.hexdigest()


def tensor_summary(weights):
    return [{'name': name, 'shape': list(v.shape), 'parameters': int(v.size),
             'nonzero': int(np.count_nonzero(v)), 'min': float(v.min()),
             'max': float(v.max()), 'norm': float(np.linalg.norm(v.astype(float)))}
            for name, v in weights.items()]


def difference(before, after):
    result = []
    for name in NAMES:
        a, b = before[name], after[name]
        changed = int(np.count_nonzero(a != b))
        if changed:
            result.append({'tensor': name, 'changed': changed,
                           'total': int(a.size),
                           'max_delta': float(np.max(np.abs(b.astype(float) - a)))})
    return result


def _index(node):
    if isinstance(node, ast.Tuple):
        return tuple(_index(n) for n in node.elts)
    if isinstance(node, ast.Slice):
        return slice(*[None if n is None else _index(n)
                       for n in (node.lower, node.upper, node.step)])
    value = ast.literal_eval(node)
    if type(value) is not int:
        raise ValueError('Indices must be integers or slices')
    return value


def apply_patch(weights, code):
    """Parse a tiny numeric assignment language; never eval or execute code.

    All statements succeed on a copy, or nothing is written. Calls, attributes,
    loops, expressions on the RHS, and implicit broadcasting of lists are rejected.
    """
    if not isinstance(code, str) or not code.strip() or len(code) > 50000:
        raise ValueError('Provide 1–50,000 characters of tensor assignments')
    tree = ast.parse(code)
    if len(tree.body) > 200:
        raise ValueError('At most 200 assignments per patch')
    edited = {n: v.copy() for n, v in weights.items()}
    for statement in tree.body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, op = statement.targets[0], None
        elif isinstance(statement, ast.AugAssign) and isinstance(statement.op, (ast.Add, ast.Sub, ast.Mult)):
            target, op = statement.target, statement.op
        else:
            raise ValueError('Only assignments and +=, -=, *= are supported')
        if not isinstance(target, ast.Subscript) or not isinstance(target.value, ast.Name):
            raise ValueError('Assign to a named tensor slice, e.g. W3[0:8:2, 1] = 30')
        name = target.value.id
        if name not in edited:
            raise ValueError('Unknown tensor: ' + name)
        index = _index(target.slice)
        raw = ast.literal_eval(statement.value)
        values = np.asarray(raw)
        if values.dtype.kind not in 'iuf':
            raise ValueError('Values must be numeric')
        values = values.astype(np.float64)
        if not np.isfinite(values).all() or np.any(np.abs(values) > 1e6):
            raise ValueError('Values must be finite numbers with absolute value <= 1e6')
        current = edited[name][index]
        if np.size(current) == 0:
            raise ValueError('Slice is empty')
        if values.ndim and values.shape != np.shape(current):
            raise ValueError('List shape must match the selected tensor slice')
        if isinstance(op, ast.Add):
            values = current.astype(float) + values
        elif isinstance(op, ast.Sub):
            values = current.astype(float) - values
        elif isinstance(op, ast.Mult):
            values = current.astype(float) * values
        if not np.isfinite(values).all() or np.any(np.abs(values) > 1e6):
            raise ValueError('Edited values exceed the finite ±1e6 bound')
        edited[name][index] = values
    if not difference(weights, edited):
        raise ValueError('Patch does not change any weights')
    return edited


def observation(state):
    # Official Breakout channels -> the six channels in the paper's prompt.
    x = np.zeros((10, 10, 6), dtype=np.float32)
    x[:, :, 0] = state[:, :, 0]  # paddle
    x[:, :, 2] = state[:, :, 3]  # bricks
    x[:, :, 3] = state[:, :, 1]  # ball
    x[:, :, 4] = state[:, :, 2]  # previous ball position
    return x.ravel()


def forward(weights, x):
    # Binary input: sum active rows, equivalent to x @ W1. Avoid dense BLAS overhead.
    h1 = np.tanh(weights['W1'][np.flatnonzero(x)].sum(axis=0) + weights['b1'])
    h2 = np.tanh(h1 @ weights['W2'] + weights['b2'])
    logits = h2 @ weights['W3'] + weights['b3']
    p = np.exp((logits - logits.max()).astype(np.float64))
    return p / p.sum(), h1, h2


def episode(weights, seed, max_steps, record=False):
    env = Environment('breakout', sticky_action_prob=0.1)
    env.seed(seed)
    env.reset()
    # Separate environment and policy randomness; same seeds reused for both models.
    rng = np.random.RandomState(seed ^ 0x5EED)
    score, trace, done = 0, [], False
    for step in range(max_steps):
        state = env.state()
        p, h1, _ = forward(weights, observation(state))
        action = int(rng.choice(6, p=p))
        if record:
            # Capture every frame so replay does not hide missed actions.
            trace.append({'step': step, 'score': score, 'action': action,
                          'cells': [np.argwhere(state[:, :, i]).tolist() for i in range(4)],
                          'probabilities': p.tolist(), 'h1': h1[:6].tolist()})
        reward, done = env.act(action)
        score += float(reward)
        if done:
            break
    return {'seed': seed, 'score': score, 'steps': step + 1,
            'truncated': not bool(done), 'trace': trace}


def compare(base, candidate, episodes=8, seed=1000, max_steps=3000):
    if type(episodes) is not int or not 1 <= episodes <= 64:
        raise ValueError('Episodes must be an integer from 1 to 64')
    if type(seed) is not int or not 0 <= seed <= 2**32 - 65:
        raise ValueError('Seed must be an integer in [0, 2**32 - 65]')
    if type(max_steps) is not int or not 1 <= max_steps <= 10000:
        raise ValueError('Max steps must be an integer from 1 to 10,000')
    start = time.monotonic()
    models = []
    for weights in (base, candidate):
        rows = [episode(weights, seed + i, max_steps, record=(i == 0)) for i in range(episodes)]
        scores = np.array([r['score'] for r in rows])
        models.append({'mean': float(scores.mean()),
                       'se': float(scores.std(ddof=1) / math.sqrt(episodes)) if episodes > 1 else None,
                       'episodes': [{k: v for k, v in r.items() if k != 'trace'} for r in rows],
                       'trace': rows[0]['trace'],
                       'forward_calls': sum(r['steps'] for r in rows)})
    delta = np.array([b['score'] - a['score'] for a, b in zip(models[0]['episodes'], models[1]['episodes'])])
    return {'base': models[0], 'candidate': models[1], 'paired_mean_delta': float(delta.mean()),
            'paired_se': float(delta.std(ddof=1) / math.sqrt(episodes)) if episodes > 1 else None,
            'episodes': episodes, 'seed': seed, 'max_steps': max_steps,
            'sticky_actions': 0.1, 'sampling': 'softmax', 'seconds': time.monotonic() - start,
            'environment': 'MinAtar 1.0.15 Breakout', 'numpy': np.__version__}


class Store:
    def __init__(self, path=None):
        self.path = Path(path or ROOT / '.godseye')
        self.path.mkdir(parents=True, exist_ok=True)
        self.paper = load_weights(ROOT / 'fixtures/breakout/paper.npz')

    def weights(self, model_id):
        if model_id == 'paper':
            return {n: v.copy() for n, v in self.paper.items()}
        if model_id == 'zero':
            return {n: np.zeros_like(v) for n, v in self.paper.items()}
        if len(model_id) != 16 or any(c not in '0123456789abcdef' for c in model_id):
            raise ValueError('Invalid checkpoint id')
        return load_weights(self.path / (model_id + '.npz'))

    def checkpoints(self):
        rows = [{'id': 'paper', 'name': 'Paper · authored network', 'parent': None},
                {'id': 'zero', 'name': 'Zero initialization', 'parent': None}]
        rows += sorted([json.loads(p.read_text()) for p in self.path.glob('checkpoint-*.json')],
                       key=lambda r: r['created'])
        return rows

    def patch(self, base_id, code, hypothesis):
        if not isinstance(hypothesis, str) or not hypothesis.strip() or len(hypothesis) > 4000:
            raise ValueError('Write a hypothesis (1–4,000 characters)')
        base = self.weights(base_id)
        edited = apply_patch(base, code)
        model_id = uuid.uuid4().hex[:16]
        report = {'id': model_id, 'name': hypothesis[:70], 'parent': base_id,
                  'hypothesis': hypothesis, 'patch': code, 'diff': difference(base, edited),
                  'sha256': digest(edited), 'parent_sha256': digest(base), 'created': time.time()}
        save_weights(self.path / (model_id + '.npz'), edited)
        (self.path / ('checkpoint-' + model_id + '.json')).write_text(json.dumps(report, indent=2))
        return report

    def run(self, base_id, candidate_id, **kwargs):
        base, candidate = self.weights(base_id), self.weights(candidate_id)
        result = compare(base, candidate, **kwargs)
        result.update({'id': uuid.uuid4().hex[:16], 'base_id': base_id,
                       'candidate_id': candidate_id, 'base_sha256': digest(base),
                       'candidate_sha256': digest(candidate), 'created': time.time()})
        (self.path / ('run-' + result['id'] + '.json')).write_text(json.dumps(result))
        return result
