"""Trusted loopback control plane for one fixed local Qwen task (stdlib only).

SQLite is the durable admission authority; an inherited POSIX flock is the process
ownership fence. Neither HTTP retries nor recovery ever launch an admitted job.
"""
try:
    import fcntl
except ImportError:  # Ordinary lab imports still work on platforms without POSIX locks.
    fcntl = None
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

from .local_runtime import MODEL, REVISION
from .local_task_runner import approved_spec
from .service_worker import LocalWorker
from .task_contract import canonical, digest, preview, strict_json
from .task_suite import evaluate, freeze_selection, validate_record

TERMINAL = {'completed', 'failed', 'cancelled', 'interrupted'}
STATUS = dict(unavailable=503, readonly=403, invalid_request=422, not_found=404,
              conflict=409, plan_expired=409, busy=429, storage_full=507, internal=500)
MAX_EVIDENCE = 256 * 1024**2
MAX_FILE = 16 * 1024**2
MAX_RESPONSE = 4 * 1024**2
RUN_RESERVATION = 32 * 1024**2
REVIEW = ('Local CPU; fixed Qwen2.5-0.5B-Instruct target; public 28-case fixture; '
          'two predefined column edits, prompt and decoding alternatives, and unchanged original. '
          'Ceilings: 126 attempts, 96 new tokens each, 30 minutes total including loading, hashes '
          'and cleanup. No provider fee. These are ceilings, not a time estimate or improvement promise.')


def timestamp(value=None):
    return datetime.fromtimestamp(time.time() if value is None else value,
                                  timezone.utc).isoformat().replace('+00:00', 'Z')


class ServiceError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)

    def response(self):
        return dict(schema_version=1, code=self.code, error=self.message)


def read_json(path, maximum=MAX_FILE):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('unsafe evidence')
    return strict_json(path.read_text(), max_bytes=maximum)


def _journal(output):
    """Validate the existing hash chain, retaining its complete prefix on crash."""
    path = output / 'run/journal.jsonl'
    if not path.exists():
        return [], 'journal_not_created'
    if path.is_symlink() or path.stat().st_size > MAX_FILE:
        return [], 'invalid_journal'
    events, previous = [], None
    issue = None
    with path.open('rb') as stream:
        for line in stream:
            try:
                if not line.endswith(b'\n') or len(events) >= 1024:
                    raise ValueError()
                e = strict_json(line.decode(), max_bytes=256 * 1024)
                if type(e) is not dict or not isinstance(e.get('kind'), str):
                    raise ValueError()
                body = {k: v for k, v in e.items() if k != 'sha256'}
                if (type(e['sequence']) is not int or e['sequence'] != len(events)
                        or e['previous_sha256'] != previous or e['sha256'] != digest(body)):
                    raise ValueError()
                events.append(e)
                previous = e['sha256']
            except (ValueError, KeyError, TypeError, UnicodeError):
                issue = 'invalid_journal'
                break
    return events, issue


def journal(output):
    try:
        return _journal(output)
    except OSError:
        return [], 'invalid_journal'


def evidence(output):
    """Recompute scores from validated records; never publish raw runtime/log/error data."""
    spec = approved_spec()
    events, issue = journal(output)
    reservations, records = {}, []
    frozen = None
    frozen_seen = False
    base = None
    rollback_ok = True
    selected_check = None
    begun = []
    ended = []
    try:
        for e in events:
            kind = e['kind']
            if kind == 'candidates':
                base = e['base_tensor_sha256']
                if not isinstance(base, str) or not re.fullmatch('[a-f0-9]{64}', base):
                    raise ValueError()
            elif kind == 'reservation':
                attempt = e['attempt_id']
                if attempt in reservations or len(reservations) >= 126 or e['spec_sha256'] != spec.sha256:
                    raise ValueError()
                if e['split'] == 'heldout' and not frozen_seen:
                    raise ValueError()
                reservations[attempt] = e
            elif kind == 'result':
                r = validate_record(e['record'], spec)
                reservation = reservations.get(r['attempt_id'])
                if (reservation is None or any(reservation[k] != r[k] for k in
                        ('spec_sha256', 'case_id', 'split', 'variant'))
                        or r['attempt_id'] in {v['attempt_id'] for v in records}):
                    raise ValueError()
                records.append(r)
            elif kind == 'variant_begin':
                if base is None or e['base_tensor_sha256'] != base:
                    raise ValueError()
                begun.append((e['split'], e['variant']))
            elif kind == 'variant_end':
                ended.append((e['split'], e['variant']))
                rollback_ok &= e['rollback_tensor_sha256'] == base
            elif kind == 'freeze':
                if (frozen_seen or not rollback_ok or begun != ended
                        or any(r['split'] == 'heldout' for r in records)):
                    raise ValueError()
                frozen = freeze_selection(spec, records)
                if not frozen['selection_eligible'] or e['freeze'] != frozen:
                    raise ValueError()
                if read_json(output / 'run/freeze.json') != frozen:
                    raise ValueError()
                frozen_seen = True
            elif kind == 'selected_delta_verified':
                selected_check = e
        if issue == 'invalid_journal':
            raise ValueError()
        assessment = frozen or freeze_selection(spec, [r for r in records if r['split'] == 'dev'])
        report = evaluate(spec, assessment, records) if records else None
        complete = False
        delta = None
        reason = 'worker_crash'
        report_path = output / 'run/report.json'
        if report_path.exists():
            raw = read_json(report_path)
            if type(raw) is not dict:
                raise ValueError()
            # The evaluator's score/count/data identity fields must agree exactly.
            if report is None or any(raw.get(k) != v for k, v in report.items()):
                # Runner explicitly marks failures incomplete even after all calls returned.
                if report is None or any(raw.get(k) != v for k, v in report.items()
                                         if k not in ('status', 'verdict')):
                    raise ValueError()
            if (raw.get('persisted_freeze') != frozen or
                    raw.get('original_tensor_sha256') != base or
                    raw.get('final_tensor_sha256') != base or base is None
                    or not rollback_ok or begun != ended):
                reason = 'rollback_failed'
            elif raw.get('error') is not None:
                reason = ('budget_limited' if any(r['status'] == 'budget_limited' for r in records)
                          else 'evaluation_incomplete')
            elif raw.get('status') == 'complete' and report['status'] == 'complete' and frozen_seen:
                complete = True
                reason = None
            else:
                reason = ('budget_limited' if any(r['status'] == 'budget_limited' for r in records)
                          else 'evaluation_incomplete')
            if complete and len(reservations) != len(records):
                complete, reason = False, 'evaluation_incomplete'
            if complete:
                identity = read_json(output / 'run/spec.json')
                if (type(identity) is not dict or identity.get('spec') != spec.to_dict() or identity.get('sha256') != spec.sha256):
                    raise ValueError()
                finishes = [e for e in events if e['kind'] == 'finish']
                if (len(finishes) != 1 or finishes[0].get('report_sha256') != digest(raw)
                        or finishes[0].get('attempt_count') != len(records)
                        or events[-1] != finishes[0]):
                    raise ValueError()
            if complete and frozen['selected_weight'] != 'unchanged':
                from .local_delta import load_delta
                delta = load_delta(output / 'run/selected-delta.json')
                check = raw.get('selected_delta_check')
                reload = read_json(output / 'selected-reload.json')
                hashes = dict(base_tensor_sha256=base,
                              edited_tensor_sha256=delta['edited_tensor_sha256'],
                              rollback_tensor_sha256=base)
                variant = frozen['selected_weight']
                candidate = spec.to_dict()['operations']['candidates'][int(variant[-1])]
                if (type(check) is not dict or type(reload) is not dict or selected_check is None
                        or check.get('variant') != variant
                        or selected_check.get('variant') != variant
                        or selected_check.get('content_sha256') != delta['content_sha256']
                        or check.get('content_sha256') != delta['content_sha256']
                        or delta['base_tensor_sha256'] != base
                        or delta['column'] != candidate['column'] or delta['scale'] != candidate['scale']
                        or reload.get('status') != 'complete'
                        or any(check.get(k) != v or reload.get(k) != v or
                               selected_check.get(k) != v for k, v in hashes.items())):
                    raise ValueError()
        if report is not None:
            report.update(persisted_freeze=frozen, original_tensor_sha256=base,
                          selected_delta_check=({k: raw['selected_delta_check'][k] for k in
                              ('variant', 'base_tensor_sha256', 'edited_tensor_sha256',
                               'rollback_tensor_sha256', 'content_sha256')} if complete and delta else None))
        if report is not None and not complete:
            report['status'], report['verdict'] = 'incomplete', 'not_evaluated'
        return dict(report=report, attempts=records,
                    interrupted_attempts=len(reservations) - len(records)), complete, reason, delta
    except (ValueError, KeyError, TypeError, OSError, IndexError):
        # Preserve validated prefix, but never accept a malformed report as success.
        return dict(report=None, attempts=records,
                    interrupted_attempts=max(0, len(reservations) - len(records))), False, 'invalid_evidence', None


class LMService:
    def __init__(self, directory=None, *, adapter=None, cache=None, python=None,
                 seconds=1800, grace=1.0, clock=time.time):
        self.lock = threading.RLock()
        self.clock, self.seconds, self.grace = clock, min(seconds, 1800), min(grace, 1.0)
        self.directory = Path(directory) if directory else None
        self.adapter = adapter or (LocalWorker(cache, python) if cache and python else None)
        self.db = None
        self.guard = None
        self.owner = False
        self.closed = False
        self.thread = None
        self.child = None
        self.active = None
        self.cancel_event = threading.Event()
        self._ready = None
        self._ready_until = 0
        self.setup_error = None
        if self.directory is None or self.adapter is None:
            self.setup_error = ('Set GODSEYE_LM_CACHE, GODSEYE_LM_PYTHON and GODSEYE_LM_DIR '
                                'before starting the local lab; see local-lm-service.md.')
            return
        if fcntl is None:
            self.setup_error = 'Local LM process ownership requires a POSIX host (macOS or Linux). '
            return
        try:
            if isinstance(self.adapter, LocalWorker):
                cache_path = self.adapter.cache.resolve()
                evidence_path = self.directory.resolve()
                if (cache_path == evidence_path or cache_path in evidence_path.parents
                        or evidence_path in cache_path.parents):
                    raise ValueError()
            if not self.directory.is_absolute() or self.directory.is_symlink():
                raise ValueError()
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.directory.stat().st_mode & 0o077:
                raise ValueError()
            guard_path = self.directory / 'owner.lock'
            fd = os.open(guard_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            self.guard = os.fdopen(fd, 'r+')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.owner = True
            except BlockingIOError:
                self.setup_error = ('Another service or surviving worker owns this LM directory. '
                                    'Wait for it to stop; do not retry with another directory.')
            dbpath = self.directory / 'control.sqlite3'
            if dbpath.is_symlink():
                raise ValueError()
            self.db = sqlite3.connect(dbpath, check_same_thread=False, timeout=5)
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA synchronous=FULL')
            self.db.executescript('''
                CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, expires REAL, spec TEXT, hash TEXT);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, key TEXT UNIQUE, plan TEXT,
                    hash TEXT, created TEXT, updated TEXT, status TEXT, reason TEXT,
                    result TEXT, delta TEXT);
            ''')
            if self.owner:
                with self.db:
                    self.db.execute("UPDATE jobs SET status='interrupted', reason='service_restarted', "
                                    "updated=? WHERE status NOT IN ('completed','failed','cancelled','interrupted')",
                                    (timestamp(),))
        except (OSError, ValueError, sqlite3.Error):
            self.setup_error = ('GODSEYE_LM_DIR must be an absolute private writable directory '
                                '(mode 0700) with a healthy control store.')
            self.owner = False

    @classmethod
    def from_env(cls):
        return cls(os.environ.get('GODSEYE_LM_DIR'), cache=os.environ.get('GODSEYE_LM_CACHE'),
                   python=os.environ.get('GODSEYE_LM_PYTHON'))

    def readiness(self):
        if self.setup_error:
            return self.setup_error
        if self.closed or not self.owner:
            return 'Local LM service is stopped or ownership cannot be established. Restart the local lab.'
        now = time.monotonic()
        if now >= self._ready_until:
            try:
                self._ready = self.adapter.readiness()
            except Exception:
                self._ready = 'Local runtime metadata could not be checked; review the operator setup.'
            self._ready_until = now + 30
        return self._ready

    def capabilities(self, readonly=False):
        with self.lock:
            reason = ('Recorded demo is read-only. Start a configured local lab.' if readonly
                      else self.readiness())
            return dict(schema_version=1, available=reason is None, readonly=readonly, reason=reason,
                        model=dict(id=MODEL, revision=REVISION), execution='local_cpu',
                        supported_goal='correct_bounded_json', sample_request='Improve JSON schema adherence',
                        limits=dict(max_attempts=126, max_new_tokens=96,
                                    max_worker_seconds=1800, max_concurrency=1))

    def plan(self, request):
        value = preview(request, revision=REVISION)
        value.update(schema_version=1, plan_id=None, expires_at=None)
        if value['outcome'] != 'ready':
            return value
        with self.lock:
            reason = self.readiness()
            if reason:
                raise ServiceError('unavailable', reason)
            now = self.clock()
            with self.db:
                self.db.execute('DELETE FROM plans WHERE expires < ? AND id NOT IN (SELECT plan FROM jobs)', (now,))
                if self.db.execute('SELECT COUNT(*) FROM plans WHERE id NOT IN (SELECT plan FROM jobs)').fetchone()[0] >= 64:
                    raise ServiceError('busy', 'Too many active previews. Wait ten minutes for previews to expire.')
                plan_id = str(uuid.uuid4())
                self.db.execute('INSERT INTO plans VALUES(?,?,?,?)',
                                (plan_id, now + 600, canonical(value['spec']), value['spec_sha256']))
            value.update(plan_id=plan_id, expires_at=timestamp(now + 600), message=REVIEW)
            return value

    def _row(self, job_id):
        row = self.db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone() if self.db else None
        if row is None:
            raise ServiceError('not_found', 'Local LM job not found.')
        return row

    def _output(self, job_id):
        # Only server-created opaque IDs come here, never HTTP path components.
        return self.directory / job_id

    def _snapshot(self, row):
        if row['result']:
            return json.loads(row['result'])
        return evidence(self._output(row['id']))[0]

    def _job(self, row):
        result = self._snapshot(row)
        events, _ = journal(self._output(row['id']))
        reserved = min(126, sum(e.get('kind') == 'reservation' for e in events))
        phase = 'queued'
        if row['status'] == 'running':
            phase = 'verifying'
        if any(e['kind'] == 'reservation' for e in events):
            phase = 'development'
        if any(e['kind'] == 'freeze' for e in events):
            phase = 'freeze'
        if any(e['kind'] == 'reservation' and e.get('split') == 'heldout' for e in events):
            phase = 'heldout'
        if row['status'] in TERMINAL:
            phase = 'finalizing' if result['report'] is not None else 'unknown'
        return dict(id=row['id'], spec_sha256=row['hash'], created_at=row['created'],
                    updated_at=row['updated'], status=row['status'], reason=row['reason'], phase=phase,
                    progress=dict(reserved_attempts=reserved, finished_attempts=len(result['attempts']),
                                  max_attempts=126),
                    result_available=row['status'] in TERMINAL and bool(result['attempts'] or result['interrupted_attempts']),
                    selected_delta_available=row['status'] == 'completed' and row['delta'] is not None)

    def jobs(self):
        with self.lock:
            return [self._job(row) for row in self.db.execute(
                'SELECT * FROM jobs ORDER BY created DESC, rowid DESC LIMIT 20')] if self.db else []

    def job(self, job_id):
        with self.lock:
            return self._job(self._row(job_id))

    def resolve(self, key, spec_hash):
        with self.lock:
            row = self.db.execute('SELECT * FROM jobs WHERE key=?', (key,)).fetchone() if self.db else None
            if row is None:
                raise ServiceError('not_found', 'No admission exists for this exact pending request.')
            if row['hash'] != spec_hash:
                raise ServiceError('conflict', 'This idempotency key belongs to another specification.')
            return self._job(row)

    def _bytes(self):
        # Only the private evidence directory; never the configured model cache.
        total = 0
        for root, dirs, files in os.walk(self.directory, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
            for name in files:
                path = Path(root) / name
                try:
                    if not path.is_symlink():
                        total += path.stat().st_size
                except FileNotFoundError:
                    # atomic_json publishes with rename while the monitor scans.
                    # A listed temporary name may disappear before stat; count the
                    # published name on the next scan, within the reserved quota.
                    continue
        return total

    def start(self, plan_id, spec_hash, key):
        with self.lock:
            # Reconciliation precedes expiry/readiness/storage: no new execution.
            if self.db:
                old = self.db.execute('SELECT * FROM jobs WHERE key=?', (key,)).fetchone()
                if old:
                    if old['plan'] != plan_id or old['hash'] != spec_hash:
                        raise ServiceError('conflict', 'Idempotency key is already bound to a different plan or specification.')
                    return self._job(old), False
            reason = self.readiness()
            if reason:
                raise ServiceError('unavailable', reason)
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                row = self.db.execute('SELECT * FROM plans WHERE id=?', (plan_id,)).fetchone()
                if row is None or row['expires'] <= self.clock():
                    raise ServiceError('plan_expired', 'Preview expired. Review a fresh preview before starting.')
                if row['hash'] != spec_hash or row['spec'] != canonical(approved_spec().to_dict()):
                    raise ServiceError('conflict', 'Preview specification does not match the start request.')
                if self.active or self.db.execute("SELECT 1 FROM jobs WHERE status NOT IN "
                        "('completed','failed','cancelled','interrupted')").fetchone():
                    raise ServiceError('busy', 'One local Qwen run is active. Wait for it to finish or cancel it.')
                if self.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] >= 20 or self._bytes() + RUN_RESERVATION > MAX_EVIDENCE:
                    raise ServiceError('storage_full', 'Local LM evidence storage is full. Archive it as an operator before a new run.')
                job_id = str(uuid.uuid4())
                now = timestamp()
                self.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,NULL,NULL)',
                                (job_id, key, plan_id, spec_hash, now, now, 'queued', None))
            # Reservation is fsynced by SQLite FULL commit BEFORE any launch.
            self.active = job_id
            self.cancel_event.clear()
            self.thread = threading.Thread(target=self._execute, args=(job_id,), daemon=True)
            try:
                self.thread.start()
            except Exception:
                self.thread = None
                self.active = None
                self._update(job_id, 'failed', 'worker_launch_failed',
                             dict(report=None, attempts=[], interrupted_attempts=0))
            return self._job(self._row(job_id)), True

    def _update(self, job_id, status, reason=None, result=None, delta=None):
        with self.db:
            self.db.execute('UPDATE jobs SET status=?,reason=?,updated=?,result=?,delta=? WHERE id=?',
                            (status, reason, timestamp(), canonical(result) if result is not None else None,
                             canonical(delta) if delta is not None else None, job_id))

    def _stop(self, child):
        # Signals only our live Popen object, never a stored/recycled PID.
        if child.poll() is None:
            try:
                child.send_signal(signal.SIGINT)
                child.wait(timeout=self.grace)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=1)
        child.wait(timeout=0)

    def _execute(self, job_id):
        start = time.monotonic()
        output = self._output(job_id)
        reason = None
        stopped = False
        cleanup = True
        returncode = None
        try:
            output.mkdir(mode=0o700)
            for stage in ('task', 'selected-reload'):
                with self.lock:
                    if self.cancel_event.is_set():
                        stopped = True
                        break
                    self._update(job_id, 'running')
                    self.child = self.adapter.launch(output, stage, self.guard.fileno())
                    child = self.child
                while child.poll() is None:
                    if self.cancel_event.wait(0.05):
                        stopped = True
                        break
                    if time.monotonic() - start >= max(0, self.seconds - self.grace - 1):
                        reason = 'deadline_exceeded'
                        stopped = True
                        break
                    if self._bytes() >= MAX_EVIDENCE - 2 * MAX_RESPONSE:
                        reason = 'storage_full'
                        stopped = True
                        break
                if stopped:
                    self._stop(child)
                    break
                returncode = child.wait()
                self.child = None
                if returncode != 0:
                    break
                raw = read_json(output / 'run/report.json')
                if stage == 'selected-reload' or raw.get('selected_delta_check') is None:
                    break
                # No simultaneous loaded models. First child exited and was waited.
        except Exception:
            reason = 'worker_failed'
        finally:
            if self.child is not None:
                try:
                    self._stop(self.child)
                except Exception:
                    cleanup = False
                if cleanup:
                    self.child = None
            result, complete, assessment_reason, delta = evidence(output)
            if reason == 'worker_failed' and assessment_reason == 'invalid_evidence':
                reason = 'invalid_evidence'
            # Persist bounded, validated snapshots. No raw logs/runtime/error messages.
            if len(canonical(result).encode()) > MAX_RESPONSE:
                result, complete, assessment_reason, delta = dict(report=None, attempts=[], interrupted_attempts=0), False, 'invalid_evidence', None
            if time.monotonic() - start >= self.seconds:
                reason = reason or 'deadline_exceeded'
            with self.lock:
                if not cleanup:
                    status, reason = 'interrupted', 'cleanup_unknown'
                    self.setup_error = 'Worker cleanup could not be established. Admission is blocked; operator investigation is required.'
                elif self.cancel_event.is_set():
                    status, reason = 'cancelled', 'cancelled_by_user' if not self.closed else 'service_shutdown'
                elif reason:
                    status = 'failed'
                elif complete and returncode == 0:
                    status, reason = 'completed', None
                else:
                    status, reason = 'failed', assessment_reason or 'worker_failed'
                if status != 'completed':
                    delta = None
                    if result['report']:
                        result['report']['status'], result['report']['verdict'] = 'incomplete', 'not_evaluated'
                self._update(job_id, status, reason, result, delta)
                self.active = None

    def cancel(self, job_id):
        with self.lock:
            row = self._row(job_id)
            if row['status'] not in TERMINAL:
                if self.active != job_id or not self.owner:
                    raise ServiceError('unavailable', 'Worker ownership is unknown. Admission is blocked; inspect the local service.')
                self.cancel_event.set()
                self._update(job_id, 'cancelling')
                row = self._row(job_id)
            return self._job(row)

    def result(self, job_id):
        with self.lock:
            row = self._row(job_id)
            if row['status'] not in TERMINAL:
                raise ServiceError('conflict', 'Run is still active. Wait until the owned worker has stopped.')
            return dict(schema_version=1, job=self._job(row), **self._snapshot(row))

    def export(self, job_id, kind):
        with self.lock:
            row = self._row(job_id)
            job = self._job(row)
            if row['status'] not in TERMINAL or not job['result_available']:
                raise ServiceError('conflict', 'Stopped-run evidence is not yet available.')
            if kind == 'evidence':
                value = self.result(job_id)
            elif row['status'] == 'completed' and row['delta'] is not None:
                from .local_delta import validate
                # Download bytes are directly consumable by local_delta.load_delta.
                # Job/spec provenance and instructions belong outside this fixed schema.
                value = validate(json.loads(row['delta']))
            else:
                raise ServiceError('conflict', 'No independently verified selected delta exists for this run.')
            if len(canonical(value).encode()) > MAX_RESPONSE:
                raise ServiceError('internal', 'Evidence exceeds the safe download bound; inspect it locally.')
            return value

    def close(self):
        with self.lock:
            self.closed = True
            if self.active:
                self.cancel_event.set()
                self._update(self.active, 'cancelling')
        if self.thread:
            self.thread.join(timeout=self.grace + 4)
        with self.lock:
            # Do not release the ownership fence while a monitor can still launch.
            if self.thread and self.thread.is_alive():
                return
            if self.db:
                self.db.close()
                self.db = None
            if self.guard:
                self.guard.close()
                self.guard = None
            self.owner = False
