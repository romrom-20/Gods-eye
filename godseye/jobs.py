"""Single-worker local queue. Durable status, bounded work, cooperative cancellation."""
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import threading
import time
import uuid

from .storage import write_json


class Cancelled(Exception):
    pass


class QueueFull(Exception):
    pass


class Conflict(Exception):
    pass


class JobQueue:
    def __init__(self, store, capacity=4):
        self.store = store
        self.capacity = capacity
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='godseye')
        self.events = {}
        self.rows = {}
        self.closed = False
        for path in store.path.glob('job-*.json'):
            row = json.loads(path.read_text())
            if row['status'] in ('queued', 'running', 'cancelling'):
                row.update(status='interrupted', finished=time.time(),
                           error='Server stopped before completion. Submit a new job.')
                write_json(path, row)
            self.rows[row['id']] = row

    def _save(self, row):
        write_json(self.store.path / ('job-' + row['id'] + '.json'), row)

    def submit(self, settings, key=None):
        fingerprint = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()
        with self.lock:
            if self.closed:
                raise QueueFull('Worker is shutting down')
            if key:
                for row in self.rows.values():
                    if row.get('idempotency_key') == key:
                        if row['fingerprint'] != fingerprint:
                            raise Conflict('Idempotency key already used with different settings')
                        return copy.deepcopy(row)
            if sum(r['status'] in ('queued', 'running', 'cancelling')
                   for r in self.rows.values()) >= self.capacity:
                raise QueueFull('Local queue is full. Wait for a job to finish.')
            row = dict(id=uuid.uuid4().hex[:16], status='queued', created=time.time(),
                       completed=0, total=2 * settings['episodes'], settings=settings,
                       fingerprint=fingerprint, idempotency_key=key, run_id=None)
            self.rows[row['id']] = row
            self.events[row['id']] = threading.Event()
            self._save(row)
            self.pool.submit(self._run, row['id'])
            return copy.deepcopy(row)

    def get(self, job_id):
        with self.lock:
            return copy.deepcopy(self.rows[job_id])

    def list(self):
        with self.lock:
            return copy.deepcopy(sorted(self.rows.values(), key=lambda r: r['created'], reverse=True)[:30])

    def cancel(self, job_id):
        with self.lock:
            row = self.rows[job_id]
            if row['status'] in ('queued', 'running', 'cancelling'):
                self.events[job_id].set()
                if row['status'] == 'queued':
                    row.update(status='cancelled', finished=time.time())
                else:
                    row['status'] = 'cancelling'
                self._save(row)
            return copy.deepcopy(row)

    def _run(self, job_id):
        with self.lock:
            row = self.rows[job_id]
            event = self.events[job_id]
            if event.is_set():
                self.events.pop(job_id, None)
                return
            row.update(status='running', started=time.time())
            self._save(row)

        def check_cancel():
            if event.is_set():
                raise Cancelled()

        def progress(completed, total):
            with self.lock:
                row.update(completed=completed, total=total)
                self._save(row)

        try:
            result = self.store.run(**row['settings'], check_cancel=check_cancel, progress=progress)
            # Once the result is durably published, success wins a late cancellation race.
            with self.lock:
                row.update(status='succeeded', run_id=result['id'])
        except Cancelled:
            with self.lock:
                row['status'] = 'cancelled'
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Evaluation job failed: %s', job_id)
            with self.lock:
                row.update(status='failed', error='Evaluation failed. Check the local server log.')
        finally:
            with self.lock:
                row['finished'] = time.time()
                self._save(row)
                self.events.pop(job_id, None)

    def close(self):
        with self.lock:
            self.closed = True
            for event in self.events.values():
                event.set()
        self.pool.shutdown(wait=True)
