"""Rendered guide contract and execution of the exact displayed Python examples."""
from contextlib import contextmanager, redirect_stdout
from html.parser import HTMLParser
import io
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest

import uvicorn

from godseye.core import Store, digest, save_weights
from godseye.export import export_demo
from godseye.server import create_app

ROOT = Path(__file__).resolve().parents[1]


class Guide(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.examples = {}
        self.links = []
        self.ids = set()
        self.example = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        if tag == 'a':
            self.links.append(attrs['href'])
        if tag == 'code' and 'data-example' in attrs:
            self.example = attrs['data-example']
            self.examples[self.example] = ''

    def handle_endtag(self, tag):
        if tag == 'code':
            self.example = None

    def handle_data(self, data):
        if self.example:
            self.examples[self.example] += data


@contextmanager
def temporary_api(store):
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(create_app(store), log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('Guide test server did not start')
            time.sleep(.01)
        yield 'http://127.0.0.1:' + str(sock.getsockname()[1])
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()
        if thread.is_alive():
            raise RuntimeError('Guide test server did not stop')


class APIGuideTests(unittest.TestCase):
    def test_displayed_examples_import_edit_and_measure_a_real_checkpoint(self):
        guide = Guide((ROOT / 'godseye/static/api.html').read_text())
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'workspace')
            source = Path(directory) / 'weights.npz'
            save_weights(source, store.weights('paper'))
            original_hash = digest(store.weights('paper'))
            scope = {}
            with temporary_api(store) as url, redirect_stdout(io.StringIO()):
                for name in ('inspect', 'import', 'edit', 'evaluate'):
                    example = guide.examples[name].replace('http://127.0.0.1:8787', url)
                    example = example.replace('./weights.npz', str(source))
                    exec(compile(example, f'api.html:{name}', 'exec'), scope)
                self.assertIn('checkpoint_import', scope['state']['capabilities'])
                record, branch, result = (scope[k] for k in ('record', 'branch', 'result'))
                self.assertIsNone(record['parent'])
                self.assertEqual(record['sha256'], original_hash)
                self.assertEqual(branch['parent'], record['id'])
                self.assertEqual(scope['preview']['changed'], 4)
                self.assertEqual(result['base_sha256'], original_hash)
                self.assertEqual(result['candidate_id'], branch['id'])
                self.assertEqual(result['episodes'], 2)
                self.assertEqual(result['max_steps'], 100)
                calls = sum(result[side]['forward_calls'] for side in ('base', 'candidate'))
                self.assertLessEqual(calls, 400)
                # The guide's late-cancellation statement is true for a completed run.
                cancelled = scope['lab'].cancel(scope['job']['id'])
                self.assertEqual(cancelled['status'], 'succeeded')
            self.assertEqual(digest(store.weights('paper')), original_hash)
            self.assertEqual(digest(store.weights(record['id'])), original_hash)

    def test_export_guide_is_self_contained_and_all_internal_targets_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            output = export_demo(Path(directory) / 'Gods-eye')
            html = (output / 'api.html').read_text()
            guide = Guide(html)
            self.assertEqual(len(list(output.iterdir())), 13)
            self.assertNotIn('href="landing.css"', html)
            self.assertNotIn('<script', html)
            self.assertIn('body class="guide"', html)
            self.assertIn('grid-template-columns:200px minmax(0,760px)', html)
            self.assertIn('position:sticky', html)
            self.assertIn('overflow:auto', html)
            self.assertIn('readonly spellcheck="false"', html)
            self.assertIn('uncertain_write', html)
            for href in guide.links:
                if href.startswith('#'):
                    self.assertIn(href[1:], guide.ids)
                elif href.startswith('https://'):
                    if '/blob/main/' in href:
                        self.assertTrue((ROOT / href.split('/blob/main/')[1]).is_file(), href)
                else:
                    target = href.split('#')[0]
                    self.assertTrue((output / target).exists(), href)
            for example in guide.examples.values():
                compile(example, 'api.html', 'exec')


if __name__ == '__main__':
    unittest.main()
