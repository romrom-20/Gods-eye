"""SCRIPTED contract-v1 browser fixture. Never imports an LM runtime or executes a model.

Uses actual historical 70-attempt evidence as read-only input; admission, progress and
cancellation are scripted UI test transport, not a new model execution. Bind only a
new dedicated loopback port. Run with the existing goal-ui test venv, not LM Python.
"""
import argparse
import copy
import json
import tempfile
from pathlib import Path

import uvicorn
from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from godseye.core import Store
from godseye.export import export_demo
from godseye.server import create_app
from godseye.lm.task_contract import TaskSpec, canonical, validate_spec
from godseye.lm.task_suite import validate_record, freeze_selection, evaluate
from godseye.web_assets import page_html

ROOT = Path(__file__).resolve().parents[2]
HISTORY = json.loads((ROOT / 'experiments/local_lm_task_validation.json').read_text())
validate_spec(HISTORY['spec'])
SPEC = TaskSpec(canonical(HISTORY['spec']))
FIELDS = ('attempt_id', 'case_id', 'split', 'variant', 'status', 'output',
          'input_tokens', 'output_tokens', 'elapsed_seconds')
ATTEMPTS = [validate_record(dict({k: a[k] for k in FIELDS}, spec_sha256=SPEC.sha256), SPEC)
            for a in HISTORY['attempts']]
REPORT = evaluate(SPEC, freeze_selection(SPEC, ATTEMPTS), ATTEMPTS)
assert len(ATTEMPTS) == 70 and sum(a['status'] == 'budget_limited' for a in ATTEMPTS) == 1
assert REPORT['verdict'] == 'not_evaluated' and REPORT['status'] == 'incomplete'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18996)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='lm-scripted-browser-') as directory:
        path = Path(directory)
        app = create_app(Store(path / 'store'))
        export_path = export_demo(path / 'recorded')
        assert len(list(export_path.iterdir())) == 13, 'Preserve the existing static allowlist'
        app.mount('/recorded', StaticFiles(directory=export_path))
        control = {'mode': 'budget', 'jobs': {}, 'bindings': {}, 'polls': {}, 'calls': [], 'starts': 0}

        def error(message, status=422, code='invalid_request'):
            return JSONResponse({'schema_version': 1, 'error': message, 'code': code}, status_code=status)

        def envelope(job):
            return {'schema_version': 1, 'job': copy.deepcopy(job)}

        def make_job(index):
            return dict(id=f'scripted-{index}', spec_sha256=SPEC.sha256,
                        created_at='2026-11-13T12:00:00Z', updated_at='2026-11-13T12:00:00Z',
                        status='running', reason=None, phase='development',
                        progress={'reserved_attempts': 14, 'finished_attempts': 14, 'max_attempts': 126},
                        result_available=False, selected_delta_available=False)

        @app.middleware('http')
        async def scripted_transport(request, call_next):
            route = request.url.path
            if route.startswith('/api/'):
                control['calls'].append({'path': route, 'method': request.method})
            if route == '/lab':
                html = page_html('index.html', ROOT / 'godseye/static')
                html = html.replace('<body>', '<body><div id="scripted-label" style="background:#193642;color:#fff;padding:10px 20px;text-align:center;position:relative;z-index:10000">SCRIPTED UI TRANSPORT · No model execution · Historical evidence replay</div>')
                return HTMLResponse(html)
            if not route.startswith('/api/v1/lm'):
                return await call_next(request)
            suffix = route.removeprefix('/api/v1/lm')
            body = await request.json() if request.method == 'POST' else None
            mode = control['mode']
            if suffix == '/capabilities':
                if mode == 'old':
                    return error('Scripted old server: route missing', 404, 'not_found')
                if mode == 'unauthorized':
                    return error('Authentication required', 401)
                return JSONResponse(dict(schema_version=1, available=mode != 'unavailable',
                    readonly=mode == 'readonly', reason='SCRIPTED runtime readiness; no model load',
                    model=SPEC.to_dict()['model'], execution='local_cpu', supported_goal='correct_bounded_json',
                    sample_request='Improve JSON schema adherence',
                    limits={'max_attempts': 126, 'max_new_tokens': 96, 'max_worker_seconds': 1800, 'max_concurrency': 1}))
            if suffix == '/plan':
                assert set(body) == {'schema_version', 'request'} and body['schema_version'] == 1
                ready = body['request'].lower().strip().rstrip('.') == 'improve json schema adherence'
                return JSONResponse(dict(schema_version=1, outcome='ready' if ready else 'unsupported',
                    message='SCRIPTED fixed plan. No model execution.' if ready else 'Only the fixed JSON goal is supported.',
                    plan_id='scripted-plan' if ready else None, expires_at='2099-01-01T00:00:00Z' if ready else None,
                    spec_sha256=SPEC.sha256 if ready else None, spec=SPEC.to_dict() if ready else None))
            if suffix == '/jobs' and request.method == 'POST':
                assert set(body) == {'schema_version', 'plan_id', 'spec_sha256', 'idempotency_key'}
                assert body['schema_version'] == 1 and body['plan_id'] == 'scripted-plan' and body['spec_sha256'] == SPEC.sha256
                key = body['idempotency_key']
                if key in control['bindings']:
                    return JSONResponse(envelope(control['jobs'][control['bindings'][key]]))
                control['starts'] += 1
                job = make_job(control['starts'])
                control['jobs'][job['id']] = job
                control['bindings'][key] = job['id']
                if mode == 'lost_ack':
                    return Response('{', status_code=202, media_type='application/json')
                return JSONResponse(envelope(job), status_code=202)
            if suffix == '/resolve':
                assert set(body) == {'schema_version', 'spec_sha256', 'idempotency_key'}
                bound = control['bindings'].get(body['idempotency_key'])
                if not bound:
                    return error('No scripted admission', 404, 'not_found')
                if body['spec_sha256'] != SPEC.sha256:
                    return error('Specification conflict', 409, 'conflict')
                return JSONResponse(envelope(control['jobs'][bound]))
            if suffix == '/jobs':
                return JSONResponse({'schema_version': 1, 'jobs': list(reversed(list(control['jobs'].values())))})
            parts = suffix.strip('/').split('/')
            if len(parts) < 2 or parts[0] != 'jobs' or parts[1] not in control['jobs']:
                return error('No scripted job', 404, 'not_found')
            job = control['jobs'][parts[1]]
            if len(parts) == 2:
                n = control['polls'].get(job['id'], 0) + 1
                control['polls'][job['id']] = n
                if job['status'] == 'cancelling':
                    job.update(status='cancelled', reason='user_cancelled', phase='unknown', updated_at='2026-11-13T12:00:03Z')
                elif mode != 'running' and n >= 2 and job['status'] == 'running':
                    job.update(status='failed', reason='budget_limited', phase='finalizing',
                               updated_at='2026-11-13T12:00:02Z', result_available=True,
                               progress={'reserved_attempts': 70, 'finished_attempts': 70, 'max_attempts': 126})
                return JSONResponse(envelope(job))
            if parts[2] == 'cancel':
                assert body == {'schema_version': 1}
                if job['status'] == 'running':
                    job.update(status='cancelling', updated_at='2026-11-13T12:00:01Z')
                return JSONResponse(envelope(job))
            if parts[2] == 'result':
                assert job['result_available']
                return JSONResponse(dict(envelope(job), report=REPORT, attempts=ATTEMPTS, interrupted_attempts=0))
            if parts[2] == 'export':
                assert body == {'schema_version': 1, 'kind': 'evidence'} and job['result_available']
                value = dict(fixture='SCRIPTED UI TRANSPORT; historical evidence replay, no model execution',
                             report=REPORT, attempts=ATTEMPTS, job=job)
                return JSONResponse(value, headers={'Content-Disposition': 'attachment; filename="scripted-evidence.json"'})
            return error('Unsupported scripted route', 404, 'not_found')

        @app.post('/__fixture/config')
        async def config(request: Request):
            value = await request.json()
            assert value['mode'] in ('budget', 'lost_ack', 'running', 'unavailable', 'readonly', 'old', 'unauthorized')
            control['mode'] = value['mode']
            return {'fixture': 'SCRIPTED', 'mode': control['mode']}

        @app.get('/__fixture/state')
        async def state():
            return dict(fixture='SCRIPTED UI transport; no inference', starts=control['starts'],
                        calls=control['calls'], jobs=list(control['jobs'].values()), export_file_count=13)

        uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
