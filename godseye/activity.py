"""Trusted local activity journal, separate from the experiment v1 wire schema.

Only evaluator/worker code writes this database, inside private evaluator state.
No strings supplied by a provider, browser, or tool argument are recorded.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import uuid

from .experiment_spec import ContractError

KINDS = frozenset(('worker_started', 'worker_finished', 'worker_failed', 'worker_cancelled',
    'operation_started', 'activity_finished', 'activity_failed', 'activity_unknown',
    'root_probe_reserved', 'candidate_probe_reserved', 'edit_started', 'held_out_reserved',
    'selection_frozen'))
OPERATIONS = frozenset(('worker', 'list', 'read', 'patch', 'evaluate', 'freeze', 'report'))
ARMS = frozenset(('agent', 'unchanged', 'heuristic', 'administrator', 'worker'))
PHASES = dict(root_probe_reserved='checking_original', candidate_probe_reserved='trying_edit',
              edit_started='trying_edit', held_out_reserved='testing')
MAX_SEQUENCE = 2**53 - 1


class Journal:
    def __init__(self, directory):
        self.path = Path(directory) / 'activity.sqlite3'
        self.lost = self.path.with_suffix('.lost')

    @contextmanager
    def connection(self):
        # Never create a journal as a side effect of an observation/read.
        db = sqlite3.connect(self.path.resolve().as_uri() + '?mode=rw', uri=True, timeout=5)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def initialize(self, run_id, spec_hash):
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with self.connection() as db:
            db.executescript('''CREATE TABLE scope (run TEXT, hash TEXT, terminal INTEGER DEFAULT 0);
                CREATE TABLE events (sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT, operation TEXT, arm TEXT, count INTEGER);
                CREATE TABLE active (id TEXT PRIMARY KEY);''')
            db.execute('INSERT INTO scope(run,hash) VALUES (?, ?)', (run_id, spec_hash))

    def emit(self, kind, operation, arm, *, count=None, begin=None, end=None):
        if kind not in KINDS or operation not in OPERATIONS or arm not in ARMS:
            raise ValueError('Unsupported trusted observation')
        if count is not None and (type(count) is not int or not 0 <= count <= 256):
            raise ValueError('Unsupported measured count')
        try:
            with self.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT terminal FROM scope').fetchone()[0]:
                    return  # A terminal fence rejects late and replayed observations.
                if kind in ('worker_finished', 'worker_failed', 'worker_cancelled'):
                    db.execute('UPDATE scope SET terminal=1')
                    db.execute('DELETE FROM active')
                if begin:
                    db.execute('INSERT INTO active VALUES (?)', (begin,))
                if end:
                    db.execute('DELETE FROM active WHERE id=?', (end,))
                active = db.execute('SELECT count(*) FROM active').fetchone()[0]
                if active > 1 or end and active:
                    kind = 'activity_unknown'
                db.execute('INSERT INTO events(kind,operation,arm,count) VALUES (?,?,?,?)',
                           (kind, operation, arm, count))
        except Exception:
            # Fail closed; an already persisted evaluator reservation stays consumed.
            self.lost.touch(mode=0o600)
            raise

    @contextmanager
    def operation(self, operation, arm):
        if not self.path.exists():
            yield lambda *a, **kw: None
            return
        identifier = uuid.uuid4().hex
        self.emit('operation_started', operation, arm, begin=identifier)
        try:
            yield lambda kind, **kw: self.emit(kind, operation, arm, **kw)
        except BaseException:
            self.emit('activity_failed', operation, arm, end=identifier)
            raise
        else:
            self.emit('activity_finished', operation, arm, end=identifier)

    def read(self, run_id, spec_hash, status, after=0, limit=50, *, gap_fence=0):
        unknown = dict(name='unknown', event_sequence=None)
        result = dict(schema_version=1, experiment_id=run_id, spec_hash=spec_hash,
                      available=False, status=status, phase=unknown, events=[],
                      next_cursor=after, high_water=0, gap=False, has_more=False)
        if not self.path.exists():
            result.update(next_cursor=0, gap=bool(after))
            return result
        try:
            with self.connection() as db:
                db.execute('BEGIN')
                if db.execute('SELECT run,hash FROM scope').fetchone() != (run_id, spec_hash):
                    return result
                high = db.execute('SELECT coalesce(max(sequence),0) FROM events').fetchone()[0]
                total = db.execute('SELECT count(*) FROM events WHERE sequence>?', (gap_fence,)).fetchone()[0]
                result['high_water'] = high
                if after > high or total != max(0, high - gap_fence) or self.lost.exists():
                    result['gap'] = True
                    result['next_cursor'] = high
                    result['phase']['event_sequence'] = high or None
                    return result
                if after < gap_fence or gap_fence and high <= gap_fence:
                    result.update(gap=True, next_cursor=gap_fence,
                                  phase=dict(name='unknown', event_sequence=high or None))
                    return result
                rows = db.execute('SELECT sequence,kind,operation,arm,count FROM events '
                                  'WHERE sequence>? ORDER BY sequence LIMIT ?', (after, limit)).fetchall()
                last = db.execute('SELECT sequence,kind FROM events ORDER BY sequence DESC LIMIT 1').fetchone()
                if any(r[1] not in KINDS or r[2] not in OPERATIONS or r[3] not in ARMS
                       or r[4] is not None and (type(r[4]) is not int or not 0 <= r[4] <= 256)
                       for r in rows) or high > MAX_SEQUENCE:
                    result['gap'] = True
                    result['phase']['event_sequence'] = min(high, MAX_SEQUENCE) or None
                    return result
                result.update(available=True, events=[dict(sequence=r[0], kind=r[1],
                    operation=r[2], arm=r[3], count=r[4]) for r in rows],
                    next_cursor=rows[-1][0] if rows else after,
                    has_more=bool(rows and rows[-1][0] < high))
                if last:
                    result['phase'] = dict(name=PHASES.get(last[1], 'unknown')
                        if status in ('running', 'cancelling') else 'unknown', event_sequence=last[0])
                return result
        except (sqlite3.Error, OSError):
            result['gap'] = True
            return result


def activity_request(value):
    if type(value) is not dict or set(value) != {'schema_version', 'experiment_id', 'spec_hash', 'after', 'limit'}:
        raise ContractError('invalid_schema')
    from .experiment_spec import validate_message
    validate_message('status_request', dict(schema_version=value['schema_version'], experiment_id=value['experiment_id']))
    import re
    if (type(value['spec_hash']) is not str or not re.fullmatch('[0-9a-f]{64}', value['spec_hash'])
            or type(value['after']) is not int or not 0 <= value['after'] <= MAX_SEQUENCE
            or type(value['limit']) is not int or not 1 <= value['limit'] <= 100):
        raise ContractError('invalid_schema')
    return value
