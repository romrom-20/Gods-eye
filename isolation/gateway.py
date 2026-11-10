"""Fixed-destination operator HTTP gateway; no credentials or private mounts.

Internal-only Docker networks may not publish ports. Keep the evaluator internal
and expose its two authenticated routes through this separate loopback service.
This is not a general HTTP proxy: destinations, paths and methods are fixed.
"""
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer


class Gateway(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.connection.settimeout(130)
        if self.path not in ('/rpc', '/report'):
            self.send_error(404)
            return
        try:
            size = int(self.headers.get('Content-Length', '-1'))
            if (self.headers.get('Transfer-Encoding') or not 0 < size <= 65536
                    or self.headers.get_content_type() != 'application/json'):
                self.send_error(400)
                return
            body = self.rfile.read(size)
            if len(body) != size:
                self.send_error(400)
                return
            connection = http.client.HTTPConnection('evaluator', 8790, timeout=120)
            try:
                connection.request('POST', self.path, body, {
                    'Authorization': self.headers.get('Authorization', ''),
                    'Content-Type': 'application/json',
                })
                response = connection.getresponse()
                result = response.read()
                self.send_response(response.status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(result)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(result)
            finally:
                connection.close()
        except (OSError, ValueError, http.client.HTTPException):
            self.send_error(502)


if __name__ == '__main__':
    HTTPServer(('0.0.0.0', 8790), Gateway).serve_forever()
