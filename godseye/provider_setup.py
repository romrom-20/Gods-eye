"""Loopback-only credential setup. Never contacts a provider or returns a saved key."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import stat
import tempfile
import time
import webbrowser

STATIC = Path(__file__).parent / 'static'


class ProviderSettings:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else Path.home() / '.godseye-secrets'

    def _secure_directory(self):
        if self.directory.is_symlink():
            raise ValueError('The settings directory must not be a symbolic link')
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.stat().st_uid != os.getuid():
            raise ValueError('Settings directory must belong to your OS user')
        self.directory.chmod(0o700)

    def _file(self, name):
        path = self.directory / name
        if path.is_symlink() or (path.exists() and not stat.S_ISREG(path.stat().st_mode)):
            raise ValueError('Settings files must be regular files, not symbolic links')
        return path

    def status(self, provider=None):
        # Read configuration only. Never read the saved secret back into the UI.
        if self.directory.is_symlink():
            raise ValueError('The settings directory must not be a symbolic link')
        config = self._file('provider.json')
        settings = json.loads(config.read_text()) if config.exists() else {}
        provider = provider or settings.get('provider', 'openai')
        if provider not in ('openai', 'openrouter', 'huggingface'):
            raise ValueError('Unsupported provider')
        profile = settings.get('profiles', {}).get(provider, settings if provider == settings.get('provider', 'openai') else {})
        return {'provider': provider, 'configured': self._file(provider + '-api-key').exists(),
                'model': profile.get('model', ''), 'routing': profile.get('routing', 'price'),
                'directory': str(self.directory), 'env_file': str(self.directory / 'provider.env')}

    def _write(self, name, content):
        path = self._file(name)
        fd, temporary = tempfile.mkstemp(prefix='.pending-', dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save(self, key, model, provider="openai", routing="price"):
        if provider not in ("openai", "openrouter", "huggingface") or routing not in ("price", "latency", "throughput"):
            raise ValueError("Unsupported provider or routing policy")
        if not isinstance(key, str) or not isinstance(model, str):
            raise ValueError('Key and model must be text')
        key, model = key.strip(), model.strip()
        pattern = r'hf_[A-Za-z0-9_-]{16,1024}' if provider == 'huggingface' else r'sk-[A-Za-z0-9_-]{16,1024}'
        if key and not re.fullmatch(pattern, key):
            raise ValueError('Enter a valid key for the selected provider.')
        if model and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}', model):
            raise ValueError('Enter a model ID without spaces or shell characters')
        if not key and not self.status(provider)['configured']:
            raise ValueError('Enter an API key for this provider')
        self._secure_directory()
        # Validate all destinations before any writes.
        for name in (provider + '-api-key', 'provider.json', 'provider.env'):
            self._file(name)
        if key:
            self._write(provider + '-api-key', key + '\n')
        else:
            self._file(provider + '-api-key').chmod(0o600)
        config = self._file('provider.json')
        previous = json.loads(config.read_text()) if config.exists() else {}
        profiles = previous.get('profiles', {})
        if previous.get('model') and not profiles:
            profiles[previous.get('provider', 'openai')] = {'model': previous['model'], 'routing': 'price'}
        profiles[provider] = {'model': model, 'routing': routing}
        self._write('provider.json', json.dumps({'provider': provider, 'model': model, 'profiles': profiles}) + '\n')
        env = 'REPAIR_AGENT_KEY_FILE=' + shlex.quote(str(self.directory / (provider + '-api-key'))) + '\n'
        env += 'REPAIR_AGENT_MODEL=' + shlex.quote(model) + '\n'
        env += 'REPAIR_AGENT_PROVIDER=' + provider + '\n'
        env += 'REPAIR_AGENT_ROUTING=' + routing + '\n'
        self._write('provider.env', env)
        return self.status()


def create_server(settings=None, port=0):
    settings = settings or ProviderSettings()
    csrf = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log request paths, bodies, or credentials.

        def reply(self, body, status=200, mime='application/json'):
            if isinstance(body, dict):
                body = json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', mime)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def allowed(self, write=False):
            expected = '127.0.0.1:' + str(self.server.server_port)
            if self.headers.get('Host') != expected:
                return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + expected:
                return False
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                return False
            return not write or (origin == 'http://' + expected and hmac.compare_digest(
                self.headers.get('X-Setup-Token', '').encode(), csrf.encode()))

        def do_GET(self):
            if not self.allowed():
                return self.reply({'error': 'Request rejected'}, 403)
            if self.path == '/':
                html = (STATIC / 'provider-setup.html').read_text().replace('__SETUP_TOKEN__', csrf)
                return self.reply(html.encode(), mime='text/html; charset=utf-8')
            if self.path == '/setup.js':
                return self.reply((STATIC / 'provider-setup.js').read_bytes(), mime='text/javascript')
            if self.path == '/status' or self.path.startswith('/status?provider='):
                try:
                    return self.reply(settings.status(self.path.split('=', 1)[1] if '=' in self.path else None))
                except (ValueError, OSError):
                    return self.reply({'error': 'Cannot access local settings safely'}, 400)
            self.reply({'error': 'Not found'}, 404)

        def do_POST(self):
            if not self.allowed(write=True):
                return self.reply({'error': 'Request rejected'}, 403)
            if self.path != '/save':
                return self.reply({'error': 'Not found'}, 404)
            if self.headers.get_content_type() != 'application/json':
                return self.reply({'error': 'Use JSON'}, 415)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 8192 or self.headers.get('Transfer-Encoding'):
                    return self.reply({'error': 'Invalid request size'}, 413)
                data = json.loads(self.rfile.read(size))
                if type(data) is not dict or not {'key', 'model'} <= set(data) or set(data) - {'key', 'model', 'provider', 'routing'}:
                    return self.reply({'error': 'Expected key and model'}, 400)
                result = settings.save(data['key'], data['model'], data.get('provider', 'openai'), data.get('routing', 'price'))
            except ValueError as error:
                # Validation messages are fixed strings, never interpolate the key.
                message = str(error) if type(error) is ValueError else 'Invalid request'
                return self.reply({'error': message}, 400)
            except OSError:
                return self.reply({'error': 'Could not save local settings. Check directory permissions.'}, 500)
            self.reply(result)

    server = HTTPServer(('127.0.0.1', port), Handler)
    server.timeout = 1
    # Bound slow requests to this local, single-purpose setup process.
    original_get_request = server.get_request
    def get_request():
        connection, address = original_get_request()
        connection.settimeout(5)
        return connection, address
    server.get_request = get_request
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8810)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    server = create_server(port=args.port)
    url = f'http://127.0.0.1:{server.server_port}'
    print('Open key setup: ' + url, flush=True)
    print('No provider calls. Setup closes after 30 minutes or Ctrl+C.', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    deadline = time.monotonic() + 1800
    try:
        while time.monotonic() < deadline:
            server.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
