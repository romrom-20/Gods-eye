"""Trusted, single-operator experiment service. Never imported by the agent image.

Only operator code registers private evaluator directories or supplies workers.
Browser input is handled exclusively through experiment_spec's exact contract.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import subprocess
import threading
import time
import uuid

from .core import digest, load_weights
from .experiment_spec import (
    ContractError, PlanningPolicy, TERMINAL, canonical_json,
    confirm_start, evidence_verdict, loads_message, plan, transition,
    validate_message, validate_spec,
)
from .provider_setup import ProviderSettings
from .storage import write_json


PARTICIPANTS = ('unchanged', 'heuristic', 'agent')
BUDGET_STOPS = {'provider_request_limit', 'input_token_limit', 'output_token_limit',
                'elapsed_time_limit', 'tool_call_limit', 'round_limit'}


def identity():
    return uuid.uuid4().hex


def empty_usage():
    return dict(requests=0, input_tokens=0, output_tokens=0, tool_calls=0,
                elapsed_seconds=0, usage_complete=True, request_in_flight=False)


class Stopped(Exception):
    """Cooperative worker stop, never evidence that remote billing stopped."""


class WorkerFailure(Exception):
    def __init__(self, reason):
        self.reason = reason


def snapshot(directory, *, fresh=False):
    """Trusted filesystem inspection; authorize membership before tensor lookup.

    Does not use benchmark._read(), which recovers reservations and would mutate
    a running evaluator. Only the operator supplies this directory.
    """
    directory = Path(directory)
    config = json.loads((directory / 'experiment.json').read_text())
    if set(config['participants']) != set(PARTICIPANTS):
        raise ValueError('All baseline participants are required')
    roots, states = [], {}
    for role in PARTICIPANTS:
        state = json.loads((directory / role / 'private-state.json').read_text())
        settings = config['settings']
        for key, setting in (('episodes', 'episodes'), ('max_steps', 'max_steps'),
                             ('probes', 'probes'), ('forward_budget', 'forward_budget')):
            if state[key] != settings[setting]:
                raise ValueError('Evaluator settings differ')
        if not state['cases'] or not any(c['family'] == 'control' for c in state['cases']):
            raise ValueError('Controls required')
        for case in state['cases']:
            root = case['root_id']
            # Validate trusted state IDs before turning them into file names.
            if (len(root) != 32 or any(c not in '0123456789abcdef' for c in root)
                    or not any(c['id'] == root and c['parent'] is None
                               for c in case['candidates'])):
                raise ValueError('Invalid root membership')
            if fresh and (case['attempts'] or case['finalized'] or case['final']
                          or case['forward_reserved'] or len(case['candidates']) != 1):
                raise ValueError('Evaluator has already been used')
            roots.append(dict(participant=role, case_id=case['id'], root_id=root,
                              sha256=digest(load_weights(directory / role / (root + '.npz')))))
        states[role] = state
    if fresh and (directory / '.orchestration.claim').exists():
        raise ValueError('Evaluator has already been claimed')
    return config, sorted(roots, key=lambda r: (r['participant'], r['case_id'])), states


def private_commitment(config, states, directory):
    """Private integrity fence; never part of the public baseline manifest/hash."""
    immutable = dict(config=config, participants={})
    for role, state in states.items():
        reference = state['reference_id']
        if len(reference) != 32 or any(c not in '0123456789abcdef' for c in reference):
            raise ValueError('Invalid private reference')
        immutable['participants'][role] = dict(
            generation_seed=state['generation_seed'], reference_id=reference,
            reference_sha256=digest(load_weights(Path(directory) / role / (reference + '.npz'))),
            cases=[{k: case[k] for k in ('id', 'root_id', 'family', 'dev_seed', 'held_seed')}
                   for case in state['cases']])
    return hashlib.sha256(canonical_json(immutable).encode()).hexdigest()


def policy_for(registration):
    return PlanningPolicy(**registration['policy'])


def verify_registration(registration, spec, *, fresh):
    policy = policy_for(registration)
    validate_spec(spec, policy)
    config, roots, states = snapshot(registration['directory'], fresh=fresh)
    if (roots != registration['manifest'] or private_commitment(
            config, states, registration['directory']) != registration['integrity_sha256']):
        raise ContractError('spec_conflict')
    settings = config['settings']
    if any(settings[k] != v for k, v in dict(
            episodes=policy.episodes, max_steps=policy.max_steps,
            probes=policy.probes_per_case, forward_budget=policy.forwards_per_case).items()):
        raise ContractError('spec_conflict')
    return states


def read_accounting(path, previous=None):
    """Allowlist adapter accounting, including an unresolved durable reservation.

    A partial final line is ignored. Unknown usage is never converted to zero.
    Raw tool/provider strings never enter a browser response.
    """
    usage = dict(previous or empty_usage())
    stop, completed = None, False
    if not Path(path).exists():
        return usage, stop, completed
    with Path(path).open('rb') as stream:
        for line in stream:
            if not line.endswith(b'\n'):
                break
            try:
                row = json.loads(line)
                counts = row.get('cumulative')
                if counts is not None:
                    candidate = {k: counts[k] for k in usage if k != 'tool_calls'}
                    candidate['tool_calls'] = counts['calls']
                    # Reuse exact response validation to check finite counts/flags.
                    validate_message('status_response', dict(
                        schema_version=1, experiment_id='accounting', spec_hash='0' * 64,
                        status='running', phase=dict(name='unknown', event_sequence=None),
                        verdict='not_evaluated', reason=None, usage=candidate))
                    if any(candidate[k] < usage[k] for k in (
                            'requests', 'input_tokens', 'output_tokens', 'tool_calls')):
                        continue
                    usage = candidate
                if row.get('event') in ('incomplete', 'failed'):
                    stop = row.get('reason')
                completed = row.get('event') == 'completed'
            except (ValueError, KeyError, TypeError):
                usage['usage_complete'] = False
    if usage['request_in_flight']:
        usage['usage_complete'] = False
    return usage, stop, completed


def audit_selections(states):
    """Fail before reveal when a changed selection lacks a prior root comparison."""
    for state in states.values():
        for case in state['cases']:
            final = case['final']
            if not case['finalized'] or final is None:
                raise WorkerFailure('agent_incomplete')
            chosen = final['candidate_id']
            if not any(c['id'] == chosen for c in case['candidates']):
                raise WorkerFailure('evaluation_error')
            if chosen == case['root_id']:
                continue
            root_score = None
            selected_score = None
            for probe in case['attempts']:
                if probe['status'] != 'completed':
                    continue
                score = probe['result']['mean_score']
                if probe['candidate_id'] == case['root_id']:
                    root_score = score
                elif probe['candidate_id'] == chosen and root_score is not None:
                    selected_score = score
            if root_score is None or selected_score is None or selected_score <= root_score:
                raise WorkerFailure('evaluation_error')


def assemble_result(registration, spec, directory):
    """Derive public evidence from complete, private evaluator records, never prose."""
    states = verify_registration(registration, spec, fresh=False)
    audit_selections(states)
    deltas, controls, manifest, patches = [], [], [], []
    report = {}
    for role, state in states.items():
        if len(state['cases']) != len([r for r in registration['manifest']
                                      if r['participant'] == role]):
            raise WorkerFailure('evaluation_error')
        report[role] = state  # Private: retains attempts, errors and baseline arms.
        for case in state['cases']:
            final = case['final']
            if final['status'] != 'completed':
                raise WorkerFailure('evaluation_error')
            for arm in ('reference', 'corrupted', 'selected'):
                scores = final[arm]['scores']
                if (len(scores) != spec['evaluation']['episodes']
                        or any(type(v) not in (int, float) or not math.isfinite(v) for v in scores)):
                    raise WorkerFailure('evaluation_error')
            paired = [a - b for a, b in zip(final['selected']['scores'],
                                          final['corrupted']['scores'])]
            if paired != final['paired_corrupted']['differences']:
                raise WorkerFailure('evaluation_error')
            if role == 'agent':
                deltas.extend(paired)
                if case['family'] == 'control':
                    controls.append(statistics.mean(paired))
            selected = final['candidate_id']
            path = Path(registration['directory']) / role
            manifest.append(dict(participant=role, case_id=case['id'], root_id=case['root_id'],
                                 selected_id=selected,
                                 root_sha256=digest(load_weights(path / (case['root_id'] + '.npz'))),
                                 selected_sha256=digest(load_weights(path / (selected + '.npz')))))
            patches.append(dict(participant=role, case_id=case['id'],
                                root_id=case['root_id'], selected_id=selected,
                                candidates=case['candidates'], paired_deltas=paired))
    if not controls or len(deltas) < 2:
        raise WorkerFailure('evaluation_error')
    artifacts = {}
    for kind, value in (('report', report), ('manifest', manifest), ('delta', patches)):
        artifact = identity()
        path = Path(directory) / (artifact + '.json')
        write_json(path, value)
        artifacts[artifact] = str(path)
        artifacts[kind] = artifact
    evidence = dict(
        baseline_id=spec['baseline']['id'], candidate_manifest_id=artifacts['manifest'],
        delta_artifact_id=artifacts['delta'], report_id=artifacts['report'],
        paired_samples=len(deltas), mean_delta=statistics.mean(deltas),
        paired_se=statistics.stdev(deltas) / math.sqrt(len(deltas)),
        min_control_delta=min(controls), limitations=[
            'Small capped paired episodes; the two-SE rule is descriptive, not calibrated significance.',
            'Improvement is relative to registered case roots, not the released clean policy.',
            'Local operator and Docker daemon are trusted; this is not production multi-user security.',
        ])
    evidence_verdict(evidence)
    return evidence, {k: v for k, v in artifacts.items() if k not in ('report', 'manifest', 'delta')}


@dataclass(frozen=True)
class AdmissionLimits:
    workers: int = 1
    queue: int = 4
    plans_per_minute: int = 30
    starts_per_minute: int = 10
    reads_per_minute: int = 120
    draft_seconds: int = 900
    drafts: int = 128

    def __post_init__(self):
        for value in self.__dict__.values():
            if type(value) is not int or value < 1:
                raise ValueError('Admission limits must be finite positive integers')
        if self.workers > 8 or self.queue > 128:
            raise ValueError('Worker or queue limit exceeds local service ceiling')


class Orchestrator:
    """One local authorization scope per private DB and server token.

    A lifetime OS lock refuses a second service owner. SQLite FULL transactions
    bind confirmation, idempotency, single-use registry claim and queue admission.
    """
    def __init__(self, directory, *, worker=None, settings=None, limits=None, clock=time.time):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        self.owner = (self.directory / '.service.lock').open('a')
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owner.close()
            raise ContractError('unavailable') from None
        self.lock = threading.RLock()
        self.worker, self.settings = worker, settings or ProviderSettings()
        self.limits, self.clock = limits or AdmissionLimits(), clock
        if worker and self.limits.workers > worker.capacity:
            self.owner.close()
            raise ValueError('Worker cannot support configured concurrency')
        self.closed, self.events = False, {}
        self.db = sqlite3.connect(self.directory / 'orchestration.sqlite3', check_same_thread=False)
        os.chmod(self.directory / 'orchestration.sqlite3', 0o600)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, kind TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS starts (key TEXT PRIMARY KEY, draft TEXT UNIQUE,
                hash TEXT, run TEXT UNIQUE, baseline TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS rates (kind TEXT PRIMARY KEY, since REAL, count INTEGER);
        ''')
        self.db.commit()
        self.pool = ThreadPoolExecutor(max_workers=self.limits.workers,
                                       thread_name_prefix='experiment')
        # Quiesce deterministic containers from a prior service, without resuming,
        # loading keys, calling report, or refunding any reservation. If recovery
        # cannot establish local quiescence, fence new starts for this service.
        self.recovery_blocked = False
        recovered = set()
        for row in self.rows('run'):
            if row['status'] not in TERMINAL or row.get('recovery_required'):
                if worker is None:
                    self.recovery_blocked = True
                else:
                    try:
                        worker.recover(row, self.registration(row['spec']['baseline']['id']),
                                       self.directory / row['id'])
                        recovered.add(row['id'])
                    except Exception:
                        self.recovery_blocked = True
        # Never resubmit a persisted job or clear an evaluator/evidence claim.
        with self.transaction():
            for row in self.rows('run'):
                if row['status'] not in TERMINAL or row.get('recovery_required'):
                    usage, _, _ = read_accounting(self.evidence_path(row['id']), row['usage'])
                    if row['status'] not in TERMINAL:
                        row.update(status=transition(row['status'], 'interrupted'),
                                   reason='process_lost')
                    row.update(usage=usage, recovery_required=row['id'] not in recovered)
                    self.save(row['id'], 'run', row)

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def rows(self, kind):
        return [json.loads(r[0]) for r in self.db.execute(
            'SELECT body FROM documents WHERE kind=?', (kind,))]

    def load(self, identifier, kind):
        row = self.db.execute('SELECT body FROM documents WHERE id=? AND kind=?',
                              (identifier, kind)).fetchone()
        if row is None:
            raise ContractError('not_found')
        return json.loads(row[0])

    def save(self, identifier, kind, value):
        self.db.execute('INSERT OR REPLACE INTO documents VALUES (?, ?, ?)',
                        (identifier, kind, canonical_json(value)))

    def throttle(self, kind, maximum):
        row = self.db.execute('SELECT since,count FROM rates WHERE kind=?', (kind,)).fetchone()
        now = self.clock()
        since, count = row if row and 0 <= now - row[0] < 60 else (now, 0)
        if count >= maximum:
            raise ContractError('rate_limited')
        self.db.execute('INSERT OR REPLACE INTO rates VALUES (?, ?, ?)', (kind, since, count + 1))

    def register(self, directory, *, baseline_id, suite_id, revision, ceilings=None):
        """Operator-only, never an HTTP operation. Register a fresh, private suite.

        Initialize via the existing isolated evaluator; do not reuse revealed suites.
        Registering another suite selects it for subsequent plans, without changing
        immutable existing registrations. Duplicate baseline IDs are refused.
        """
        config, manifest, states = snapshot(directory, fresh=True)
        settings = config['settings']
        policy = PlanningPolicy(
            baseline_id, hashlib.sha256(canonical_json(manifest).encode()).hexdigest(),
            suite_id, revision, episodes=settings['episodes'], max_steps=settings['max_steps'],
            probes_per_case=settings['probes'], forwards_per_case=settings['forward_budget'],
            **({'ceilings': ceilings} if ceilings is not None else {}))
        registration = dict(directory=str(Path(directory).resolve()), manifest=manifest,
                            integrity_sha256=private_commitment(config, states, directory),
                            policy=dict(baseline_id=policy.baseline_id,
                                        baseline_sha256=policy.baseline_sha256,
                                        suite_id=policy.suite_id, revision=policy.revision,
                                        episodes=policy.episodes, max_steps=policy.max_steps,
                                        probes_per_case=policy.probes_per_case,
                                        forwards_per_case=policy.forwards_per_case,
                                        ceilings=dict(policy.ceilings)))
        with self.transaction():
            if any(r['directory'] == registration['directory'] or r['manifest'] == manifest
                   for r in self.rows('registry')):
                raise ContractError('state_conflict')
            if self.db.execute('SELECT 1 FROM documents WHERE id=?',
                               ('registry_' + baseline_id,)).fetchone():
                raise ContractError('state_conflict')
            self.save('registry_' + baseline_id, 'registry', registration)
            self.save('current_registry', 'config', dict(baseline_id=baseline_id))
        return policy

    def registration(self, baseline):
        return self.load('registry_' + baseline, 'registry')

    def evidence_path(self, run_id):
        return self.directory / run_id / 'evidence' / 'agent.jsonl'

    def handle(self, operation, raw):
        if operation not in ('plan', 'start', 'status', 'cancel', 'results'):
            raise ContractError('not_found')
        request = validate_message(operation + '_request', loads_message(raw))
        return getattr(self, operation)(request)

    def plan(self, request):
        request = validate_message('plan_request', request)
        with self.transaction():
            self.throttle('plan', self.limits.plans_per_minute)
        with self.transaction():
            try:
                current = self.load('current_registry', 'config')
            except ContractError:
                raise ContractError('unavailable') from None
            registration = self.registration(current['baseline_id'])
            # Purge only unadmitted, expired drafts; admitted review remains durable.
            for draft in self.rows('draft'):
                if draft['expires'] <= self.clock() and draft['status'] == 'ready':
                    self.db.execute('DELETE FROM documents WHERE id=?', (draft['id'],))
            if sum(d['status'] == 'ready' for d in self.rows('draft')) >= self.limits.drafts:
                raise ContractError('rate_limited')
            result = plan(request, policy_for(registration), draft_id=identity())
            if result['outcome'] == 'ready':
                self.save(result['draft_id'], 'draft', dict(
                    id=result['draft_id'], status='ready', spec=result['spec'],
                    hash=result['spec_hash'], expires=self.clock() + self.limits.draft_seconds))
        return result

    def start(self, request):
        request = validate_message('start_request', request)
        with self.lock:
            return self._start(request)

    def _start(self, request):
        with self.transaction():
            existing = self.db.execute('SELECT draft,hash,run FROM starts WHERE key=?',
                                       (request['idempotency_key'],)).fetchone()
            if existing:
                if tuple(existing[:2]) != (request['draft_id'], request['spec_hash']):
                    raise ContractError('idempotency_conflict')
                return self.start_response(self.load(existing[2], 'run'))
            self.throttle('start', self.limits.starts_per_minute)
        with self.transaction():
            draft = self.load(request['draft_id'], 'draft')
            if draft['hash'] != request['spec_hash'] or draft['expires'] <= self.clock():
                raise ContractError('spec_conflict')
            registration = self.registration(draft['spec']['baseline']['id'])
            spec = confirm_start(request, draft['spec'], policy_for(registration),
                                 draft_id=draft['id'], status=draft['status'])
            if self.db.execute('SELECT 1 FROM starts WHERE baseline=?',
                               (spec.to_dict()['baseline']['id'],)).fetchone():
                raise ContractError('state_conflict')
            try:
                verify_registration(registration, spec.to_dict(), fresh=True)
            except (ValueError, KeyError, OSError):
                raise ContractError('spec_conflict') from None
            if (self.closed or self.recovery_blocked or self.worker is None
                    or not self.worker.available()):
                raise ContractError('worker_unavailable')
            active = sum(r['status'] not in TERMINAL for r in self.rows('run'))
            if active >= self.limits.workers + self.limits.queue:
                raise ContractError('queue_full')
            run_id = identity()
            evidence_ids = {role: identity() for role in PARTICIPANTS}
            evidence_artifacts = {artifact: str(self.directory / run_id / 'evidence' /
                                                (role + '.jsonl'))
                                  for role, artifact in evidence_ids.items()}
            row = dict(id=run_id, status='queued', spec=spec.to_dict(), hash=spec.sha256,
                       confirmation=request, usage=empty_usage(), reason=None,
                       evidence=None, artifacts=evidence_artifacts, evidence_ids=evidence_ids,
                       created=self.clock())
            self.save(run_id, 'run', row)
            self.db.execute('INSERT INTO starts VALUES (?, ?, ?, ?, ?)',
                            (request['idempotency_key'], draft['id'], spec.sha256,
                             run_id, spec.to_dict()['baseline']['id']))
            draft['status'] = transition(draft['status'], 'queued')
            self.save(draft['id'], 'draft', draft)
            self.events[run_id] = threading.Event()
        # Identity is committed before scheduling or loading any credential.
        # Keep scheduling ordered with close(); rejected scheduling preserves run identity.
        with self.lock:
            if not self.closed:
                try:
                    self.pool.submit(self._run, run_id)
                except RuntimeError:
                    with self.transaction():
                        row['status'] = transition(row['status'], 'failed')
                        row['reason'] = 'runtime_failure'
                        self.save(run_id, 'run', row)
                        self.events.pop(run_id, None)
        return self.start_response(row)

    @staticmethod
    def start_response(row):
        return validate_message('start_response', dict(schema_version=1, experiment_id=row['id'],
                                spec_hash=row['hash'], status=row['status']))

    @staticmethod
    def response(row, operation):
        value = dict(schema_version=1, experiment_id=row['id'], spec_hash=row['hash'],
                     status=row['status'], phase=dict(name='unknown', event_sequence=None),
                     verdict=evidence_verdict(row['evidence']) if row['status'] == 'completed'
                     else 'not_evaluated', reason=row['reason'], usage=row['usage'])
        if operation == 'results':
            value['evidence'] = row['evidence'] if row['status'] == 'completed' else None
        return validate_message(operation + '_response', value)

    def status(self, request):
        request = validate_message('status_request', request)
        with self.transaction():
            self.throttle('read', self.limits.reads_per_minute)
        with self.lock:
            return self.response(self.load(request['experiment_id'], 'run'), 'status')

    def results(self, request):
        request = validate_message('results_request', request)
        with self.transaction():
            self.throttle('read', self.limits.reads_per_minute)
        with self.lock:
            return self.response(self.load(request['experiment_id'], 'run'), 'results')

    def cancel(self, request):
        request = validate_message('cancel_request', request)
        with self.transaction():
            row = self.load(request['experiment_id'], 'run')
            if row['status'] in ('queued', 'running'):
                row['status'] = transition(row['status'], 'cancelling')
                self.save(row['id'], 'run', row)
                self.events[row['id']].set()
            return self.response(row, 'cancel')

    def _run(self, run_id):
        event = self.events[run_id]
        row, reason, evidence, artifacts = None, None, None, {}
        try:
            with self.transaction():
                row = self.load(run_id, 'run')
                if event.is_set():
                    raise Stopped()
                row['status'] = transition(row['status'], 'running')
                self.save(run_id, 'run', row)
                registration = self.registration(row['spec']['baseline']['id'])
            try:
                verify_registration(registration, row['spec'], fresh=True)
            except (ValueError, KeyError, OSError):
                raise WorkerFailure('evaluation_error') from None
            directory = self.directory / run_id
            directory.mkdir(mode=0o700)
            (directory / 'evidence').mkdir(mode=0o700)
            # Permanent one-use claim on the private evaluator too.
            claim = Path(registration['directory']) / '.orchestration.claim'
            with claim.open('x') as stream:
                stream.write(run_id)
                stream.flush()
                os.fsync(stream.fileno())
            fd = os.open(str(claim.parent), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

            def check():
                if event.is_set():
                    raise Stopped()

            def accounting():
                usage, _, _ = read_accounting(self.evidence_path(run_id))
                with self.transaction():
                    current = self.load(run_id, 'run')
                    current['usage'] = usage
                    self.save(run_id, 'run', current)

            check()
            self.worker.execute(row, registration, directory, self.settings, check, accounting)
            check()
            try:
                evidence, artifacts = assemble_result(registration, row['spec'], directory)
            except (ValueError, KeyError, TypeError, OSError):
                raise WorkerFailure('evaluation_error') from None
        except Stopped:
            pass
        except WorkerFailure as error:
            reason = error.reason
        except ContractError:
            reason = 'evaluation_error'
        except Exception:
            reason = 'runtime_failure'  # No raw exceptions or provider text in logs/responses.
        finally:
            # Worker.execute must not return until local work is quiescent; inability
            # to establish that is process_lost, never a cancelled acknowledgement.
            with self.transaction():
                current = self.load(run_id, 'run')
                usage, _, _ = read_accounting(self.evidence_path(run_id), current['usage'])
                if reason == 'process_lost':
                    self.recovery_blocked = True
                if reason == 'process_lost' or self.closed:
                    status, reason = 'interrupted', 'process_lost'
                elif current['status'] == 'cancelling':
                    status, reason = 'cancelled', 'user_cancelled'
                elif reason:
                    status = 'failed'
                elif evidence is not None:
                    status = 'completed'
                else:
                    status, reason = 'failed', 'agent_incomplete'
                current['artifacts'].update(artifacts)
                current.update(status=transition(current['status'], status), reason=reason,
                               recovery_required=reason == 'process_lost',
                               usage=usage, evidence=evidence if status == 'completed' else None)
                self.save(run_id, 'run', current)
                self.events.pop(run_id, None)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            for event in self.events.values():
                event.set()
        self.pool.shutdown(wait=True)
        with self.transaction():
            for row in self.rows('run'):
                if row['status'] not in TERMINAL:
                    row.update(status=transition(row['status'], 'interrupted'),
                               reason='process_lost', recovery_required=True)
                    self.save(row['id'], 'run', row)
        self.db.close()
        self.owner.close()


class DockerWorker:
    """Source-checkout worker using the existing, unmodified Compose isolation.

    The gateway has a fixed loopback port, so this worker's capacity is one.
    Images must be built by the trusted operator; no runtime build or shell.
    """
    capacity = 1

    def __init__(self, checkout):
        self.checkout = Path(checkout).resolve()
        self.compose = self.checkout / 'isolation' / 'compose.yaml'
        if not self.compose.is_file():
            raise ValueError('Existing isolation checkout required')

    def _images(self):
        # Trusted worker implementation only; never configured by an API request.
        # Tests subclass this to select an image with a scripted transport while
        # retaining the actual worker, adapter, and Compose isolation settings.
        return {role: 'isolation-' + role for role in ('evaluator', 'agent', 'gateway')}

    def available(self):
        # No provider contact, key read, daemon mutation, image pull or build.
        if os.getuid() == 0:
            return False  # Never override Compose's non-root user with root.
        try:
            # `info` also probes unrelated CLI plugins, which can hang even when
            # the daemon is healthy. `version` checks the server without that scan.
            if subprocess.run(['docker', 'version', '--format', '{{.Server.Version}}'],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=5).returncode:
                return False
            return subprocess.run(['docker', 'image', 'inspect', 'isolation-evaluator',
                                   'isolation-agent', 'isolation-gateway'],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=5).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def recover(self, row, registration, directory):
        """Stop orphaned local containers. Never start, reveal, or reconnect an agent."""
        project = 'ge-' + row['id']
        env = {k: v for k, v in os.environ.items() if k in (
            'PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG',
            'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'TMPDIR')}
        env.update(EVALUATOR_PRIVATE_DIR=registration['directory'],
                   REPAIR_EVIDENCE_DIR=str(directory / 'evidence'),
                   REPAIR_AGENT_KEY_FILE=str(directory / 'provider.key'),
                   EVALUATOR_UID=str(os.getuid()), EVALUATOR_GID=str(os.getgid()))
        # A one-off compose run can survive its CLI parent. It must be addressed
        # by its deterministic name as well as stopping the project services.
        result = subprocess.run(['docker', 'ps', '-aq', '--filter', 'name=^/' + project + '-agent$'],
                                env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=10, check=True)
        if result.stdout.strip():
            subprocess.run(['docker', 'rm', '-f', project + '-agent'], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, check=True)
        subprocess.run(['docker', 'compose', '--project-name', project, '--env-file', '/dev/null',
                        '-f', str(self.compose), '--profile', 'agent', 'down', '--timeout', '1'], env=env,
                       cwd=self.checkout, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=15, check=True)
        (directory / 'provider.key').unlink(missing_ok=True)

    def execute(self, row, registration, directory, settings, check, accounting):
        from isolation.agent_adapter import Client, Evidence, baseline, post

        private, evidence = Path(registration['directory']), directory / 'evidence'
        key_file = directory / 'provider.key'
        project = 'ge-' + row['id']
        container = project + '-agent'
        # Ignore inherited Compose overrides/provider configuration entirely.
        env = {k: v for k, v in os.environ.items() if k in (
            'PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG',
            'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'TMPDIR')}
        env.update(EVALUATOR_PRIVATE_DIR=str(private), REPAIR_EVIDENCE_DIR=str(evidence),
                   EVALUATOR_UID=str(os.getuid()), EVALUATOR_GID=str(os.getgid()),
                   REPAIR_AGENT_KEY_FILE=str(key_file))
        provider = row['spec']['provider']
        env.update(REPAIR_AGENT_PROVIDER=provider['name'], REPAIR_AGENT_MODEL=provider['model'],
                   REPAIR_AGENT_ROUTING=provider['routing'])
        env.update({'REPAIR_AGENT_' + k.upper(): str(v)
                    for k, v in row['spec']['limits'].items()})
        # Run identity changes the Compose project, which otherwise changes default
        # image tags too. Pin the existing operator-built images without modifying
        # any service's mounts, networking, resource limits, user or entrypoint.
        image_config = directory / 'compose-images.json'
        write_json(image_config, dict(services={role: dict(image=image)
                                               for role, image in self._images().items()}))
        command = ['docker', 'compose', '--project-name', project, '--env-file', '/dev/null',
                   '-f', str(self.compose), '-f', str(image_config)]

        def compose(args, timeout=30):
            result = subprocess.run(command + args, env=env, cwd=self.checkout,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    timeout=timeout)
            if result.returncode:
                raise WorkerFailure('runtime_failure')

        def checked_call(client, operation, args):
            check()
            return Client.call(client, operation, args)

        class GuardedClient(Client):
            def call(self, operation, args):
                return checked_call(self, operation, args)

        process = None
        try:
            if os.getuid() == 0:
                raise WorkerFailure('runtime_failure')
            check()
            credential = settings.credential(provider['name'])
            with open(key_file, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
                stream.write(credential)
            del credential
            check()
            compose(['up', '-d', '--no-build', '--pull', 'never', 'evaluator', 'gateway'])
            # Readiness polling is control-plane only; no evaluator/provider work retries.
            ready = False
            for _ in range(100):
                check()
                client = GuardedClient('http://127.0.0.1:8790',
                                       (private / 'agent.token').read_text().strip())
                if 'cases' in client.call('list', {}):
                    ready = True
                    break
                time.sleep(.05)
            if not ready:
                raise WorkerFailure('evaluation_error')
            for role in ('unchanged', 'heuristic'):
                check()
                client = GuardedClient('http://127.0.0.1:8790',
                                       (private / (role + '.token')).read_text().strip())
                log = Evidence(evidence / (role + '.jsonl'))
                try:
                    try:
                        baseline(client, role, log)
                    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
                        raise WorkerFailure('evaluation_error') from None
                finally:
                    log.stream.close()
            check()
            process = subprocess.Popen(command + ['run', '--rm', '--no-deps', '--pull', 'never',
                                                   '--name', container, 'agent'],
                                       env=env, cwd=self.checkout, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL)
            agent_started = time.monotonic()
            while process.poll() is None:
                accounting()
                check()
                if time.monotonic() - agent_started >= row['spec']['limits']['max_seconds']:
                    raise WorkerFailure('budget_exhausted')
                time.sleep(.05)
            accounting()
            usage, stop, completed = read_accounting(evidence / 'agent.jsonl')
            if process.returncode or not completed:
                reason = ('budget_exhausted' if stop in BUDGET_STOPS else
                          'provider_error' if stop in ('provider_request_failed',
                                                       'missing_or_malformed_usage',
                                                       'provider_response_incomplete') else
                          'agent_incomplete')
                raise WorkerFailure(reason)
            check()
            states = verify_registration(registration, row['spec'], fresh=False)
            audit_selections(states)
            check()
            try:
                report = post('http://127.0.0.1:8790/report',
                              (private / 'admin.token').read_text().strip(), {})
            except (OSError, ValueError, KeyError, TypeError):
                raise WorkerFailure('evaluation_error') from None
            write_json(directory / 'held-out.json', report)
            check()
        finally:
            # A restart never resumes this run. Container identity is deterministic,
            # and a retained claim prevents an alternate agent invocation.
            quiescent = True
            try:
                # Stop the CLI from issuing any later container-start command.
                # Its exit alone cannot certify container stop (e.g. daemon link
                # loss), so always reconcile the named one-off and project too.
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                self.recover(row, registration, directory)
            except (OSError, subprocess.SubprocessError):
                quiescent = False
            accounting()
            if not quiescent:
                raise WorkerFailure('process_lost')
