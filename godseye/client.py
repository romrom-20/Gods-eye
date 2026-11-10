"""Small dependency-free HTTP client for researchers and coding agents."""
import json
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class APIError(RuntimeError):
    def __init__(self, status, payload):
        self.status, self.payload = status, payload
        super().__init__(payload.get('error', 'API request failed'))


class Client:
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

    def state(self):
        return self._request('state')

    def tensor(self, checkpoint='paper', name='W3'):
        return self._request('tensor?' + urlencode({'id': checkpoint, 'name': name}))

    def preview(self, base, patch, hypothesis, **options):
        return self._request('patches/preview', dict(base_id=base, patch=patch, hypothesis=hypothesis, **options))

    def patch(self, base, patch, hypothesis, **options):
        return self._request('checkpoints', dict(base_id=base, patch=patch, hypothesis=hypothesis, **options))

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
