"""Offline transport diagnostics and the documented raw HTTP workflow."""
import contextlib
import errno
from http.client import RemoteDisconnected
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
from pathlib import Path
import socket
import tempfile
import threading
import time
import traceback
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from godseye.client import APIError, Client, TransportError


class TransportTests(unittest.TestCase):
    def test_constructor_is_offline_and_refused_read_is_actionable(self):
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            url = 'http://127.0.0.1:' + str(reservation.getsockname()[1])
        # Release the socket: a bound but unlistening socket can time out on macOS.
        with patch('godseye.client.urlopen') as opened:
            client = Client(url, timeout=2)
            opened.assert_not_called()
        with self.assertRaises(TransportError) as caught:
            client.state()
        error = caught.exception
        self.assertEqual(error.reason, 'connection_refused')
        self.assertEqual(error.errno, errno.ECONNREFUSED)
        self.assertFalse(error.uncertain_write)
        self.assertIsInstance(error.__cause__, URLError)
        self.assertIsInstance(error.__cause__.reason, ConnectionRefusedError)
        self.assertIn('godseye serve', str(error))
        self.assertIn('separate terminal', str(error))
        self.assertIn('Client(url=...)', str(error))

    def test_diagnostics_and_traceback_do_not_echo_secrets(self):
        secret = 'super-private-test-value'
        failures = [URLError(secret), URLError(TimeoutError(secret)),
                    ConnectionResetError(errno.ECONNRESET, secret),
                    RemoteDisconnected(secret)]
        for failure in failures:
            with self.subTest(type=type(failure).__name__), \
                 patch('godseye.client.urlopen', side_effect=failure) as opened:
                client = Client('http://user:'+secret+'@127.0.0.1:1/?token='+secret,
                                token=secret)
                try:
                    client.patch('paper', 'W3[0, 1] = 0', 'test')
                except TransportError as error:
                    self.assertTrue(error.uncertain_write)
                    self.assertIn('may have been admitted', str(error))
                    formatted = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
                    self.assertNotIn(secret, formatted)
                    self.assertNotIn('http://', str(error))
                else:
                    self.fail('Expected TransportError')
                self.assertEqual(opened.call_count, 1)

    def test_timeout_classification_and_http_error_boundary(self):
        for failure in [TimeoutError('private'), URLError(socket.timeout('private'))]:
            with patch('godseye.client.urlopen', side_effect=failure) as opened:
                with self.assertRaises(TransportError) as caught:
                    Client().state()
                self.assertEqual(caught.exception.reason, 'timeout')
                self.assertFalse(caught.exception.uncertain_write)
                self.assertEqual(opened.call_count, 1)
        response = HTTPError('http://127.0.0.1/', 403, 'Forbidden', {},
                             io.BytesIO(b'{"error":"Not authorized"}'))
        with patch('godseye.client.urlopen', side_effect=response):
            with self.assertRaises(APIError) as caught:
                Client().state()
        self.assertEqual(caught.exception.status, 403)

    def test_write_read_by_peer_then_disconnected_is_never_retried(self):
        bodies = []

        class Disconnect(BaseHTTPRequestHandler):
            def do_POST(self):
                bodies.append(self.rfile.read(int(self.headers['Content-Length'])))
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Disconnect)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = Client('http://127.0.0.1:' + str(server.server_port))
            with self.assertRaises(TransportError) as caught:
                client.evaluate('paper', 'paper', idempotency_key='keep-this-key')
            self.assertEqual(caught.exception.reason, 'disconnected')
            self.assertTrue(caught.exception.uncertain_write)
            self.assertIsInstance(caught.exception.__cause__, RemoteDisconnected)
            self.assertEqual(len(bodies), 1)
            self.assertIn('idempotency key', str(caught.exception))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


class RealHTTPExampleTests(unittest.TestCase):
    def test_documented_raw_http_and_client_against_temporary_server(self):
        import uvicorn
        from godseye.core import Store, digest
        from godseye.server import create_app

        with tempfile.TemporaryDirectory(prefix='client-http-example-') as directory, \
             socket.socket() as listener:
            store = Store(Path(directory))
            original = digest(store.weights('paper'))
            app = create_app(store)  # No orchestrator, operator settings or provider.
            listener.bind(('127.0.0.1', 0))
            base = 'http://127.0.0.1:' + str(listener.getsockname()[1])
            server = uvicorn.Server(uvicorn.Config(app, log_level='error'))
            thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
            thread.start()
            try:
                deadline = time.monotonic() + 10
                while not server.started:
                    if not thread.is_alive() or time.monotonic() > deadline:
                        self.fail('Temporary HTTP server did not start')
                    time.sleep(.01)
                doc = (Path(__file__).resolve().parents[1] / 'docs/http-example.md').read_text()
                example = doc.split('```python\n', 1)[1].split('```', 1)[0]
                example = example.replace("BASE = 'http://127.0.0.1:8787'", 'BASE = ' + repr(base))
                namespace = {}
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    exec(compile(example, 'docs/http-example.md', 'exec'), namespace)
                self.assertIn('Paired mean change:', output.getvalue())
                self.assertEqual(namespace['status']['status'], 'succeeded')
                self.assertEqual(len(namespace['result']['base']['episodes']), 2)
                client = Client(base)
                preview = client.preview('paper', 'W3[0:8:2, 1] = 0', 'Known edit')
                branch = client.patch('paper', 'W3[0:8:2, 1] = 0', 'Known edit',
                                      expected_parent_sha256=preview['parent_sha256'])
                job = client.evaluate('paper', branch['id'], episodes=2, max_steps=100,
                                      idempotency_key='client-example')
                result = client.wait(job['id'], interval=.01)
                self.assertIn('paired_se', result)
                self.assertEqual(digest(store.weights('paper')), original)
            finally:
                server.should_exit = True
                thread.join(timeout=10)
                self.assertFalse(thread.is_alive(), 'Owned server did not stop')


if __name__ == '__main__':
    unittest.main()
