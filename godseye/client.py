"""Small dependency-free HTTP client for researchers and coding agents."""
import base64
import errno
import json
import socket
import ssl
import time
from http.client import HTTPException, RemoteDisconnected
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class APIError(RuntimeError):
    def __init__(self, status, payload):
        self.status, self.payload = status, payload
        super().__init__(payload.get('error', 'API request failed'))


class TransportError(ConnectionError):
    """No usable HTTP response; a write may already have been admitted.

    ``reason`` and ``errno`` preserve safe transport classification. The chained
    cause is sanitized: upstream exception text can contain credentials or URLs.
    """
    def __init__(self, reason, error_number, uncertain_write):
        self.reason = reason
        self.uncertain_write = uncertain_write
        message = ("Cannot get a response from the God's Eye API (" + reason + "). "
                   "Run `godseye serve` in a separate terminal and keep it running; "
                   "check that Client(url=...) matches the server's printed URL and port.")
        if uncertain_write:
            message += (" The write outcome is unknown; work may have been admitted. "
                        "Do not submit it again automatically. Inspect saved jobs/state first; "
                        "retain any original idempotency key.")
        super().__init__(message)
        self.errno = error_number


def _transport_failure(error, uncertain_write):
    reason = error.reason if isinstance(error, URLError) else error
    number = getattr(reason, 'errno', None)
    number = number if isinstance(number, int) else None
    if isinstance(reason, (TimeoutError, socket.timeout)):
        category, cause = 'timeout', TimeoutError('API transport timed out')
    elif isinstance(reason, ConnectionRefusedError) or number == errno.ECONNREFUSED:
        category, cause = 'connection_refused', ConnectionRefusedError(number, 'API connection refused')
    elif isinstance(reason, socket.gaierror):
        category, cause = 'name_resolution', socket.gaierror(number, 'API host could not be resolved')
    elif isinstance(reason, ssl.SSLError):
        category, cause = 'tls_error', ssl.SSLError('API TLS connection failed')
    elif isinstance(reason, RemoteDisconnected):
        category, cause = 'disconnected', RemoteDisconnected('API disconnected before a response')
    elif isinstance(reason, ConnectionResetError):
        category, cause = 'connection_reset', ConnectionResetError(number, 'API connection reset')
    else:
        category, cause = 'transport_error', OSError(number, 'API transport failed')
    safe_cause = URLError(cause) if isinstance(error, URLError) else cause
    return TransportError(category, number, uncertain_write), safe_cause


class Client:
    """Store connection settings; only method calls contact the server."""

    def __init__(self, url='http://127.0.0.1:8787', token=None, timeout=30):
        self.url, self.token, self.timeout = url.rstrip('/'), token, timeout

    def _request(self, path, body=None, key=None):
        headers = {'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        if key:
            headers['Idempotency-Key'] = key
        data = None
        if body is not None:
            data = json.dumps(body, allow_nan=False).encode()
            headers['Content-Type'] = 'application/json'
        request = Request(self.url + '/api/v1/' + path, data=data, headers=headers)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as error:
            raise APIError(error.code, json.load(error)) from error
        except (URLError, OSError, HTTPException) as error:
            failure, safe_cause = _transport_failure(error, body is not None)
            raise failure from safe_cause

    def state(self):
        return self._request('state')

    def tensor(self, checkpoint='paper', name='W3'):
        return self._request('tensor?' + urlencode({'id': checkpoint, 'name': name}))

    def preview(self, base, patch, hypothesis, **options):
        return self._request('patches/preview', dict(base_id=base, patch=patch, hypothesis=hypothesis, **options))

    def patch(self, base, patch, hypothesis, **options):
        return self._request('checkpoints', dict(base_id=base, patch=patch, hypothesis=hypothesis, **options))

    def import_checkpoint(self, path, name, provenance=''):
        """One bounded local file read and one HTTP attempt; never retries a write."""
        from .checkpoint_import import metadata, read_local
        metadata(name, provenance)
        return self._request('checkpoints/import', dict(name=name, provenance=provenance,
            npz_base64=base64.b64encode(read_local(path)).decode('ascii')))

    def evaluate(self, base, candidate, idempotency_key=None, **settings):
        return self._request('jobs', dict(base_id=base, candidate_id=candidate, **settings), idempotency_key)

    def job(self, job_id):
        return self._request('jobs/' + job_id)

    def cancel(self, job_id):
        return self._request('jobs/' + job_id + '/cancel', {})

    def wait(self, job_id, timeout=120, interval=0.25):
        if timeout <= 0 or interval <= 0:
            raise ValueError('Timeout and polling interval must be positive')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.job(job_id)
            if job['status'] == 'succeeded':
                return self._request('runs/' + job['run_id'])
            if job['status'] in ('cancelled', 'failed', 'interrupted'):
                raise RuntimeError(job.get('error', job['status']))
            time.sleep(interval)
        raise TimeoutError('Job is still running; poll it again or cancel explicitly.')
