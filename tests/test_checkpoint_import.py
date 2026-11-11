"""Data-only import, real HTTP lifecycle and bounded malicious ingress checks."""
import base64
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import warnings
import zipfile

from fastapi.testclient import TestClient
import numpy as np
import uvicorn

from godseye.backends import BreakoutBackend, DATA_DIR
from godseye.checkpoint_import import MAX_JSON, MAX_NPZ, read_local, read_weights
from godseye.client import Client
from godseye.core import NAMES, Store, digest
from godseye.server import Boundary, create_app

URL = '/api/v1/checkpoints/import'


def archive(arrays=None, compressed=True):
    arrays = arrays or {key: np.full(shape, (i + 1) / 100, dtype='<f4')
                        for i, (key, shape) in enumerate(NAMES.values())}
    stream = io.BytesIO()
    (np.savez_compressed if compressed else np.savez)(stream, **arrays)
    return stream.getvalue()


def body(raw, **changes):
    return dict(name='Local fixture', provenance='', npz_base64=base64.b64encode(raw).decode(), **changes)


def rewrite(raw, mutate):
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(output, 'w') as target:
        for index, info in enumerate(source.infolist()):
            name, data = mutate(index, info.filename, source.read(info))
            if name is not None:
                target.writestr(name, data)
    return output.getvalue()


@contextmanager
def live_server(store):
    # Dedicated ephemeral listener owned by this test; no pre-existing service.
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    server = uvicorn.Server(uvicorn.Config(create_app(store), log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError('Test server did not start')
            time.sleep(.01)
        yield Client('http://127.0.0.1:' + str(sock.getsockname()[1]))
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()
        if thread.is_alive():
            raise RuntimeError('Test server did not stop')


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.store = Store(self.root / 'workspace')
        self.raw = archive()

    def tearDown(self):
        self.directory.cleanup()

    def test_real_http_import_inspect_patch_cpu_evaluation_and_reload(self):
        self.raw = archive(compressed=False)
        self.assertGreater(len(json.dumps(body(self.raw))), 65536)
        original_file = DATA_DIR / 'breakout/paper.npz'
        original = original_file.read_bytes()
        # Preserve both bundled original and a previously saved branch byte-for-byte.
        previous = self.store.patch('paper', 'b3[0] += 1', 'Existing branch')
        before = {p: p.read_bytes() for p in self.store.path.iterdir()}
        source = self.root / 'private-source-name.npz'
        source.write_bytes(self.raw)
        with live_server(self.store) as client:
            self.assertIn('checkpoint_import', client.state()['capabilities'])
            with patch.object(self.store.backend, 'compare', side_effect=AssertionError('Import ran model')):
                imported = client.import_checkpoint(source, 'My checkpoint', 'Deterministic fixture')
            self.assertIsNone(imported['parent'])
            self.assertEqual(imported['source_sha256'], hashlib.sha256(self.raw).hexdigest())
            self.assertEqual(imported['sha256'], digest(read_weights(self.raw)))
            self.assertEqual(imported['backend'], 'minatar-breakout-v1')
            self.assertFalse({'patch', 'diff', 'parent_sha256'} & imported.keys())
            self.assertEqual(client.tensor(imported['id'])['sha256'], imported['sha256'])
            self.assertIn(imported, client.state()['checkpoints'])
            child = client.patch(imported['id'], 'b3[0] += 1', 'Test imported parent',
                                 expected_parent_sha256=imported['sha256'])
            self.assertEqual(child['parent'], imported['id'])
            job = client.evaluate(imported['id'], child['id'], episodes=2, seed=20, max_steps=20)
            result = client.wait(job['id'], timeout=5, interval=.01)
            self.assertEqual(result['base_sha256'], imported['sha256'])
            self.assertEqual(result['candidate_sha256'], child['sha256'])
            self.assertLessEqual(sum(result[k]['forward_calls'] for k in ('base', 'candidate')), 80)
        reloaded = Store(self.store.path)
        self.assertIn(imported, reloaded.checkpoints())
        self.assertEqual(digest(reloaded.weights(imported['id'])), imported['sha256'])
        self.assertEqual(reloaded.read_run(result['id'])['candidate_id'], child['id'])
        self.assertEqual((self.store.path / (imported['id'] + '.npz')).read_bytes(), self.raw)
        self.assertEqual(source.read_bytes(), self.raw)
        self.assertEqual(original_file.read_bytes(), original)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertEqual(digest(reloaded.weights(previous['id'])), previous['sha256'])

    def test_supported_archives_and_canonical_tensor_order(self):
        for raw in (self.raw, archive(compressed=False), (DATA_DIR / 'breakout/paper.npz').read_bytes()):
            imported = self.store.import_checkpoint(raw, 'Accepted')
            self.assertEqual(digest(self.store.weights(imported['id'])), imported['sha256'])
        arrays = {key: np.ones(shape, dtype='<f4') for key, shape in reversed(list(NAMES.values()))}
        imported = self.store.import_checkpoint(archive(arrays), 'Reverse ZIP order')
        self.assertEqual(list(self.store.weights(imported['id'])), list(NAMES))
        self.assertEqual(digest(self.store.weights(imported['id'])), imported['sha256'])

    def test_bad_npz_never_publishes(self):
        arrays = {key: np.zeros(shape, dtype='<f4') for key, shape in NAMES.values()}
        first = next(iter(arrays))
        invalid = [b'not zip', b'PK', self.raw[:-1], b'prefix' + self.raw,
                   self.raw + b'trailer', b'0' * (MAX_NPZ + 1)]
        for value in (np.zeros((1,), dtype='<f4'), np.zeros((600, 32), dtype='<f8'),
                      np.zeros((600, 32), dtype='>f4'), np.full((600, 32), np.nan, dtype='<f4'),
                      np.full((600, 32), np.inf, dtype='<f4'), np.zeros((600, 32), dtype=object)):
            invalid.append(archive(dict(arrays, **{first: value})))
        invalid.append(rewrite(self.raw, lambda i, n, d: (None if i == 0 else n, d)))
        invalid.append(rewrite(self.raw, lambda i, n, d: ('unknown.npy' if i == 0 else n, d)))
        invalid.append(rewrite(self.raw, lambda i, n, d: ('../' + n if i == 0 else n, d)))
        duplicate = io.BytesIO(self.raw)
        with warnings.catch_warnings(), zipfile.ZipFile(duplicate, 'a') as target:
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(io.BytesIO(self.raw)) as source:
                name = source.namelist()[0]
                target.writestr(name, source.read(name))
        invalid.append(duplicate.getvalue())
        for raw in invalid:
            with self.subTest(length=len(raw)):
                with self.assertRaises(ValueError):
                    self.store.import_checkpoint(raw, 'Invalid')
                self.assertEqual(len(self.store.checkpoints()), 2)
                self.assertEqual(list(self.store.path.iterdir()), [])

    def test_huge_shapes_headers_payload_bombs_and_encryption(self):
        def npy(shape, descr='<f4', fortran=False):
            stream = io.BytesIO()
            np.lib.format.write_array_header_1_0(stream, dict(shape=shape, descr=descr, fortran_order=fortran))
            return stream.getvalue()
        malformed = [npy((10**12, 32)), npy((600, 32), '|O'), npy((600, 32), fortran=True),
                     b'\x93NUMPY\x01\x00\xff\xff' + b' ' * 2048,
                     b'0' * 110000, npy((600, 32)) + b'0' * (600 * 32 * 4 + 1)]
        duplicate_header = b"{'descr': '<f4', 'fortran_order': False, 'shape': (600, 32), 'shape': (600, 32)}\n"
        malformed.append(b'\x93NUMPY\x01\x00' + struct.pack('<H', len(duplicate_header))
                         + duplicate_header + b'0' * (600 * 32 * 4))
        for data in malformed:
            raw = rewrite(self.raw, lambda i, n, d: (n, data if i == 0 else d))
            # The importer never calls numpy.load/read_array (or allocates the declared shape).
            with patch('numpy.load', side_effect=AssertionError('Unsafe loader')), \
                 patch('numpy.lib.format.read_array', side_effect=AssertionError('Unsafe loader')), \
                 patch('numpy.frombuffer', side_effect=AssertionError('Array before header validation')):
                with self.assertRaises(ValueError):
                    read_weights(raw)
        encrypted = bytearray(self.raw)
        struct.pack_into('<H', encrypted, 6, 1)
        central = encrypted.index(b'PK\x01\x02')
        struct.pack_into('<H', encrypted, central + 8, 1)
        with self.assertRaises(ValueError):
            read_weights(bytes(encrypted))
        corrupted = bytearray(self.raw)
        corrupted[100] ^= 1
        with self.assertRaises(ValueError):
            read_weights(bytes(corrupted))
        # Large expansion with forged small directory size still fails bounded decompression.
        huge = io.BytesIO()
        with zipfile.ZipFile(huge, 'w', compression=zipfile.ZIP_DEFLATED) as target:
            with zipfile.ZipFile(io.BytesIO(self.raw)) as source:
                for i, info in enumerate(source.infolist()):
                    target.writestr(info.filename, b'0' * 1000000 if i == 0 else source.read(info))
        bomb = bytearray(huge.getvalue())
        central = bomb.index(b'PK\x01\x02')
        struct.pack_into('<L', bomb, 22, 76928)
        struct.pack_into('<L', bomb, central + 24, 76928)
        with self.assertRaises(ValueError):
            read_weights(bytes(bomb))

    def test_strict_http_schema_base64_metadata_and_no_writes(self):
        with TestClient(create_app(self.store)) as client:
            good = body(self.raw)
            for value in ('!', good['npz_base64'] + '\n', 'AB==', 'AA===', '',
                          base64.b64encode(b'x' * (MAX_NPZ + 1)).decode()):
                bad = dict(good, npz_base64=value)
                self.assertEqual(client.post(URL, json=bad).status_code, 400)
            for update in ({'name': ''}, {'name': ' '}, {'name': 'a' * 81}, {'name': 1},
                           {'provenance': 'a' * 2001}, {'provenance': None}, {'unknown': 'x'}):
                self.assertEqual(client.post(URL, json=dict(good, **update)).status_code, 400)
            for raw in (b'{"name":"a","name":"b"}', b'[]', b'{',
                        b'{"name":"x","provenance":""}', b'[' * 2000):
                self.assertEqual(client.post(URL, content=raw,
                    headers={'Content-Type': 'application/json'}).status_code, 400)
            self.assertEqual(list(self.store.path.iterdir()), [])

    def test_auth_readonly_hosts_origin_content_type_and_capabilities(self):
        with TestClient(create_app(self.store, token='test-token')) as client:
            self.assertEqual(client.post(URL, json=body(self.raw)).status_code, 401)
            headers = {'Authorization': 'Bearer test-token'}
            for change in ({'Host': 'evil.invalid'}, {'Origin': 'https://evil.invalid'},
                           {'Sec-Fetch-Site': 'cross-site'}):
                self.assertEqual(client.post(URL, json=body(self.raw), headers=dict(headers, **change)).status_code, 403)
            self.assertEqual(client.post(URL, content=b'{}', headers=dict(headers, **{'Content-Type': 'text/plain'})).status_code, 415)
            self.assertEqual(client.post(URL, json=body(self.raw), headers=headers).status_code, 201)
        with TestClient(create_app(self.store, readonly=True)) as client:
            self.assertNotIn('checkpoint_import', client.get('/api/v1/state').json()['capabilities'])
            self.assertEqual(client.post(URL, json=body(self.raw)).status_code, 403)
        class Custom(BreakoutBackend):
            pass
        custom = Store(self.root / 'custom', backend=Custom())
        with TestClient(create_app(custom)) as client:
            self.assertNotIn('checkpoint_import', client.get('/api/v1/state').json()['capabilities'])
            self.assertEqual(client.post(URL, json=body(self.raw)).status_code, 400)
        with self.assertRaises(ValueError):
            custom.import_checkpoint(self.raw, 'custom')

    def test_metadata_published_last_and_failure_cleanup(self):
        import godseye.core as core
        write = core.write_json
        def inspect_then_write(path, value):
            if path.name.startswith('checkpoint-'):
                self.assertEqual(len(self.store.checkpoints()), 2)
                self.assertEqual((self.store.path / (value['id'] + '.npz')).read_bytes(), self.raw)
            return write(path, value)
        with patch.object(core, 'write_json', side_effect=inspect_then_write):
            row = self.store.import_checkpoint(self.raw, 'Atomic')
        self.assertIn(row, self.store.checkpoints())
        before = {p: p.read_bytes() for p in self.store.path.iterdir()}
        with patch.object(core, 'write_json', side_effect=OSError('Injected failure')):
            with self.assertRaises(OSError):
                self.store.import_checkpoint(self.raw, 'Failed')
        self.assertEqual(before, {p: p.read_bytes() for p in self.store.path.iterdir()})
        self.store._import_lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError, 'already in progress'):
                self.store.import_checkpoint(self.raw, 'Busy')
        finally:
            self.store._import_lock.release()

    def test_cli_and_bounded_local_reader(self):
        source = self.root / 'private-source.npz'
        source.write_bytes(self.raw)
        env = dict(os.environ, GODSEYE_DATA_DIR=str(self.store.path))
        result = subprocess.run([sys.executable, '-m', 'godseye', 'import-checkpoint',
                                 '--file', str(source), '--name', 'CLI fixture'],
                                env=env, text=True, capture_output=True, check=True)
        row = json.loads(result.stdout)
        self.assertEqual(row['provenance'], '')
        self.assertNotIn(str(source), json.dumps(self.store.checkpoints()))
        self.assertEqual(digest(self.store.weights(row['id'])), row['sha256'])
        source.write_bytes(b'x' * (MAX_NPZ + 1))
        with self.assertRaises(ValueError):
            read_local(source)
        with self.assertRaises(ValueError):
            read_local(self.root)


class StreamBounds(unittest.IsolatedAsyncioTestCase):
    async def test_route_specific_stream_limit_and_import_slot(self):
        reached = []
        async def downstream(scope, receive, send):
            reached.append(await receive())
            await send({'type': 'http.response.start', 'status': 204, 'headers': []})
            await send({'type': 'http.response.body', 'body': b''})
        boundary = Boundary(downstream, ['testserver'], None)
        async def request(path, chunks, method='POST'):
            consumed, sent = [], []
            async def receive():
                consumed.append(True)
                data = next(chunks)
                if isinstance(data, BaseException):
                    raise data
                return data
            async def send(message):
                sent.append(message)
            scope = dict(type='http', path=path, method=method, scheme='http', headers=[
                (b'host', b'testserver'), (b'content-type', b'application/json')])
            await boundary(scope, receive, send)
            return consumed, sent
        def chunks(total):
            return iter([{'type': 'http.request', 'body': b'x' * (total // 2), 'more_body': True},
                         {'type': 'http.request', 'body': b'x' * (total - total // 2), 'more_body': True},
                         {'type': 'http.request', 'body': b'', 'more_body': False}])
        for path, method, limit in ((URL, 'POST', MAX_JSON), ('/api/v1/checkpoints', 'POST', 65536),
                                    (URL + '/', 'POST', 65536), (URL, 'PUT', 65536),
                                    ('/api/v1/experiments/start', 'POST', 65536)):
            consumed, sent = await request(path, chunks(limit + 1), method)
            self.assertEqual(len(consumed), 2)
            self.assertIn(sent[0]['status'], (400, 413))  # Existing experiment envelope.
        self.assertEqual(reached, [])
        consumed, sent = await request(URL, chunks(MAX_JSON))
        self.assertEqual(sent[0]['status'], 204)
        self.assertEqual(len(reached[-1]['body']), MAX_JSON)
        # Admission occurs before reading another potentially large request.
        boundary.import_slot.acquire()
        try:
            consumed, sent = await request(URL, iter(()))
            self.assertEqual(sent[0]['status'], 429)
            self.assertEqual(consumed, [])
        finally:
            boundary.import_slot.release()
        for messages in (iter([{'type': 'http.disconnect'}]), iter([RuntimeError('Read failed')])):
            try:
                await request(URL, messages)
            except RuntimeError:
                pass
            self.assertTrue(boundary.import_slot.acquire(blocking=False))
            boundary.import_slot.release()


if __name__ == '__main__':
    unittest.main()
