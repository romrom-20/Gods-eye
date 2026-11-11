# A complete local HTTP experiment

No provider key, Docker or paid API is needed. This known four-weight example
checks editing and measurement mechanics; it does not demonstrate AI repair.
Install the server extra as described in [installation](install.md). In terminal A,
run `godseye serve` and leave it running. Use its printed URL below if different.

In terminal B, save this as `http-example.py` and run `python http-example.py`.
It uses Python's standard HTTP library directly, without the God's Eye client.
The one-second polling interval repeats only GET reads, never a write. The
bounded evaluation plays two games per version, capped at 100 steps each.

```python
import json
import time
from urllib.request import Request, urlopen

BASE = 'http://127.0.0.1:8787'


def http(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = Request(BASE + '/api/v1/' + path, data=data,
                      headers={'Content-Type': 'application/json'})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


edit = dict(base_id='paper', patch='W3[0:8:2, 1] = 0',
            hypothesis='Removing the left circuit reduces score.')
preview = http('patches/preview', edit)
branch = http('checkpoints', dict(edit, expected_parent_sha256=preview['parent_sha256']))
job = http('jobs', dict(base_id='paper', candidate_id=branch['id'],
                        episodes=2, seed=1000, max_steps=100))
print('Saved job:', job['id'])
for attempt in range(120):
    status = http('jobs/' + job['id'])
    if status['status'] == 'succeeded':
        result = http('runs/' + status['run_id'])
        print('Paired mean change:', result['paired_mean_delta'])
        print('Paired standard error:', result['paired_se'])
        break
    if status['status'] in ('failed', 'cancelled', 'interrupted'):
        raise RuntimeError('Job ended: ' + status['status'])
    time.sleep(1)
else:
    raise TimeoutError('Poll the saved job again; this did not cancel it.')
```

The original `paper` checkpoint remains unchanged. A small capped sample may be
inconclusive. Inspect the saved run in `/lab#history`; this script does not export
or apply the edited model. For request/response schemas, open `/api.html` or
`/api/v1/openapi.json` on your local server.

If a write disconnects, do not repeat the whole script automatically: the
checkpoint or job may already exist. Read `/api/v1/state` and `/api/v1/jobs` to
reconcile before deciding on another submission. If you configured
`GODSEYE_API_TOKEN`, explicitly add its bearer header to your requests; keep the
token out of URLs, source files and logs. This example assumes the default local
server with no token configured.
