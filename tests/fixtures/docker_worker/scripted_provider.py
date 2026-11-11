"""Test-image entrypoint. Never copied into the production agent image."""
import json
import os
from pathlib import Path
import time
import urllib.request

import agent_adapter as adapter


# Fail closed: even a fixture bug cannot send the dummy credential to a provider.
real_urlopen = urllib.request.urlopen


def local_only(request, *args, **kwargs):
    assert request.full_url == 'http://evaluator:8790/rpc', request.full_url
    return real_urlopen(request, *args, **kwargs)


urllib.request.urlopen = local_only
real_post = adapter.post
calls = 0


def scripted_post(url, token, body):
    global calls
    if url == 'http://evaluator:8790/rpc':
        return real_post(url, token, body)
    assert url == adapter.PROVIDER_URLS['openai']
    assert token == 'dummy-docker-worker-only'
    assert token not in json.dumps(body)
    assert {t['name'] for t in body['tools']} == set(adapter.FIELDS)
    assert body['store'] is False
    assert body['max_output_tokens'] == int(os.environ['REPAIR_AGENT_MAX_OUTPUT_TOKENS'])
    calls += 1
    # Host test observes the real worker/container before allowing progress.
    while not Path('/evidence/release').exists():
        time.sleep(.025)
    model = body['model']
    if model == 'scripted-error':
        raise ConnectionError('dummy-docker-worker-only must be redacted')
    if model == 'scripted-missing':
        return {'output': []}
    outputs = [m for m in body['input'] if m.get('type') == 'function_call_output']
    if not outputs:
        name, args = 'list', {}
    else:
        cases = json.loads(outputs[0]['output'])['cases']
        index = len(outputs) - 1
        if index >= len(cases):
            return dict(output=[], usage=dict(input_tokens=2, output_tokens=3))
        case = cases[index]
        name, args = 'freeze', dict(case_id=case['id'], candidate_id=case['root_id'])
    return dict(usage=dict(input_tokens=2, output_tokens=3), output=[dict(
        type='function_call', name=name, arguments=json.dumps(args), call_id=str(calls))])


adapter.post = scripted_post
raise SystemExit(adapter.main())
