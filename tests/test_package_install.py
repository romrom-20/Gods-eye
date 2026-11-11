"""Opt-in artifact test: GODSEYE_TEST_WHEEL=/absolute/path/to/wheel.whl.

Installs the artifact and its server extra in a fresh venv outside the checkout.
Installation can access the package index; the actual CPU/HTTP example is local.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
import venv


@unittest.skipUnless(os.environ.get('GODSEYE_TEST_WHEEL'), 'Set GODSEYE_TEST_WHEEL to test a built wheel')
class InstalledPackageTests(unittest.TestCase):
    def test_installed_browser_and_cpu_example(self):
        wheel = Path(os.environ['GODSEYE_TEST_WHEEL']).resolve(strict=True)
        checkout = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='godseye-package-') as temporary:
            root = Path(temporary).resolve()
            self.assertNotIn(checkout, root.parents)
            venv.create(root / 'venv', with_pip=True)
            scripts = root / 'venv' / ('Scripts' if os.name == 'nt' else 'bin')
            python = scripts / ('python.exe' if os.name == 'nt' else 'python')
            cli = scripts / ('godseye.exe' if os.name == 'nt' else 'godseye')
            # Fresh HOME and an allowlist prevent inherited operator configuration,
            # orchestration, credentials or PYTHONPATH from influencing this run.
            env = {key: os.environ[key] for key in (
                'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL',
                'SSL_CERT_FILE', 'SSL_CERT_DIR',
            ) if key in os.environ}
            home = root / 'home'
            home.mkdir()
            env.update(HOME=str(home), USERPROFILE=str(home), PYTHONNOUSERSITE='1',
                       GODSEYE_DATA_DIR=str(root / 'workspace'))

            def run(*args):
                return subprocess.run([str(arg) for arg in args], cwd=root, env=env,
                                      text=True, capture_output=True, check=True, timeout=180)

            run(python, '-m', 'pip', 'install', '--disable-pip-version-check',
                f'{wheel}[server]')
            location = Path(run(python, '-c', 'import godseye; print(godseye.__file__)').stdout.strip())
            self.assertIn(root / 'venv', location.parents)
            self.assertNotIn(checkout, location.parents)
            inspected = json.loads(run(cli, 'inspect', 'paper').stdout)
            self.assertEqual(sum(t['parameters'] for t in inspected['tensors']), 20486)
            # Exercises all bundled recorded checkpoints, runs, JS/CSS and license data.
            run(cli, 'export-demo', '--output', root / 'demo')
            demo = json.loads((root / 'demo/demo.json').read_text())
            self.assertEqual(len(demo['state']['checkpoints']), 4)
            self.assertEqual(len(demo['runs']), 2)
            self.assertTrue((location.parent / 'data/breakout/PROVENANCE.md').is_file())
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            opener = build_opener(ProxyHandler({}))
            base = f'http://127.0.0.1:{port}'

            def request(path, body=None):
                data = None if body is None else json.dumps(body).encode()
                req = Request(base + path, data=data,
                              headers={} if body is None else {'Content-Type': 'application/json'})
                with opener.open(req, timeout=3) as response:
                    return response.read()

            with (root / 'server.log').open('w+') as log:
                process = subprocess.Popen([str(cli), 'serve', '--port', str(port)],
                                           cwd=root, env=env, stdout=log, stderr=log)
                try:
                    deadline = time.monotonic() + 20
                    while True:
                        try:
                            health = json.loads(request('/healthz'))
                            break
                        except (URLError, TimeoutError):
                            if process.poll() is not None or time.monotonic() > deadline:
                                log.seek(0)
                                self.fail('Installed server failed to start: ' + log.read())
                            time.sleep(.05)
                    self.assertEqual(health, {'status': 'ok', 'mode': 'local'})
                    for asset in ('/', '/lab', '/app.js', '/style.css', '/landing.js',
                                  '/landing.css', '/api.html'):
                        self.assertTrue(request(asset), asset)
                    state = json.loads(request('/api/v1/state'))
                    self.assertEqual(state['backend'], 'minatar-breakout-v1')
                    self.assertTrue(json.loads(request('/api/v1/presets/ball-chaser'))['patch'])
                    checkpoint = json.loads(request('/api/v1/checkpoints', {
                        'base_id': 'paper', 'patch': 'W3[0:8:2, 1] = 0',
                        'hypothesis': 'Package smoke: ablate four known left-action connections',
                    }))
                    job = json.loads(request('/api/v1/jobs', {
                        'base_id': 'paper', 'candidate_id': checkpoint['id'],
                        'episodes': 1, 'max_steps': 40, 'seed': 1000,
                    }))
                    deadline = time.monotonic() + 20
                    while job['status'] in ('queued', 'running', 'cancelling'):
                        self.assertLess(time.monotonic(), deadline, 'CPU evaluation timed out')
                        time.sleep(.05)
                        job = json.loads(request('/api/v1/jobs/' + job['id']))
                    self.assertEqual(job['status'], 'succeeded', job)
                    evidence = json.loads(request('/api/v1/runs/' + job['run_id']))
                    self.assertEqual(evidence['base_sha256'], inspected['sha256'])
                    self.assertEqual(evidence['candidate_sha256'], checkpoint['sha256'])
                    self.assertNotEqual(evidence['base_sha256'], evidence['candidate_sha256'])
                    for side in ('base', 'candidate'):
                        self.assertGreater(evidence[side]['forward_calls'], 0)
                        self.assertLessEqual(evidence[side]['forward_calls'], 40)
                    self.assertTrue((root / 'workspace' / ('run-' + job['run_id'] + '.json')).is_file())
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
