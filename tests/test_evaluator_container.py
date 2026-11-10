"""Opt-in tests of the actual Compose boundary; no real provider requests."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.request
import urllib.error

from isolation.agent_adapter import Client, post


@unittest.skipUnless(os.environ.get('GODSEYE_CONTAINER_TEST') == '1' and shutil.which('docker'),
                     'Requires Docker daemon and GODSEYE_CONTAINER_TEST=1; boundary unverified otherwise')
class ContainerBoundaryTests(unittest.TestCase):
    def test_compose_isolation_persistence_and_scripted_agent(self):
        root = Path(__file__).resolve().parents[1]
        # Never inherit a real provider credential or secret path from the operator.
        with tempfile.TemporaryDirectory(prefix='godseye-container-') as temp:
            private, evidence = Path(temp) / 'private', Path(temp) / 'evidence'
            private.mkdir(mode=0o700)
            evidence.mkdir(mode=0o700)
            key = Path(temp) / 'dummy-provider-key'
            key.write_text('dummy-provider-key-for-container-tests-only')
            key.chmod(0o600)
            uid, gid = os.getuid() or 65532, os.getgid() or 65532
            if os.getuid() == 0:
                for path in (private, evidence, key):
                    os.chown(path, uid, gid)
                os.chmod(temp, 0o755)
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(('OPENAI_', 'REPAIR_', 'EVALUATOR_', 'COMPOSE_'))}
            env.update(EVALUATOR_PRIVATE_DIR=str(private), REPAIR_EVIDENCE_DIR=str(evidence),
                       REPAIR_AGENT_KEY_FILE=str(key), REPAIR_AGENT_MODEL='dummy-scripted-model',
                       EVALUATOR_UID=str(uid), EVALUATOR_GID=str(gid))
            project = 'godseye-test-' + str(os.getpid())
            compose = ['docker', 'compose', '-p', project, '-f', str(root / 'isolation/compose.yaml')]

            def command(argv, *, input=None, check=True, timeout=240):
                result = subprocess.run(argv, env=env, cwd=root, input=input,
                                        capture_output=True, text=True, timeout=timeout)
                if check and result.returncode:
                    self.fail(f'{argv[:8]} exited {result.returncode}\n{result.stdout}\n{result.stderr}')
                return result

            def run(*args, **kwargs):
                return command([*compose, *args], **kwargs)

            def inspect(cid):
                return json.loads(command(['docker', 'inspect', cid]).stdout)[0]

            def ready(client):
                for _ in range(80):
                    state = client.call('list', {})
                    if 'cases' in state:
                        return state
                    time.sleep(0.25)
                self.fail(f'Evaluator did not become ready: {state}\n'
                          + run('logs', '--no-color').stdout)

            agent_name = project + '-boundary-agent'
            agent_started = False
            try:
                command(['docker', 'version'], timeout=30)
                run('build', 'evaluator', 'agent', 'gateway')
                run('run', '--rm', '--no-deps', 'evaluator', '--initialize-only', '--seed', '924371')
                run('up', '-d', 'evaluator', 'gateway')
                client = Client('http://127.0.0.1:8790', (private / 'agent.token').read_text())
                state = ready(client)
                self.assertEqual(len(state['cases']), 12)
                evaluator = inspect(run('ps', '-q', 'evaluator').stdout.strip())
                gateway = inspect(run('ps', '-q', 'gateway').stdout.strip())
                run('run', '-d', '--no-deps', '--name', agent_name, '--entrypoint', 'python',
                    'agent', '-c', 'import time; time.sleep(600)')
                agent_started = True
                agent = inspect(agent_name)

                with self.subTest('actual service hardening and mounts'):
                    for info, memory, pids in ((evaluator, 512, 32), (agent, 128, 16),
                                                (gateway, 64, 16)):
                        host = info['HostConfig']
                        self.assertEqual(info['Config']['User'], f'{uid}:{gid}')
                        self.assertNotEqual(uid, 0)
                        self.assertTrue(host['ReadonlyRootfs'])
                        self.assertIn('ALL', host['CapDrop'])
                        self.assertIn('no-new-privileges:true', host['SecurityOpt'])
                        self.assertEqual(host['Memory'], memory * 1024**2)
                        self.assertEqual(host['NanoCpus'], 10**9)
                        self.assertEqual(host['PidsLimit'], pids)
                        self.assertIn('noexec', host['Tmpfs']['/tmp'])
                    mounts = {m['Destination']: m for m in agent['Mounts']}
                    self.assertEqual(set(mounts), {'/evidence', '/run/secrets/agent_token',
                                                  '/run/secrets/agent_api_key'})
                    self.assertTrue(mounts['/evidence']['RW'])
                    for dest in ('/run/secrets/agent_token', '/run/secrets/agent_api_key'):
                        self.assertFalse(mounts[dest]['RW'])
                    self.assertEqual(Path(mounts['/run/secrets/agent_api_key']['Source']), key)
                    self.assertEqual({m['Destination'] for m in evaluator['Mounts']}, {'/private'})
                    self.assertFalse(evaluator['HostConfig']['PortBindings'])
                    self.assertFalse(gateway['Mounts'])
                    self.assertEqual(gateway['NetworkSettings']['Ports']['8790/tcp'][0]['HostIp'],
                                     '127.0.0.1')
                    self.assertFalse(agent['HostConfig']['PortBindings'])

                with self.subTest('network topology and evaluator egress denial'):
                    eval_nets = set(evaluator['NetworkSettings']['Networks'])
                    agent_nets = set(agent['NetworkSettings']['Networks'])
                    self.assertEqual(eval_nets, {project + '_evaluation'})
                    self.assertEqual(agent_nets, eval_nets | {project + '_provider'})
                    self.assertEqual(set(gateway['NetworkSettings']['Networks']),
                                     eval_nets | {project + '_operator'})
                    for name in agent_nets:
                        network = json.loads(command(['docker', 'network', 'inspect', name]).stdout)[0]
                        self.assertEqual(network['Internal'], name in eval_nets)
                    command(['docker', 'exec', evaluator['Id'], 'python', '-c', '''
import socket
try:
    socket.create_connection(('1.1.1.1', 443), timeout=2).close()
except OSError:
    pass
else:
    raise AssertionError('Evaluator has external egress')
'''])

                with self.subTest('filesystem denial inside the Compose agent'):
                    command(['docker', 'exec', '-i', agent_name, 'python', '-'], input='''
import importlib.util, os
from pathlib import Path
assert os.getuid() != 0
assert importlib.util.find_spec('godseye') is None
assert sorted(p.name for p in Path('/app').iterdir()) == ['agent_adapter.py']
for p in ['/private', '/evaluator', '/var/run/docker.sock', '/app/godseye',
          '/app/fixtures', '/run/secrets/admin.token', '/run/secrets/heuristic.token',
          '/run/secrets/unchanged.token']:
    assert not Path(p).exists(), p
for p in ['/app/forbidden', '/run/secrets/agent_token', '/run/secrets/agent_api_key']:
    try:
        with open(p, 'ab') as stream:
            stream.write(b'forbidden')
    except OSError:
        pass
    else:
        raise AssertionError('Unexpected write access: ' + p)
Path('/tmp/scratch').write_text('allowed ephemeral scratch')
assert Path('/run/secrets/agent_api_key').read_text() == 'dummy-provider-key-for-container-tests-only'
status = Path('/proc/self/status').read_text()
assert 'CapEff:\\t0000000000000000' in status
assert 'NoNewPrivs:\\t1' in status
''')

                with self.subTest('HTTP authorization, ownership and reveal gate'):
                    for token, path, expected in [('wrong', '/rpc', 401),
                            (client.token, '/report', 403),
                            ((private / 'admin.token').read_text(), '/report', 400),
                            (client.token, '/private/experiment.json', 404),
                            (client.token, '/rpc?url=https://api.openai.com', 404),
                            (client.token, '/http://example.com/rpc', 404)]:
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            post(client.url + path, token, {})
                        self.assertEqual(error.exception.code, expected)
                    # The gateway must reject oversized/chunked/non-JSON input
                    # before forwarding, and never follow a client-supplied URL.
                    for headers in ({'Content-Length': '65537'},
                                    {'Transfer-Encoding': 'chunked'},
                                    {'Content-Type': 'text/plain'}):
                        request = urllib.request.Request(client.url + '/rpc', data=b'{}', headers={
                            'Authorization': 'Bearer ' + client.token,
                            'Content-Type': 'application/json', **headers})
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            urllib.request.urlopen(request, timeout=5)
                        self.assertEqual(error.exception.code, 400)
                    case = state['cases'][0]
                    args = dict(case_id=case['id'], candidate_id=case['root_id'])
                    other = Client(client.url, (private / 'heuristic.token').read_text())
                    self.assertEqual(other.call('evaluate', args)['status'], 400)
                    self.assertEqual(client.call('read', dict(**args, tensor='../../experiment.json',
                                                             start=0, count=1))['status'], 400)
                    self.assertEqual(client.call('patch', dict(case_id=case['id'], parent_id=case['root_id'],
                        patch="b3[0] = __import__('os').system('true')", hypothesis='denial test'))['status'], 400)

                with self.subTest('budget and freeze persistence through restart'):
                    self.assertIn('result', client.call('evaluate', args))
                    self.assertIn('result', client.call('evaluate', args))
                    self.assertEqual(client.call('evaluate', args)['status'], 400)
                    self.assertTrue(client.call('freeze', args)['frozen'])
                    run('restart', 'evaluator')
                    persisted = ready(client)['cases'][0]
                    self.assertEqual(persisted['probes_used'], 2)
                    self.assertEqual(persisted['forward_reserved'], 800)
                    self.assertTrue(persisted['finalized'])
                    self.assertEqual(client.call('evaluate', args)['status'], 400)
                    # Reinitialization cannot erase reservations or selections.
                    self.assertNotEqual(run('run', '--rm', '--no-deps', 'evaluator',
                                            '--initialize-only', check=False).returncode, 0)
                    self.assertEqual(ready(client)['cases'][0], persisted)

                with self.subTest('standalone adapter with dummy provider and actual HTTP tools'):
                    # Use the service's configured command and secret loading. Replace only
                    # the provider transport in-process; evaluator HTTP remains real.
                    config = json.loads(run('--profile', 'agent', 'config', '--format', 'json').stdout)
                    code = '''
import json, sys
from pathlib import Path
import agent_adapter as adapter
real_post = adapter.post
calls = []
def scripted_post(url, token, body):
    if url != 'https://api.openai.com/v1/responses':
        return real_post(url, token, body)
    assert token == 'dummy-provider-key-for-container-tests-only'
    assert body['model'] == 'dummy-scripted-model'
    assert {t['name'] for t in body['tools']} == set(adapter.FIELDS)
    assert body['store'] is False
    assert token not in json.dumps(body)
    calls.append(url)
    outputs = [m for m in body['input'] if m.get('type') == 'function_call_output']
    if not outputs:
        name, args = 'list', {}
    else:
        state = json.loads(outputs[0]['output'])
        cases = [c for c in state['cases'] if not c['finalized']]
        index = len(outputs) - 1
        if index >= len(cases):
            return {'output': [], 'usage': {'input_tokens': 1, 'output_tokens': 1}}
        case = cases[index]
        name, args = 'freeze', dict(case_id=case['id'], candidate_id=case['root_id'])
    return {'usage': {'input_tokens': 1, 'output_tokens': 1}, 'output': [dict(type='function_call', name=name, arguments=json.dumps(args),
                           call_id=str(len(calls)))]}
adapter.post = scripted_post
sys.argv = ['agent_adapter.py'] + CONFIGURED_COMMAND
assert adapter.main() == 0
assert len(calls) == 13
rows = [json.loads(line) for line in Path('/evidence/agent.jsonl').read_text().splitlines()]
assert rows[-1]['event'] == 'completed'
assert len([r for r in rows if r['event'] == 'tool' and r['name'] == 'freeze']) == 11
print('Scripted provider completed; real evaluator HTTP; zero provider network calls')
'''.replace('CONFIGURED_COMMAND', repr(config['services']['agent']['command']))
                    result = command(['docker', 'exec', '-i', agent_name, 'python', '-'], input=code)
                    self.assertIn('zero provider network calls', result.stdout)
                    self.assertTrue(all(c['finalized'] for c in ready(client)['cases']))
                    # Baseline arms are still unfrozen: the reveal gate must remain closed.
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        post(client.url + '/report', (private / 'admin.token').read_text(), {})
                    self.assertEqual(error.exception.code, 400)
                    saved = (evidence / 'agent.jsonl').read_text()
                    for secret in (key.read_text(), *(p.read_text() for p in private.glob('*.token'))):
                        self.assertNotIn(secret, saved)
            finally:
                # Compose down omits profiled one-off agent containers on some versions.
                if agent_started:
                    command(['docker', 'rm', '-f', agent_name])
                run('--profile', 'agent', 'down', '--volumes', '--remove-orphans')
