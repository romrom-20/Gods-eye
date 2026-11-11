"""Opt-in integration of DockerWorker itself, with no saved or live credentials."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from godseye.evaluator import Evaluator
from godseye.experiment_spec import ContractError, DEFAULT_CEILINGS
from godseye.orchestration import DockerWorker, Orchestrator


ROOT = Path(__file__).resolve().parents[1]
TEST_IMAGE = 'godseye-worker-scripted:validation'


class DummySettings:
    def credential(self, provider):
        assert provider == 'openai'
        return 'dummy-docker-worker-only'


class ScriptedDockerWorker(DockerWorker):
    # Trusted Python subclass only; no request flag, endpoint, mount or environment
    # override is added to production. Everything else is the real worker.
    def _images(self):
        return dict(super()._images(), agent=TEST_IMAGE)


def docker(*args, **kwargs):
    return subprocess.run(['docker', *args], check=True, capture_output=True,
                          text=True, timeout=120, **kwargs).stdout


def start(service, model='scripted-complete', **limits):
    plan = service.plan(dict(schema_version=1, text='Improve Breakout score',
        provider=dict(name='openai', model=model, routing='price'),
        limits=dict(DEFAULT_CEILINGS, **limits)))
    return service.start(dict(schema_version=1, draft_id=plan['draft_id'],
        spec_hash=plan['spec_hash'], idempotency_key='docker-validation', confirmed=True))


def crash_child(path):
    service = Orchestrator(Path(path) / 'service', worker=ScriptedDockerWorker(ROOT),
                           settings=DummySettings())
    service.register(Path(path) / 'private', baseline_id='docker-baseline',
                     suite_id='breakout-pilot', revision='v1')
    run = start(service)
    (Path(path) / 'run-id').write_text(run['experiment_id'])
    while True:
        time.sleep(1)


@unittest.skipUnless(os.environ.get('GODSEYE_CONTAINER_TEST') == '1' and shutil.which('docker'),
                     'Requires Docker daemon and GODSEYE_CONTAINER_TEST=1')
class DockerWorkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getuid() == 0:
            raise unittest.SkipTest('DockerWorker requires a non-root operator')
        # Explicit opt-in fails if Docker/build is broken; it must not silently skip.
        docker('version', '--format', '{{.Server.Version}}')
        env = {k: v for k, v in os.environ.items() if k in (
            'PATH', 'HOME', 'DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG',
            'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH', 'TMPDIR')}
        env['EVALUATOR_PRIVATE_DIR'] = '/tmp/unused-build-only'
        docker('compose', '--project-name', 'isolation', '--env-file', '/dev/null',
               '-f', str(ROOT / 'isolation/compose.yaml'), 'build',
               'evaluator', 'agent', 'gateway', env=env)
        # No extra source, home, sockets, or private mounts in the test agent.
        with tempfile.TemporaryDirectory(prefix='godseye-scripted-image-') as context:
            shutil.copy(ROOT / 'tests/fixtures/docker_worker/scripted_provider.py', context)
            docker('build', '-t', TEST_IMAGE, '-f', '-', context, input='''
FROM isolation-agent
COPY scripted_provider.py /app/scripted_provider.py
ENTRYPOINT ["python", "/app/scripted_provider.py"]
''')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='godseye-worker-')
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()
        Evaluator.create(self.path / 'private', seed=49273, instances=1,
                         episodes=2, max_steps=1, probes=2, forward_budget=4)
        self.worker = ScriptedDockerWorker(ROOT)
        self.service = None
        self.run_id = None
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.service:
            self.service.close()
        if self.run_id:
            self.worker.recover(dict(id=self.run_id),
                dict(directory=str(self.path / 'private')), self.directory)

    @property
    def directory(self):
        return self.path / 'service' / self.run_id

    def launch(self, model='scripted-complete', **limits):
        self.service = Orchestrator(self.path / 'service', worker=self.worker,
                                    settings=DummySettings())
        self.service.register(self.path / 'private', baseline_id='docker-baseline',
                              suite_id='breakout-pilot', revision='v1')
        # Poison inherited settings; only confirmed settings may reach containers.
        with patch.dict(os.environ, dict(REPAIR_AGENT_MODEL='wrong-model',
                REPAIR_AGENT_KEY_FILE='/must-not-read', OPENAI_API_KEY='must-not-use',
                COMPOSE_FILE='/must-not-use', COMPOSE_PROFILES='agent')):
            run = start(self.service, model, **limits)
            self.run_id = run['experiment_id']
            self.wait_for_request()
        return run

    def until(self, predicate, timeout=40):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(.05)
        self.fail('Timed out waiting for DockerWorker; ' + str(self.result()))

    def result(self):
        if not self.service or not self.run_id:
            return None
        with self.service.lock:
            return self.service.load(self.run_id, 'run')

    def wait_for_request(self):
        def requested():
            path = self.directory / 'evidence/agent.jsonl'
            return path.exists() and '"event": "request"' in path.read_text()
        self.until(requested)

    def release(self):
        (self.directory / 'evidence/release').touch()

    def done(self):
        return self.until(lambda: (row if (row := self.result())['status'] in
                          ('completed', 'failed', 'cancelled', 'interrupted') else None))

    def assert_clean(self):
        self.assertFalse((self.directory / 'provider.key').exists())
        self.assertEqual(docker('ps', '-aq', '--filter',
            'label=com.docker.compose.project=ge-' + self.run_id).strip(), '')
        self.assertEqual(docker('network', 'ls', '-q', '--filter',
            'label=com.docker.compose.project=ge-' + self.run_id).strip(), '')
        secrets = ['dummy-docker-worker-only'] + [p.read_text() for p in
                                                    (self.path / 'private').glob('*.token')]
        for path in self.directory.rglob('*'):
            if path.is_file():
                for secret in secrets:
                    self.assertNotIn(secret.encode(), path.read_bytes(), str(path))

    def test_launch_images_isolation_limits_and_completion(self):
        limits = dict(max_requests=19, max_input_tokens=301, max_total_output_tokens=203,
                      max_seconds=45, max_rounds=18, max_calls=17, max_output_tokens=23)
        self.launch(**limits)
        project = 'ge-' + self.run_id
        ids = docker('ps', '-q', '--filter', 'label=com.docker.compose.project=' + project).split()
        infos = json.loads(docker('inspect', *ids))
        by_role = {i['Config']['Labels']['com.docker.compose.service']: i for i in infos}
        self.assertEqual(set(by_role), {'agent', 'evaluator', 'gateway'})
        for role, memory, pids in [('agent', 128, 16), ('evaluator', 512, 32), ('gateway', 64, 16)]:
            info = by_role[role]
            self.assertEqual(info['Config']['Image'], TEST_IMAGE if role == 'agent' else 'isolation-' + role)
            self.assertEqual(info['Config']['User'], f'{os.getuid()}:{os.getgid()}')
            host = info['HostConfig']
            self.assertTrue(host['ReadonlyRootfs'])
            self.assertEqual(host['Memory'], memory * 1024**2)
            self.assertEqual(host['PidsLimit'], pids)
            self.assertEqual(host['NanoCpus'], 10**9)
            self.assertIn('ALL', host['CapDrop'])
            self.assertIn('no-new-privileges:true', host['SecurityOpt'])
            self.assertIn('noexec', host['Tmpfs']['/tmp'])
        agent = by_role['agent']
        mounts = {m['Destination']: m for m in agent['Mounts']}
        self.assertEqual(set(mounts), {'/evidence', '/run/secrets/agent_token', '/run/secrets/agent_api_key'})
        self.assertTrue(mounts['/evidence']['RW'])
        for dest in ('/run/secrets/agent_token', '/run/secrets/agent_api_key'):
            self.assertFalse(mounts[dest]['RW'])
        self.assertEqual(Path(mounts['/run/secrets/agent_api_key']['Source']), self.directory / 'provider.key')
        self.assertEqual((self.directory / 'provider.key').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        env = dict(e.split('=', 1) for e in agent['Config']['Env'])
        for key, value in limits.items():
            self.assertEqual(env['REPAIR_AGENT_' + key.upper()], str(value))
        self.assertEqual(env['REPAIR_AGENT_MODEL'], 'scripted-complete')
        self.assertNotIn('OPENAI_API_KEY', env)
        self.assertNotIn('dummy-docker-worker-only', json.dumps(agent))
        self.assertEqual(set(by_role['evaluator']['NetworkSettings']['Networks']), {project + '_evaluation'})
        self.assertEqual(set(agent['NetworkSettings']['Networks']), {project + '_evaluation', project + '_provider'})
        self.assertEqual(set(by_role['gateway']['NetworkSettings']['Networks']), {project + '_evaluation', project + '_operator'})
        self.assertEqual(by_role['gateway']['NetworkSettings']['Ports']['8790/tcp'][0]['HostIp'], '127.0.0.1')
        self.assertEqual({m['Destination'] for m in by_role['evaluator']['Mounts']}, {'/private'})
        self.assertFalse(by_role['gateway']['Mounts'])
        self.assertFalse(by_role['evaluator']['HostConfig']['PortBindings'])
        self.assertFalse(agent['HostConfig']['PortBindings'])
        for suffix in ('evaluation', 'operator', 'provider'):
            network = json.loads(docker('network', 'inspect', project + '_' + suffix))[0]
            self.assertEqual(network['Internal'], suffix == 'evaluation')
        docker('exec', by_role['evaluator']['Id'], 'python', '-c', '''
import socket
try:
    socket.create_connection(('1.1.1.1', 443), timeout=2).close()
except OSError: pass
else: raise AssertionError('Evaluator has external egress')
''')
        docker('exec', agent['Id'], 'python', '-c', '''
from pathlib import Path
import os
assert os.getuid() != 0
for p in ['/private', '/var/run/docker.sock', '/app/godseye', '/run/secrets/admin.token']:
    assert not Path(p).exists(), p
for p in ['/app/forbidden', '/run/secrets/agent_api_key', '/run/secrets/agent_token']:
    try:
        with open(p, 'ab') as f: f.write(b'forbidden')
    except OSError: pass
    else: raise AssertionError(p)
''')
        self.release()
        done = self.done()
        self.assertEqual(done['status'], 'completed', done)
        self.assertEqual(done['usage']['requests'], 6)  # list, four freezes, finish
        self.assertTrue(done['usage']['usage_complete'])
        self.assertTrue((self.directory / 'held-out.json').is_file())
        self.assertTrue((self.directory / 'evidence/.agent-run.claim').exists())
        self.assertTrue((self.path / 'private/.orchestration.claim').exists())
        # The container evaluator must really have supplied this scoped journal.
        request = dict(schema_version=1, experiment_id=self.run_id, spec_hash=done['hash'],
                       after=0, limit=100)
        events = []
        while True:
            activity = self.service.activity(request)
            self.assertTrue(activity['available'], activity)
            self.assertFalse(activity['gap'])
            events.extend(activity['events'])
            request['after'] = activity['next_cursor']
            if not activity['has_more']:
                break
        self.assertEqual([e['sequence'] for e in events], list(range(1,len(events)+1)))
        self.assertEqual(events[0]['kind'],'worker_started')
        self.assertEqual(events[-1]['kind'],'worker_finished')
        self.assertTrue(any(e['kind']=='root_probe_reserved' for e in events))
        self.assertTrue(any(e['arm']=='agent' and e['kind']=='selection_frozen' for e in events))
        freezes = [e['sequence'] for e in events if e['kind']=='selection_frozen']
        held = [e['sequence'] for e in events if e['kind']=='held_out_reserved']
        self.assertTrue(held)
        self.assertLess(max(freezes),min(held))
        self.assertEqual(activity['phase'],dict(name='unknown',event_sequence=len(events)))
        journal = self.path / 'private/activity.sqlite3'
        self.assertEqual(journal.stat().st_mode & 0o777,0o600)
        public = json.dumps(activity) + json.dumps(events)
        secrets = ['dummy-docker-worker-only',str(self.path)] + [p.read_text() for p in
                   (self.path / 'private').glob('*.token')]
        for secret in secrets:
            self.assertNotIn(secret,public)
        replay = self.service.activity(dict(request,after=0))
        self.assertEqual(replay['events'],events[:100])
        with self.assertRaises(ContractError):
            self.service.activity(dict(request,spec_hash='0'*64))
        self.assert_clean()

    def test_cancellation_waits_for_cleanup_and_retains_uncertain_request(self):
        run = self.launch()
        self.service.cancel(dict(schema_version=1, experiment_id=run['experiment_id']))
        done = self.done()
        self.assertEqual((done['status'], done['reason']), ('cancelled', 'user_cancelled'))
        self.assertTrue(done['usage']['request_in_flight'])
        self.assertFalse(done['usage']['usage_complete'])
        self.assertFalse((self.directory / 'held-out.json').exists())
        self.assert_clean()

    def test_elapsed_deadline_stops_blocked_provider(self):
        self.launch(max_seconds=4)
        done = self.done()
        self.assertEqual((done['status'], done['reason']), ('failed', 'budget_exhausted'))
        self.assertTrue(done['usage']['request_in_flight'])
        self.assert_clean()

    def test_request_limit_stops_before_second_provider_request(self):
        self.launch(max_requests=1)
        self.release()
        done = self.done()
        self.assertEqual((done['status'], done['reason']), ('failed', 'budget_exhausted'))
        self.assertEqual(done['usage']['requests'], 1)
        self.assertFalse((self.directory / 'held-out.json').exists())
        self.assert_clean()

    def check_adapter_limit(self, **limit):
        self.launch(**limit)
        self.release()
        done = self.done()
        self.assertEqual((done['status'], done['reason']), ('failed', 'budget_exhausted'))
        self.assertEqual(done['usage']['requests'], 1)
        self.assertFalse((self.directory / 'held-out.json').exists())
        self.assert_clean()

    def test_input_token_limit(self):
        self.check_adapter_limit(max_input_tokens=1)

    def test_total_output_token_limit(self):
        self.check_adapter_limit(max_total_output_tokens=1)

    def test_tool_limit(self):
        self.check_adapter_limit(max_calls=1)

    def test_round_limit(self):
        self.check_adapter_limit(max_rounds=1)

    def test_missing_image_fails_without_pull_and_removes_secret(self):
        images = dict(self.worker._images(), evaluator='godseye-deliberately-absent:validation')
        self.service = Orchestrator(self.path / 'service', worker=self.worker, settings=DummySettings())
        self.service.register(self.path / 'private', baseline_id='docker-baseline',
                              suite_id='breakout-pilot', revision='v1')
        with patch.object(self.worker, '_images', return_value=images):
            self.run_id = start(self.service)['experiment_id']
            done = self.done()
        self.assertEqual((done['status'], done['reason']), ('failed', 'runtime_failure'))
        self.assertFalse((self.directory / 'evidence/agent.jsonl').exists())
        self.assert_clean()

    def test_failed_cleanup_fences_admission_and_retains_secret_until_recovery(self):
        run = self.launch()
        with patch.object(self.worker, 'recover', side_effect=subprocess.TimeoutExpired('docker', 10)):
            self.service.cancel(dict(schema_version=1, experiment_id=run['experiment_id']))
            done = self.done()
        self.assertEqual((done['status'], done['reason']), ('interrupted', 'process_lost'))
        self.assertTrue(done['recovery_required'])
        self.assertTrue(self.service.recovery_blocked)
        self.assertTrue((self.directory / 'provider.key').exists())
        self.service.close()
        self.service = Orchestrator(self.path / 'service', worker=self.worker, settings=DummySettings())
        self.assertFalse(self.result()['recovery_required'])
        self.assert_clean()

    def test_provider_failure_is_redacted_and_cleaned(self):
        self.launch('scripted-error')
        self.release()
        done = self.done()
        self.assertEqual((done['status'], done['reason']), ('failed', 'provider_error'))
        self.assertFalse(done['usage']['usage_complete'])
        self.assert_clean()

    def test_missing_usage_stops_and_cleans(self):
        self.launch('scripted-missing')
        self.release()
        done = self.done()
        self.assertEqual((done['status'], done['reason']), ('failed', 'provider_error'))
        self.assertFalse(done['usage']['usage_complete'])
        self.assert_clean()

    def test_process_death_recovers_orphans_without_keys_or_reexecution(self):
        child = subprocess.Popen([sys.executable, '-c',
            'import sys; sys.path.insert(0, "tests"); from test_docker_worker import crash_child; '
            'crash_child(sys.argv[1])', str(self.path)], cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            self.until(lambda: (self.path / 'run-id').exists())
            self.run_id = (self.path / 'run-id').read_text()
            self.wait_for_request()
        finally:
            child.kill()
            child.communicate(timeout=10)
        self.assertTrue((self.directory / 'provider.key').exists())
        self.assertTrue(docker('ps', '-q', '--filter', 'name=^/ge-' + self.run_id + '-agent$').strip())
        before = (self.directory / 'evidence/agent.jsonl').read_bytes()
        class NoKeys:
            def credential(self, provider):
                raise AssertionError('Recovery must never load keys')
        self.service = Orchestrator(self.path / 'service', worker=self.worker, settings=NoKeys())
        done = self.result()
        self.assertEqual((done['status'], done['reason']), ('interrupted', 'process_lost'))
        self.assertFalse(done['recovery_required'])
        self.assertEqual(done['usage']['requests'], 1)
        self.assertTrue(done['usage']['request_in_flight'])
        self.assertFalse(done['usage']['usage_complete'])
        self.assertFalse((self.directory / 'held-out.json').exists())
        self.assertTrue((self.path / 'private/.orchestration.claim').exists())
        self.assertTrue((self.directory / 'evidence/.agent-run.claim').exists())
        self.assertEqual((self.directory / 'evidence/agent.jsonl').read_bytes(), before)
        self.assert_clean()

    def test_provider_injection_rejected_by_public_contract(self):
        self.service = Orchestrator(self.path / 'service', worker=self.worker, settings=DummySettings())
        self.service.register(self.path / 'private', baseline_id='docker-baseline',
                              suite_id='breakout-pilot', revision='v1')
        for field in ('worker', 'image', 'provider_url', 'scripted_provider', 'compose_file'):
            with self.assertRaises(ContractError) as error:
                self.service.plan(dict(schema_version=1, text='Improve Breakout score',
                    provider=dict(name='openai', model='scripted-complete', routing='price'),
                    limits=dict(DEFAULT_CEILINGS), **{field: 'test'}))
            self.assertEqual(error.exception.code, 'invalid_schema')


if __name__ == '__main__':
    unittest.main()
