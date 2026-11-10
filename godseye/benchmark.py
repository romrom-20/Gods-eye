"""Local, protocol-blinded repair benchmark; not a security sandbox.

The same OS user can read private state and the shipped reference fixture. Results
measure this bounded Breakout protocol, not novel or independently blinded repair.
"""
from contextlib import contextmanager
import copy
import fcntl
import json
import math
from pathlib import Path
import uuid

import numpy as np

from .backends import BreakoutBackend
from .core import apply_patch, difference, digest, episode, load_weights, save_weights
from .storage import write_json


class RepairBenchmark:
    def __init__(self, path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.state_path = self.path / 'private-state.json'

    @contextmanager
    def _locked(self):
        with (self.path / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _read(self):
        if not self.state_path.exists():
            raise ValueError('Create a benchmark first')
        state = json.loads(self.state_path.read_text())
        recovered = False
        for case in state['cases']:
            for record in case['attempts'] + ([case['final']] if case['final'] else []):
                if record['status'] == 'reserved':
                    record['status'] = 'interrupted'
                    recovered = True
        if recovered:
            self._save(state)
        return state

    def _save(self, state):
        write_json(self.state_path, state)

    @staticmethod
    def _integer(value, low, high, name):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{name} must be an integer in [{low}, {high}]')

    def create(self, *, seed=7, probes=4, forward_budget=8000, episodes=2, max_steps=200, instances=1):
        for value, low, high, name in ((seed, 0, 2**31 - 1, 'seed'),
                (probes, 1, 100, 'probes'), (forward_budget, 1, 1000000, 'forward_budget'),
                (instances, 1, 10, 'instances'), (episodes, 1, 8, 'episodes'), (max_steps, 1, 1000, 'max_steps')):
            self._integer(value, low, high, name)
        with self._locked():
            if any(p.name != '.lock' for p in self.path.iterdir()):
                raise ValueError('Benchmark already exists; use a fresh directory')
            rng = np.random.RandomState(seed)
            base = BreakoutBackend().initial_weights()
            reference_id = uuid.uuid4().hex
            save_weights(self.path / (reference_id + '.npz'), base)
            families = ['control', 'sign_flip', 'channel_ablation', 'bias_shift'] * instances
            rng.shuffle(families)
            state = dict(schema_version=1, generation_seed=seed, probes=probes, forward_budget=forward_budget,
                         episodes=episodes, max_steps=max_steps, reference_id=reference_id, cases=[])
            for family in families:
                weights = {k: v.copy() for k, v in base.items()}
                if family == 'sign_flip':
                    weights['W3'] *= -1
                elif family == 'channel_ablation':
                    weights['W3'][:, 1] = 0
                elif family == 'bias_shift':
                    weights['b3'][0] += 240
                case_id, root = uuid.uuid4().hex, uuid.uuid4().hex
                save_weights(self.path / (root + '.npz'), weights)
                # Non-overlapping disjoint intervals; neither interval is public.
                dev = int(rng.randint(0, 1000000)) * 16
                held = int(rng.randint(0, 1000000)) * 16 + 100000000
                state['cases'].append(dict(id=case_id, family=family, root_id=root,
                    dev_seed=dev, held_seed=held, candidates=[dict(id=root, parent=None)],
                    attempts=[], forward_reserved=0, finalized=False, final=None))
            self._save(state)
            return self._views(state)

    @staticmethod
    def _views(state):
        return [dict(id=c['id'], root_id=c['root_id'], candidates=copy.deepcopy(c['candidates']),
                     probes_used=len(c['attempts']), forward_reserved=c['forward_reserved'],
                     probe_limit=state['probes'], forward_budget=state['forward_budget'],
                     finalized=c['finalized'], episodes=state['episodes'], max_steps=state['max_steps'],
                     final_forward_budget=3 * state['episodes'] * state['max_steps'])
                for c in state['cases']]

    def cases(self):
        with self._locked():
            return self._views(self._read())

    @staticmethod
    def _case(state, case_id):
        for case in state['cases']:
            if case['id'] == case_id:
                return case
        raise ValueError('Unknown case id')

    def _weights(self, case, candidate_id):
        if not any(c['id'] == candidate_id for c in case['candidates']):
            raise ValueError('Candidate does not belong to this case')
        return load_weights(self.path / (candidate_id + '.npz'))

    def inspect(self, case_id, tensor, candidate_id=None):
        with self._locked():
            case = self._case(self._read(), case_id)
            weights = self._weights(case, candidate_id or case['root_id'])
            if tensor not in weights:
                raise ValueError('Unknown tensor')
            value = weights[tensor]
            return dict(tensor=tensor, shape=list(value.shape), values=value.tolist())

    def patch(self, case_id, parent_id, patch, hypothesis):
        if not isinstance(hypothesis, str) or not hypothesis.strip() or len(hypothesis) > 4000:
            raise ValueError('Provide a hypothesis of 1–4000 characters')
        with self._locked():
            state = self._read()
            case = self._case(state, case_id)
            if case['finalized']:
                raise ValueError('Selection is frozen')
            if len(case['candidates']) >= 101:
                raise ValueError('Candidate limit reached')
            before = self._weights(case, parent_id)
            after = apply_patch(before, patch)
            row = dict(id=uuid.uuid4().hex, parent=parent_id, hypothesis=hypothesis, patch=patch,
                       sha256=digest(after), parent_sha256=digest(before),
                       diff=difference(before, after))
            save_weights(self.path / (row['id'] + '.npz'), after)
            case['candidates'].append(row)
            self._save(state)
            return copy.deepcopy(row)

    @staticmethod
    def _evaluate(weights, seed, state):
        rows = [episode(weights, seed + i, state['max_steps'])
                for i in range(state['episodes'])]
        return dict(mean_score=float(np.mean([r['score'] for r in rows])),
                    scores=[r['score'] for r in rows],
                    se=float(np.std([r['score'] for r in rows], ddof=1) / math.sqrt(len(rows))) if len(rows) > 1 else None,
                    episodes=[{k: v for k, v in r.items() if k != 'trace'} for r in rows],
                    forward_calls=sum(r['steps'] for r in rows),
                    truncated=sum(r['truncated'] for r in rows))

    def probe(self, case_id, candidate_id):
        with self._locked():
            state = self._read()
            case = self._case(state, case_id)
            if case['finalized']:
                raise ValueError('Selection is frozen')
            weights = self._weights(case, candidate_id)
            cost = state['episodes'] * state['max_steps']
            if len(case['attempts']) >= state['probes']:
                raise ValueError('Probe limit exhausted')
            if case['forward_reserved'] + cost > state['forward_budget']:
                raise ValueError('Forward budget exhausted')
            attempt = dict(candidate_id=candidate_id, status='reserved', reserved=cost)
            case['attempts'].append(attempt)
            case['forward_reserved'] += cost
            self._save(state)  # Crash/failure consumes reservation; never refunded.
            try:
                attempt['result'] = self._evaluate(weights, case['dev_seed'], state)
                attempt['status'] = 'completed'
            except Exception:
                attempt['status'] = 'failed'
                self._save(state)
                raise
            self._save(state)
            public = copy.deepcopy(attempt)
            for row in public['result']['episodes']:
                row.pop('seed')
            return public

    def finalize(self, case_id, candidate_id, *, defer=False):
        with self._locked():
            state = self._read()
            case = self._case(state, case_id)
            if case['finalized']:
                raise ValueError('Selection is already frozen')
            weights = self._weights(case, candidate_id)
            case['finalized'] = True
            final = dict(candidate_id=candidate_id, status='frozen' if defer else 'reserved',
                         forward_reserved=3 * state['episodes'] * state['max_steps'])
            case['final'] = final
            self._save(state)  # Freeze before any held-out work, including failed work.
            if defer:
                return dict(case_id=case_id, candidate_id=candidate_id, frozen=True)
            return self._finish_final(state, case, weights)

    def finish_frozen(self):
        """Administrator only; caller must enforce the experiment-wide freeze gate."""
        with self._locked():
            state = self._read()
            if not all(c['finalized'] for c in state['cases']):
                raise ValueError('Freeze every case first')
            for case in state['cases']:
                if case['final']['status'] == 'frozen':
                    case['final']['status'] = 'reserved'
                    self._save(state)
                    self._finish_final(state, case, self._weights(case, case['final']['candidate_id']))

    def _finish_final(self, state, case, weights):
        final = case['final']
        case_id, candidate_id = case['id'], final['candidate_id']
        try:
            reference = load_weights(self.path / (state['reference_id'] + '.npz'))
            corrupted = self._weights(case, case['root_id'])
            for name, model in [('reference', reference), ('corrupted', corrupted),
                                ('selected', weights)]:
                final[name] = self._evaluate(model, case['held_seed'], state)
            final['delta_from_corrupted'] = final['selected']['mean_score'] - final['corrupted']['mean_score']
            final['delta_from_reference'] = final['selected']['mean_score'] - final['reference']['mean_score']
            for baseline in ('corrupted', 'reference'):
                deltas = np.array(final['selected']['scores']) - np.array(final[baseline]['scores'])
                final['paired_' + baseline] = dict(differences=deltas.tolist(),
                    mean=float(deltas.mean()),
                    se=float(deltas.std(ddof=1) / math.sqrt(len(deltas))) if len(deltas) > 1 else None)
            final['status'] = 'completed'
        except Exception:
            final['status'] = 'failed'
            self._save(state)
            raise
        self._save(state)
        # No held-out feedback until ALL selections have been frozen.
        return dict(case_id=case_id, candidate_id=candidate_id, status=final['status'], frozen=True)

    def report(self):
        with self._locked():
            state = self._read()
            if not all(c['finalized'] for c in state['cases']):
                raise ValueError('Freeze every case before requesting the report')
            return dict(schema_version=1, generation_seed=state['generation_seed'],
                environment='MinAtar 1.0.15 Breakout', numpy=np.__version__,
                sampling='softmax', sticky_actions=0.1, episodes=state['episodes'], max_steps=state['max_steps'],
                limitations='Local protocol only: fixture and private state are readable by the same OS user. Capped Breakout episodes; no novel repair claim. Final evaluations have a separate fixed budget.',
                cases=[dict(id=c['id'], family=c['family'], root_id=c['root_id'],
                            candidates=copy.deepcopy(c['candidates']), probes=copy.deepcopy(c['attempts']),
                            forward_reserved=c['forward_reserved'], final=copy.deepcopy(c['final']))
                       for c in state['cases']])
