"""Body-framing regressions for the local HTTP/1.0 provider setup server.

Only synthetic in-memory callbacks are used; no saved profiles or provider calls.
"""
from email.message import Message
import http.client
import io
import json
import socket
import threading
import unittest
from unittest.mock import Mock, patch

from godseye.provider_discovery import ProviderDiscovery
from godseye.provider_setup import (
    MAX_REJECT_DRAIN, ProviderSettings, create_server,
)


class ProviderSetupTransportTests(unittest.TestCase):
    def setUp(self):
        self.settings = Mock(spec=ProviderSettings)
        self.discovery = Mock(spec=ProviderDiscovery)
        self.server = create_server(self.settings, discovery=self.discovery)
        self.addCleanup(self.server.server_close)
        self.host = '127.0.0.1:' + str(self.server.server_port)
        self.handler_class = self.server.RequestHandlerClass
        # GET the actual page to obtain its token, without inspecting secrets.
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.shutdown)
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request('GET', '/')
            page = connection.getresponse().read().decode()
        finally:
            connection.close()
        self.token = page.split('name="setup-token" content="', 1)[1].split('"', 1)[0]
        self.headers = {
            'Host': self.host, 'Origin': 'http://' + self.host,
            'X-Setup-Token': self.token, 'Content-Type': 'application/json',
        }

    def assert_inert(self):
        self.assertEqual(self.settings.method_calls, [])
        self.assertEqual(self.discovery.method_calls, [])

    def handler(self, path='/save', body=b'{}', headers=None, lengths=None):
        handler = object.__new__(self.handler_class)
        handler.server = self.server
        handler.path = path
        handler.headers = Message()
        values = dict(self.headers)
        values.update(headers or {})
        for name, value in values.items():
            handler.headers[name] = value
        if lengths is None:
            lengths = [str(len(body))]
        for value in lengths:
            handler.headers['Content-Length'] = value
        handler.rfile = io.BytesIO(body)
        handler.connection = Mock()
        handler.connection.gettimeout.return_value = 5
        handler.reply = Mock()
        return handler

    def test_framed_early_rejections_consume_before_reply_on_every_post_route(self):
        # An ordering assertion, independent of whether an OS happens to send RST.
        cases = [({'Host': 'evil.example'}, 403),
                 ({'Origin': 'https://evil.example'}, 403),
                 ({'X-Setup-Token': 'wrong'}, 403),
                 ({'Sec-Fetch-Site': 'cross-site'}, 403),
                 ({'Content-Type': 'text/plain'}, 415), ({}, 413)]
        for path in ('/save', '/models', '/test-connection', '/unknown'):
            for headers, status in cases:
                with self.subTest(path=path, headers=headers):
                    body = b'x' * 9000 if status == 413 else b'{}'
                    handler = self.handler(path, body, headers)
                    # Unknown routes are rejected before content type or size.
                    expected = 404 if path == '/unknown' and status != 403 else status

                    def reply(value, actual):
                        self.assertEqual(actual, expected)
                        self.assertEqual(handler.rfile.tell(), len(body),
                                         'Response written before consuming framed request body')

                    handler.reply.side_effect = reply
                    handler.do_POST()
                    handler.reply.assert_called_once()
                    self.assertTrue(handler.close_connection)
        self.assert_inert()

    def test_ambiguous_framing_and_bodies_over_drain_cap_are_never_consumed(self):
        cases = [([], {}), (['0'], {}), (['-1'], {}), (['+2'], {}),
                 (['not-a-size'], {}), (['9' * 1000], {}), (['2, 2'], {}),
                 (['2', '2'], {}), (['2', '3'], {}),
                 (['2'], {'Transfer-Encoding': 'chunked'}),
                 ([], {'Transfer-Encoding': 'chunked'}),
                 (['2'], {'Transfer-Encoding': ''}),
                 ([str(MAX_REJECT_DRAIN + 1)], {})]
        for lengths, headers in cases:
            with self.subTest(lengths=lengths, headers=headers):
                handler = self.handler(headers=headers, lengths=lengths)
                handler.rfile = Mock(wraps=handler.rfile)
                handler.do_POST()
                handler.reply.assert_called_once_with({'error': 'Invalid request size'}, 413)
                handler.rfile.read1.assert_not_called()
                self.assertTrue(handler.close_connection)
        handler = self.handler(body=b'x' * MAX_REJECT_DRAIN)
        handler.do_POST()
        self.assertEqual(handler.rfile.tell(), MAX_REJECT_DRAIN)
        handler.reply.assert_called_once_with({'error': 'Invalid request size'}, 413)
        self.assert_inert()

    def test_absolute_drain_deadline_stops_trickling_body_and_restores_timeout(self):
        handler = self.handler(body=b'x' * 10, headers={'Host': 'evil.example'})
        clock = Mock()
        now = [0.0]
        clock.monotonic.side_effect = lambda: now[0]
        stream = handler.rfile
        handler.rfile = Mock(wraps=stream)

        def trickle(size):
            now[0] += .4
            return stream.read1(1)

        handler.rfile.read1.side_effect = trickle
        with patch('godseye.provider_setup.time', clock):
            handler.do_POST()
        self.assertEqual(stream.tell(), 3)
        self.assertEqual(handler.connection.settimeout.call_args.args, (5,))
        handler.reply.assert_called_once_with({'error': 'Request rejected'}, 403)
        self.assert_inert()

    def test_incomplete_and_timed_out_bodies_never_admit_actions(self):
        for path in ('/save', '/models', '/test-connection'):
            data = {'provider': 'openai', 'key': 'sk-test-only-not-a-real-key', 'model': 'dummy'}
            if path == '/test-connection':
                data['confirmed'] = True
            body = json.dumps(data).encode()
            for rejection in (False, True):
                for failure in ('eof', 'timeout', 'reset'):
                    with self.subTest(path=path, rejection=rejection, failure=failure):
                        handler = self.handler(path, body,
                                               {'Host': 'evil.example'} if rejection else {},
                                               lengths=[str(len(body) + 10)])
                        if failure != 'eof':
                            handler.rfile = Mock(wraps=handler.rfile)
                            error = TimeoutError if failure == 'timeout' else ConnectionResetError
                            handler.rfile.read1.side_effect = error('private-request-canary')
                        handler.do_POST()
                        value, status = handler.reply.call_args.args
                        self.assertEqual(status, 403 if rejection else 400)
                        self.assertNotIn('private-request-canary', json.dumps(value))
        self.assert_inert()

    def test_truncated_complete_json_is_not_executed_and_response_is_readable(self):
        for path in ('/save', '/models', '/test-connection'):
            data = {'provider': 'openai', 'key': 'sk-test-only-not-a-real-key', 'model': 'dummy'}
            if path == '/test-connection':
                data['confirmed'] = True
            body = json.dumps(data).encode()
            for rejection in (False, True):
                with self.subTest(path=path, rejection=rejection):
                    connection = http.client.HTTPConnection(
                        '127.0.0.1', self.server.server_port, timeout=3)
                    try:
                        connection.putrequest('POST', path, skip_host=True)
                        values = dict(self.headers)
                        if rejection:
                            values['Host'] = 'evil.example'
                        values['Content-Length'] = str(len(body) + 10)
                        for name, value in values.items():
                            connection.putheader(name, value)
                        connection.endheaders(body)
                        connection.sock.shutdown(socket.SHUT_WR)
                        response = connection.getresponse()
                        self.assertEqual(response.status, 403 if rejection else 400)
                        self.assertEqual(json.loads(response.read())['error'],
                                         'Request rejected' if rejection else 'Incomplete request body')
                    finally:
                        connection.close()
        self.assert_inert()

    def test_delayed_split_body_has_readable_complete_rejection(self):
        cases = [('/save', {'Host': 'evil.example'}, 403, b'{}'),
                 ('/models', {'Content-Type': 'text/plain'}, 415, b'{}'),
                 ('/test-connection', {'X-Setup-Token': 'wrong'}, 403, b'{}'),
                 ('/unknown', {}, 404, b'{}'),
                 ('/save', {}, 413, b'x' * 9000)]
        original_read = self.handler_class.read_body
        original_reply = self.handler_class.reply
        for path, headers, status, body in cases:
            with self.subTest(path=path, status=status):
                consumed_first_chunk = threading.Event()
                replied = threading.Event()

                def observe_read(handler, *args, **kwargs):
                    stream = handler.rfile
                    observed = Mock(wraps=stream)

                    def read1(size):
                        chunk = stream.read1(size)
                        if chunk:
                            consumed_first_chunk.set()
                        return chunk

                    observed.read1.side_effect = read1
                    handler.rfile = observed
                    try:
                        return original_read(handler, *args, **kwargs)
                    finally:
                        handler.rfile = stream

                def observe_reply(handler, *args, **kwargs):
                    replied.set()
                    return original_reply(handler, *args, **kwargs)

                connection = http.client.HTTPConnection(
                    '127.0.0.1', self.server.server_port, timeout=3)
                with patch.object(self.handler_class, 'read_body', observe_read), \
                        patch.object(self.handler_class, 'reply', observe_reply):
                    try:
                        connection.putrequest('POST', path, skip_host=True)
                        values = dict(self.headers, **headers)
                        values['Content-Length'] = str(len(body))
                        for name, value in values.items():
                            connection.putheader(name, value)
                        connection.endheaders(body[:1])
                        # Delay the rest until the handler actually consumed a
                        # partial body. No sleeps or probabilistic reset loops.
                        self.assertTrue(consumed_first_chunk.wait(2))
                        self.assertFalse(replied.is_set(), 'Early reply raced the remaining body')
                        connection.send(body[1:])
                        response = connection.getresponse()
                        self.assertEqual(response.status, status)
                        self.assertEqual(response.version, 10)
                        self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                        payload = response.read()
                        self.assertEqual(len(payload), int(response.getheader('Content-Length')))
                        self.assertIn('error', json.loads(payload))
                    finally:
                        connection.close()
        self.assert_inert()


if __name__ == '__main__':
    unittest.main()
