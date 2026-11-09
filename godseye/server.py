import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .core import Store, tensor_summary, digest

STATIC = Path(__file__).parent / 'static'


def serve(port=8787):
    store = Store()

    class Handler(BaseHTTPRequestHandler):
        def json_response(self, value, status=200):
            body = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            try:
                route = urlparse(self.path)
                query = parse_qs(route.query)
                if route.path == '/api/state':
                    self.json_response({'checkpoints': store.checkpoints(), 'backend': 'local-numpy',
                                        'parameters': 20486, 'architecture': '600 → 32 → 32 → 6 · tanh'})
                elif route.path == '/api/tensor':
                    weights = store.weights(query.get('id', ['paper'])[0])
                    name = query.get('name', ['W1'])[0]
                    if name not in weights:
                        raise ValueError('Unknown tensor')
                    self.json_response({'name': name, 'values': weights[name].tolist(),
                                        'summary': tensor_summary(weights), 'sha256': digest(weights)})
                elif route.path == '/api/runs':
                    # Return metadata only; traces are loaded on demand.
                    rows = []
                    for path in sorted(store.path.glob('run-*.json'), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
                        row = json.loads(path.read_text())
                        for key in ('base', 'candidate'):
                            row[key].pop('trace', None)
                        rows.append(row)
                    self.json_response(rows)
                elif route.path == '/api/preset/ball-chaser':
                    self.json_response({'patch': (STATIC.parent.parent / 'experiments/ball-chaser.edits').read_text()})
                elif route.path.startswith('/api/run/'):
                    run_id = route.path.rsplit('/', 1)[-1]
                    if len(run_id) != 16 or any(c not in '0123456789abcdef' for c in run_id):
                        raise ValueError('Invalid run id')
                    self.json_response(json.loads((store.path / ('run-' + run_id + '.json')).read_text()))
                else:
                    files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                             '/style.css': ('style.css', 'text/css')}
                    if route.path not in files:
                        self.json_response({'error': 'Not found'}, 404)
                        return
                    name, mime = files[route.path]
                    body = (STATIC / name).read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', mime + '; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    self.wfile.write(body)
            except (ValueError, KeyError, FileNotFoundError) as error:
                self.json_response({'error': str(error)}, 400)

        def do_POST(self):
            try:
                # Same-origin JSON only. This service stays on the loopback interface.
                origin = self.headers.get('Origin')
                allowed = {f'http://127.0.0.1:{port}', f'http://localhost:{port}'}
                if origin and origin not in allowed:
                    self.json_response({'error': 'Origin rejected'}, 403)
                    return
                if self.headers.get_content_type() != 'application/json':
                    raise ValueError('Use application/json')
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 100000:
                    raise ValueError('Invalid request size')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Expected a JSON object')
                if self.path == '/api/patch':
                    result = store.patch(body['base_id'], body['patch'], body['hypothesis'])
                elif self.path == '/api/compare':
                    result = store.run(body['base_id'], body['candidate_id'],
                                       episodes=body.get('episodes', 8), seed=body.get('seed', 1000),
                                       max_steps=body.get('max_steps', 3000))
                else:
                    self.json_response({'error': 'Not found'}, 404)
                    return
                self.json_response(result)
            except (ValueError, TypeError, KeyError, IndexError, SyntaxError, FileNotFoundError) as error:
                self.json_response({'error': str(error)}, 400)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f"God's Eye running at http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
