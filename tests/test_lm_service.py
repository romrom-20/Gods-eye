"""Synthetic control-plane acceptance; no pretrained execution or quality claims."""
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import uvicorn

from godseye.lm.local_task_runner import approved_spec
from godseye.lm.service import LMService, ServiceError
from godseye.lm.service_api import lm_router
from godseye.lm.service_worker import LocalWorker
from godseye.server import Boundary, create_app

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/lm_service/worker.py'
BASE = '/api/v1/lm'


class ScriptedAdapter:
    """Explicitly synthetic leaf process implementing the same adapter seam."""
    def __init__(self, mode='hold'):
        self.mode = mode
        self.children = []
        self.checks = 0

    def readiness(self):
        self.checks += 1
        return None

    def launch(self, output, stage, guard_fd):
        child = subprocess.Popen([sys.executable, str(FIXTURE), self.mode, stage, str(output)],
                                 cwd=ROOT, env=dict(os.environ, PYTHONPATH=str(ROOT)),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 pass_fds=(guard_fd,), start_new_session=True)
        self.children.append(child)
        return child


def app_for(service, readonly=False, token=None):
    app = FastAPI()
    app.include_router(lm_router(service, readonly=readonly))
    app.add_middleware(Boundary, hosts=['127.0.0.1', 'testserver'], token=token)
    return app


def wait_for(predicate, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError('synthetic service did not reach expected state')


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.services = []
        self.addCleanup(self.close_services)
        self.worker = ScriptedAdapter()
        self.service = self.new_service(self.worker)
        self.client = TestClient(app_for(self.service))
        self.addCleanup(self.client.close)

    def close_services(self):
        for service in reversed(self.services):
            service.close()

    def new_service(self, adapter, name='private', **kwargs):
        service = LMService(self.root / name, adapter=adapter, grace=.05, **kwargs)
        self.services.append(service)
        return service

    def post(self, route, **fields):
        return self.client.post(BASE + route, json=dict(schema_version=1, **fields))

    def preview(self):
        response = self.post('/plan', request='Improve JSON schema adherence')
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def pending(self):
        plan = self.preview()
        return dict(plan_id=plan['plan_id'], spec_sha256=plan['spec_sha256'], idempotency_key=str(uuid.uuid4()))

    def start(self, **kwargs):
        pending = self.pending()
        response = self.post('/jobs', **pending)
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()['job']['id'], pending

    def terminal(self, job_id):
        return wait_for(lambda: (lambda j: j if j['status'] in
                        ('completed', 'failed', 'cancelled', 'interrupted') else None)(self.service.job(job_id)))

    def ready_child(self, job_id):
        wait_for(lambda: (self.root / 'private' / job_id / 'ready').exists())
        return self.worker.children[-1]

    def test_inert_exact_capabilities_preview_and_expiry(self):
        with patch('socket.socket.connect', side_effect=AssertionError('network')):
            caps = self.client.get(BASE + '/capabilities').json()
            for _ in range(2):
                plan = self.preview()
        self.assertEqual(set(caps), {'schema_version', 'available', 'readonly', 'reason', 'model',
                         'execution', 'supported_goal', 'sample_request', 'limits'})
        self.assertEqual(caps['limits'], dict(max_attempts=126, max_new_tokens=96,
                                             max_worker_seconds=1800, max_concurrency=1))
        self.assertTrue(caps['available'])
        self.assertEqual(set(plan), {'schema_version', 'outcome', 'message', 'plan_id', 'expires_at',
                                    'spec_sha256', 'spec'})
        self.assertEqual(plan['spec'], approved_spec().to_dict())
        self.assertEqual(self.worker.children, [])
        self.assertEqual(self.worker.checks, 1)
        unsupported = self.post('/plan', request='Make it all clever').json()
        self.assertEqual(unsupported['outcome'], 'unsupported')
        self.assertIsNone(unsupported['plan_id'])
        self.assertEqual(self.post('/plan', request='better json please').json()['outcome'], 'clarification_required')
        with self.service.db:
            self.service.db.execute('UPDATE plans SET expires=0')
        expired = self.post('/jobs', plan_id=plan['plan_id'], spec_sha256=plan['spec_sha256'], idempotency_key=str(uuid.uuid4()))
        self.assertEqual(expired.status_code, 409)
        self.assertEqual(expired.json()['code'], 'plan_expired')
        self.assertEqual(self.worker.children, [])

    def test_simultaneous_duplicate_start_lost_ack_and_no_backlog(self):
        pending = self.pending()
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: self.post('/jobs', **pending), range(2)))
        self.assertEqual(sorted(r.status_code for r in results), [200, 202])
        ids = {r.json()['job']['id'] for r in results}
        self.assertEqual(len(ids), 1)
        job_id = ids.pop()
        self.ready_child(job_id)
        self.assertEqual(len(self.worker.children), 1)
        self.assertEqual(set(results[0].json()['job']), {'id', 'spec_sha256', 'created_at', 'updated_at',
                         'status', 'reason', 'phase', 'progress', 'result_available', 'selected_delta_available'})
        resolved = self.post('/resolve', spec_sha256=pending['spec_sha256'], idempotency_key=pending['idempotency_key'])
        self.assertEqual(resolved.json()['job']['id'], job_id)
        self.assertEqual(self.post('/resolve', spec_sha256='0' * 64,
                         idempotency_key=pending['idempotency_key']).status_code, 409)
        self.assertEqual(self.post('/resolve', spec_sha256=pending['spec_sha256'],
                         idempotency_key=str(uuid.uuid4())).status_code, 404)
        changed = dict(pending, plan_id=self.preview()['plan_id'])
        self.assertEqual(self.post('/jobs', **changed).status_code, 409)
        self.assertEqual(self.post('/jobs', **dict(pending, spec_sha256='0' * 64)).status_code, 409)
        other = self.pending()
        self.assertEqual(self.post('/jobs', **other).status_code, 429)
        self.assertEqual(len(self.service.jobs()), 1)
        with self.service.db:
            self.service.db.execute('UPDATE plans SET expires=0')
        self.assertEqual(self.post('/jobs', **pending).json()['job']['id'], job_id)
        self.assertEqual(self.client.get(BASE + '/jobs/' + job_id + '/result').status_code, 409)
        self.post('/jobs/' + job_id + '/cancel')
        self.terminal(job_id)

    def test_cancel_waits_kills_and_retains_partial_evidence(self):
        job_id, _ = self.start()
        child = self.ready_child(job_id)
        response = self.post('/jobs/' + job_id + '/cancel')
        self.assertEqual(response.json()['job']['status'], 'cancelling')
        self.assertEqual(self.post('/jobs/' + job_id + '/cancel').status_code, 200)
        terminal = self.terminal(job_id)
        self.assertEqual(terminal['status'], 'cancelled')
        self.assertEqual(child.returncode, -signal.SIGKILL)
        self.assertEqual(child.wait(timeout=0), -signal.SIGKILL)
        result = self.client.get(BASE + '/jobs/' + job_id + '/result').json()
        self.assertEqual(result['interrupted_attempts'], 1)
        self.assertIsNone(result['report'])
        exported = self.post('/jobs/' + job_id + '/export', kind='evidence')
        self.assertEqual(exported.status_code, 200)
        self.assertIn('attachment;', exported.headers['content-disposition'])
        self.assertEqual(exported.json()['interrupted_attempts'], 1)
        self.assertEqual(self.post('/jobs/' + job_id + '/export', kind='selected_delta').status_code, 409)
        self.assertEqual(self.post('/jobs/' + job_id + '/cancel').json()['job'], terminal)
        self.assertNotIn(str(self.root), exported.text)

    def test_deadline_terminates_and_waits_owned_process(self):
        self.service.seconds = 1.3  # Leaves a small positive execution window before cleanup reserve.
        job_id, _ = self.start()
        self.ready_child(job_id)
        terminal = self.terminal(job_id)
        self.assertEqual((terminal['status'], terminal['reason']), ('failed', 'deadline_exceeded'))
        self.assertIsNotNone(self.worker.children[0].returncode)
        self.worker.children[0].wait(timeout=0)

    def test_clean_shutdown_and_restart_never_resume(self):
        job_id, pending = self.start()
        child = self.ready_child(job_id)
        self.service.close()
        self.assertIsNotNone(child.returncode)
        recovered = self.new_service(ScriptedAdapter())
        self.assertEqual(recovered.job(job_id)['status'], 'cancelled')
        self.assertEqual(recovered.resolve(pending['idempotency_key'], pending['spec_sha256'])['id'], job_id)
        self.assertEqual(recovered.adapter.children, [])

    def test_restart_reconciles_unlaunched_reservation_and_partial_crash(self):
        pending = self.pending()
        # Simulate server loss after durable reservation but before creating the thread.
        with patch('threading.Thread.start'):
            job_id = self.service.start(pending['plan_id'], pending['spec_sha256'], pending['idempotency_key'])[0]['id']
        self.service.active = None
        self.service.thread = None
        self.service.close()
        recovered = self.new_service(ScriptedAdapter())
        self.assertEqual(recovered.job(job_id)['status'], 'interrupted')
        self.assertEqual(recovered.start(**dict(plan_id=pending['plan_id'], spec_hash=pending['spec_sha256'],
                         key=pending['idempotency_key']))[1], False)
        self.assertEqual(recovered.adapter.children, [])

    def test_second_service_fenced_even_after_server_process_crash(self):
        # A separate synthetic service owner is SIGKILLed; its child inherits the lock.
        directory = self.root / 'crashed-owner'
        code = '''
import sys,time
sys.path.insert(0, 'tests')
from test_lm_service import ScriptedAdapter
from godseye.lm.service import LMService
s=LMService(sys.argv[1],adapter=ScriptedAdapter())
p=s.plan('Improve JSON schema adherence')
j,_=s.start(p['plan_id'],p['spec_sha256'],'11111111-1111-4111-8111-111111111111')
while not (s.directory / j['id'] / 'ready').exists(): time.sleep(.02)
print(str(s.child.pid)+' '+j['id'],flush=True)
time.sleep(30)
'''
        owner = subprocess.Popen([sys.executable, '-c', code, str(directory)], cwd=ROOT,
                                 env=dict(os.environ, PYTHONPATH=str(ROOT)), stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: owner.poll() is None and owner.kill())
        self.addCleanup(owner.stdout.close)
        line = owner.stdout.readline().strip()
        self.assertTrue(line)
        pid, job_id = line.split()
        owner.kill()
        owner.wait(timeout=3)
        fenced = self.new_service(ScriptedAdapter(), name='crashed-owner')
        self.assertFalse(fenced.capabilities()['available'])
        with self.assertRaises(ServiceError):
            fenced.plan('Improve JSON schema adherence')
        self.assertEqual(fenced.adapter.children, [])
        # Test owns this explicitly created synthetic process; service never kills stored PIDs.
        os.kill(int(pid), signal.SIGKILL)
        fenced.close()
        # On POSIX a zombie has closed descriptors, so lock release proves resource quiescence.
        def lock_released():
            with open(directory / 'owner.lock', 'r+') as guard:
                try:
                    fcntl.flock(guard.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return True
                except BlockingIOError:
                    return False
        wait_for(lock_released)
        recovered = self.new_service(ScriptedAdapter(), name='crashed-owner')
        self.assertTrue(recovered.owner)
        self.assertEqual(recovered.job(job_id)['status'], 'interrupted')
        self.assertEqual(recovered.adapter.children, [])
        owner.stdout.close()

    def test_readonly_host_origin_token_content_and_strict_json(self):
        readonly = TestClient(app_for(self.service, readonly=True))
        self.addCleanup(readonly.close)
        self.assertTrue(readonly.get(BASE + '/capabilities').json()['readonly'])
        for route, body in [('/plan', {'request': 'Improve JSON schema adherence'}),
                            ('/jobs', {}), ('/jobs/unknown/cancel', {}), ('/jobs/unknown/export', {'kind':'evidence'})]:
            self.assertEqual(readonly.post(BASE + route, json=dict(schema_version=1, **body)).status_code, 403)
        token = TestClient(app_for(self.service, token='private-token'))
        self.addCleanup(token.close)
        self.assertEqual(token.get(BASE + '/capabilities').status_code, 401)
        self.assertEqual(token.get(BASE + '/capabilities', headers={'Authorization':'Bearer private-token'}).status_code, 200)
        for headers in ({'Host':'evil.test'}, {'Origin':'https://evil.test'}, {'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.client.get(BASE + '/capabilities', headers=headers).status_code, 403)
        self.assertEqual(self.client.post(BASE + '/plan', content='{}').status_code, 415)
        for raw in ('{"schema_version":1,"request":"x","request":"y"}',
                    '{"schema_version":true,"request":"x"}',
                    '{"schema_version":1,"request":1}',
                    '{"schema_version":1,"request":"x","path":"secret"}',
                    '[]', '{', '{"schema_version":1,"request":"x","x":NaN}'):
            response = self.client.post(BASE + '/plan', content=raw, headers={'content-type':'application/json'})
            self.assertEqual(response.status_code, 422, response.text)
            self.assertEqual(response.json()['code'], 'invalid_request')
        self.assertEqual(self.client.post(BASE + '/plan', content=' ' * 65537,
                         headers={'content-type':'application/json'}).status_code, 413)
        self.assertEqual(self.worker.children, [])

    def test_bounded_previews_history_and_storage(self):
        for _ in range(64):
            self.preview()
        self.assertEqual(self.post('/plan', request='Improve JSON schema adherence').status_code, 429)
        with self.service.db:
            self.service.db.execute('DELETE FROM plans')
        pending = self.pending()
        with patch.object(self.service, '_bytes', return_value=256 * 1024**2):
            self.assertEqual(self.post('/jobs', **pending).status_code, 507)
        self.assertEqual(self.worker.children, [])
        with self.service.db:
            for i in range(20):
                self.service.db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4()),approved_spec().sha256,
                     str(i),str(i),'interrupted','synthetic',None,None))
        self.assertEqual(len(self.client.get(BASE + '/jobs').json()['jobs']), 20)
        self.assertEqual(self.post('/jobs', **pending).status_code, 507)

    def test_evaluation_complete_negative_incomplete_selected_and_fail_closed(self):
        for mode, status, reason, delta_available in [
            ('complete', 'completed', None, False),
            ('incomplete', 'failed', 'budget_limited', False),
            ('selected', 'completed', None, True),
            ('selected-bad', 'failed', 'invalid_evidence', False),
            ('rollback', 'failed', 'rollback_failed', False),
            ('malformed', 'failed', 'invalid_evidence', False),
            ('crash', 'failed', 'worker_crash', False),
        ]:
            with self.subTest(mode=mode):
                self.worker.mode = mode
                job_id, _ = self.start()
                job = self.terminal(job_id)
                self.assertEqual((job['status'], job['reason']), (status, reason))
                self.assertEqual(job['selected_delta_available'], delta_available)
                result = self.client.get(BASE + '/jobs/' + job_id + '/result').json()
                self.assertEqual(set(result), {'schema_version', 'job', 'report', 'attempts', 'interrupted_attempts'})
                if mode == 'complete':
                    self.assertEqual(result['report']['verdict'], 'no_improvement')
                    self.assertEqual(len(result['attempts']), 112)
                if mode == 'incomplete':
                    self.assertEqual(result['report']['verdict'], 'not_evaluated')
                    self.assertEqual(len(result['attempts']), 70)
                if delta_available:
                    self.assertEqual(len(result['attempts']), 126)
                    download = self.post('/jobs/' + job_id + '/export', kind='selected_delta')
                    self.assertEqual(download.status_code, 200)
                    self.assertEqual(download.json()['delta']['column'], 0)
                    self.assertIn('local_delta.applied', download.json()['instructions'])
                else:
                    self.assertEqual(self.post('/jobs/' + job_id + '/export', kind='selected_delta').status_code, 409)
                self.assertNotIn(str(self.root), json.dumps(result))
        self.assertEqual(self.client.get(BASE + '/jobs/../../source.json/result').status_code, 404)
        self.assertEqual(self.post('/jobs/unknown/export', kind='../../source.json').status_code, 422)

    def test_unavailable_sanitized_and_server_attachment(self):
        unavailable = LMService()
        self.addCleanup(unavailable.close)
        client = TestClient(app_for(unavailable))
        self.addCleanup(client.close)
        caps = client.get(BASE + '/capabilities').json()
        self.assertFalse(caps['available'])
        self.assertIn('GODSEYE_LM_CACHE', caps['reason'])
        self.assertEqual(client.post(BASE + '/plan', json={'schema_version':1,
                         'request':'Improve JSON schema adherence'}).status_code, 503)
        from godseye.core import Store
        with TestClient(create_app(Store(self.root / 'lab'), lm_service=unavailable)) as attached:
            self.assertEqual(attached.get(BASE + '/capabilities').status_code, 200)
            self.assertEqual(attached.get('/api/v1/state').status_code, 200)

    def test_base_import_metadata_readiness_and_leaf_launch(self):
        code = "import sys; from godseye.lm.service import LMService; assert 'torch' not in sys.modules and 'numpy' not in sys.modules"
        result = subprocess.run([sys.executable, '-S', '-c', code], capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        from godseye.lm.local_runtime import FILES, REVISION, VERSIONS, WEIGHT_BYTES
        cache = self.root / 'synthetic-cache'
        cache.mkdir()
        entries = []
        for name in FILES:
            size = WEIGHT_BYTES if name == 'model.safetensors' else 0
            with (cache / name).open('wb') as stream:
                stream.truncate(size)  # Sparse synthetic file; never read/hash/load it.
            entries.append(dict(rfilename=name, size=size))
        (cache / 'source.json').write_text(json.dumps(dict(sha=REVISION, siblings=entries)))
        worker = LocalWorker(cache, sys.executable)
        with patch('godseye.lm.service_worker.subprocess.run') as probe:
            probe.return_value.stdout = json.dumps(VERSIONS).encode()
            self.assertIsNone(worker.readiness())
            self.assertIn('-I', probe.call_args.args[0])
            self.assertNotIn('import torch', probe.call_args.args[0][-1])
            probe.return_value.stdout = b'{}'
            self.assertIn('pinned local runtime packages', worker.readiness())
        with patch('godseye.lm.service_worker.subprocess.Popen') as launch:
            with patch.dict(os.environ, {'PROVIDER_KEY':'secret-canary', 'HF_TOKEN':'secret-canary'}):
                worker.launch(self.root / 'out', 'task', self.service.guard.fileno())
            args, opts = launch.call_args
            self.assertIn('--worker', args[0])
            self.assertEqual(opts['pass_fds'], (self.service.guard.fileno(),))
            self.assertNotIn('secret-canary', repr(opts['env']))
        unsafe = LMService(cache / 'evidence', cache=cache, python=sys.executable)
        self.services.append(unsafe)
        self.assertFalse(unsafe.capabilities()['available'])
        self.assertFalse((cache / 'evidence').exists())

    def test_launch_and_cleanup_failures_block_honestly(self):
        with patch.object(self.worker, 'launch', side_effect=OSError('/private/secret-canary')):
            job_id, _ = self.start()
            job = self.terminal(job_id)
            self.assertEqual((job['status'],job['reason']), ('failed','worker_failed'))
            self.assertNotIn('secret-canary', json.dumps(job))
        class UnverifiableProcess:
            def poll(self): return None
            def send_signal(self, _): raise OSError('synthetic cleanup unknown')
            def wait(self, timeout=None): raise subprocess.TimeoutExpired('synthetic', timeout)
            def kill(self): raise OSError('synthetic cleanup unknown')
        self.service.seconds = 1.1
        with patch.object(self.worker, 'launch', return_value=UnverifiableProcess()):
            job_id, _ = self.start()
            job = self.terminal(job_id)
        self.assertEqual((job['status'],job['reason']), ('interrupted','cleanup_unknown'))
        self.assertFalse(self.service.capabilities()['available'])
        self.assertIsNone(self.service.result(job_id)['report'])
        self.assertEqual(self.post('/plan', request='Improve JSON schema adherence').status_code, 503)

    def test_real_ephemeral_http_start_resolve_cancel(self):
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app_for(self.service), log_level='error', lifespan='off'))
        thread = threading.Thread(target=server.run, kwargs={'sockets':[sock]}, daemon=True)
        thread.start()
        try:
            wait_for(lambda: server.started)
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', trust_env=False) as client:
                plan = client.post(BASE + '/plan', json=dict(schema_version=1, request='Improve JSON schema adherence')).json()
                pending = dict(schema_version=1, plan_id=plan['plan_id'], spec_sha256=plan['spec_sha256'], idempotency_key=str(uuid.uuid4()))
                with ThreadPoolExecutor(2) as pool:
                    starts = list(pool.map(lambda _: client.post(BASE + '/jobs', json=pending), range(2)))
                self.assertEqual(sorted(r.status_code for r in starts), [200,202])
                job_id = starts[0].json()['job']['id']
                self.ready_child(job_id)
                resolved = client.post(BASE + '/resolve', json={k:v for k,v in pending.items() if k != 'plan_id'})
                self.assertEqual(resolved.json()['job']['id'], job_id)
                cancelled = client.post(BASE + '/jobs/' + job_id + '/cancel', json={'schema_version':1})
                self.assertEqual(cancelled.json()['job']['status'], 'cancelling')
                self.assertEqual(self.terminal(job_id)['status'], 'cancelled')
                self.assertIsNotNone(self.worker.children[0].returncode)
                self.assertEqual(len(self.worker.children), 1)
        finally:
            server.should_exit = True
            thread.join(timeout=3)
            sock.close()
        self.assertFalse(thread.is_alive())


if __name__ == '__main__':
    unittest.main()
