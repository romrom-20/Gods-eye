"""Local API and read-only demo server. Not a multi-tenant hosting boundary."""
from contextlib import asynccontextmanager
import hmac
import json
import os
import re
from pathlib import Path
import threading
from typing import Optional
from urllib.parse import urlsplit

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .backends import DATA_DIR
from .core import Store, apply_patch, difference, digest, tensor_summary
from .jobs import Conflict, JobQueue, QueueFull
from .experiment_spec import ContractError, HTTP_STATUS

STATIC = Path(__file__).parent / 'static'
MAX_BODY = 65536
MAX_FORWARDS = 250000


class PatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    base_id: str = Field(min_length=1, max_length=16)
    patch: str = Field(min_length=1, max_length=50000)
    hypothesis: str = Field(min_length=1, max_length=4000)
    expected_parent_sha256: Optional[str] = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class EvaluationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    base_id: str = Field(min_length=1, max_length=16)
    candidate_id: str = Field(min_length=1, max_length=16)
    episodes: StrictInt = Field(default=8, ge=1, le=64)
    seed: StrictInt = Field(default=1000, ge=0, le=2**32 - 65)
    max_steps: StrictInt = Field(default=3000, ge=1, le=10000)


class Boundary:
    """Validate Host/Origin and bound streamed bodies before JSON parsing."""
    def __init__(self, app, hosts, token):
        self.app, self.hosts, self.token = app, set(hosts), token

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope['headers'])
        host = headers.get(b'host', b'').decode('latin1')
        hostname = urlsplit('http://' + host).hostname if re.fullmatch(
            r'[a-zA-Z0-9.-]+(?::[0-9]{1,5})?', host) else None
        error, status = None, 403
        if hostname not in self.hosts:
            error = 'Host rejected'
        origin = headers.get(b'origin', b'').decode('latin1')
        if origin and origin != scope.get('scheme', 'http') + '://' + host:
            error = 'Origin rejected'
        is_api = scope['path'].startswith('/api/')
        if is_api and self.token and not hmac.compare_digest(
                headers.get(b'authorization', b''), ('Bearer ' + self.token).encode()):
            error, status = 'API token required', 401
        if is_api and headers.get(b'sec-fetch-site') == b'cross-site':
            error = 'Cross-site request rejected'
        if scope['method'] in ('POST', 'PUT', 'PATCH'):
            if headers.get(b'content-type', b'').split(b';')[0].strip() != b'application/json':
                error, status = 'Use application/json', 415
        body = b''
        if not error:
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                body += message.get('body', b'')
                if len(body) > MAX_BODY:
                    error, status = 'Request body exceeds 64 KiB', 413
                    break
                if not message.get('more_body', False):
                    break
        async def secured_send(message):
            if message['type'] == 'http.response.start':
                message['headers'] = list(message.get('headers', [])) + [
                    (b'x-content-type-options', b'nosniff'),
                    (b'x-frame-options', b'DENY'),
                    (b'referrer-policy', b'no-referrer'),
                    (b'cache-control', b'no-store' if is_api else b'no-cache'),
                    (b'content-security-policy', b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
                ]
            await send(message)
        if error:
            if scope['path'].startswith('/api/v1/experiments/'):
                code = ('not_authorized' if status in (401, 403) else
                        'invalid_json' if status == 413 else 'invalid_schema')
                failure = ContractError(code)
                return await JSONResponse(failure.response(), status_code=HTTP_STATUS[code])(
                    scope, receive, secured_send)
            return await JSONResponse({'error': error}, status_code=status)(scope, receive, secured_send)
        consumed = False
        async def replay():
            nonlocal consumed
            if consumed:
                return await receive()
            consumed = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        await self.app(scope, replay, secured_send)


def create_app(store=None, readonly=False, allowed_hosts=None, token=None, orchestration=None):
    store = store or Store(DATA_DIR / 'demo' if readonly else None)
    jobs = None if readonly else JobQueue(store)
    mutation_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        yield
        if orchestration:
            orchestration.close()
        if jobs:
            jobs.close()

    app = FastAPI(title="God's Eye weight-space API", version='0.3.0',
                  description='Inspect → preview → branch → evaluate. Local CPU execution.',
                  docs_url=None, redoc_url=None, openapi_url='/api/v1/openapi.json', lifespan=lifespan)
    app.state.jobs = jobs
    app.state.orchestration = orchestration
    app.add_middleware(Boundary, hosts=allowed_hosts or ['127.0.0.1', 'localhost', 'testserver'], token=token)

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse({'error': error.detail}, status_code=error.status_code)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        issues = [{'field': '.'.join(map(str, e['loc'])), 'message': e['msg']} for e in error.errors()]
        return JSONResponse({'error': 'Invalid request', 'issues': issues}, status_code=422)

    async def bad_input(request, error):
        return JSONResponse({'error': str(error)}, status_code=400)
    for cls in (ValueError, TypeError, IndexError, SyntaxError, OverflowError):
        app.add_exception_handler(cls, bad_input)

    async def missing(request, error):
        return JSONResponse({'error': 'Artifact not found'}, status_code=404)
    for cls in (KeyError, FileNotFoundError):
        app.add_exception_handler(cls, missing)

    def writable():
        if readonly:
            raise HTTPException(403, 'Recorded demo is read-only. Run the local lab to create experiments.')
        # Admission quota, not a transactional filesystem quota. A bounded run may cross it.
        if sum(p.stat().st_size for p in store.path.iterdir() if p.is_file()) >= 256 * 1024**2:
            raise HTTPException(507, 'Workspace reached its 256 MiB admission limit. Archive artifacts locally.')

    @app.get('/api/state', include_in_schema=False)
    @app.get('/api/v1/state')
    def state():
        return {'checkpoints': store.checkpoints(), 'backend': store.backend.id,
                'parameters': sum(v.size for v in store.paper.values()),
                'architecture': '600 → 32 → 32 → 6 · tanh',
                'mode': 'recorded-demo' if readonly else 'local',
                'limits': {'max_forwards': MAX_FORWARDS, 'queue_capacity': 4},
                'capabilities': ['tensor_read', 'patch_preview'] + ([] if readonly else ['patch', 'evaluate', 'cancel'])}

    @app.get('/api/tensor', include_in_schema=False)
    @app.get('/api/v1/tensor')
    def tensor(id: str = 'paper', name: str = 'W1'):
        weights = store.weights(id)
        if name not in weights:
            raise HTTPException(404, 'Unknown tensor')
        return {'name': name, 'values': weights[name].tolist(),
                'summary': tensor_summary(weights), 'sha256': digest(weights)}

    @app.get('/api/runs', include_in_schema=False)
    @app.get('/api/v1/runs')
    def runs():
        return store.runs()

    @app.get('/api/run/{run_id}', include_in_schema=False)
    @app.get('/api/v1/runs/{run_id}')
    def run(run_id: str):
        return store.read_run(run_id)

    @app.get('/api/preset/ball-chaser', include_in_schema=False)
    @app.get('/api/v1/presets/ball-chaser')
    def preset():
        return {'patch': (DATA_DIR / 'presets/ball-chaser.edits').read_text()}

    def preview(body):
        if not body.hypothesis.strip():
            raise ValueError('Write a hypothesis')
        base = store.weights(body.base_id)
        parent_hash = digest(base)
        if body.expected_parent_sha256 and body.expected_parent_sha256 != parent_hash:
            raise HTTPException(409, 'Parent hash mismatch. Inspect the checkpoint again.')
        edited = apply_patch(base, body.patch)
        diff = difference(base, edited)
        return {'parent_sha256': parent_hash, 'sha256': digest(edited), 'diff': diff,
                'changed': sum(d['changed'] for d in diff), 'parameters': sum(v.size for v in base.values())}

    @app.post('/api/v1/patches/preview')
    def preview_patch(body: PatchRequest):
        return preview(body)

    @app.post('/api/patch', include_in_schema=False, status_code=201)
    @app.post('/api/v1/checkpoints', status_code=201)
    def patch(body: PatchRequest):
        with mutation_lock:
            writable()
            preview(body)
            return store.patch(body.base_id, body.patch, body.hypothesis)

    @app.post('/api/v1/jobs', status_code=202)
    def submit(body: EvaluationRequest, idempotency_key: Optional[str] = Header(default=None)):
        with mutation_lock:
            writable()
            if 2 * body.episodes * body.max_steps > MAX_FORWARDS:
                raise HTTPException(422, 'Evaluation exceeds 250,000 maximum forward calls. Reduce episodes or steps.')
            if idempotency_key and (len(idempotency_key) > 128 or not idempotency_key.isascii()):
                raise HTTPException(400, 'Use an ASCII idempotency key of at most 128 characters')
            store.weights(body.base_id)
            store.weights(body.candidate_id)
            try:
                return jobs.submit(body.model_dump(), idempotency_key)
            except QueueFull as error:
                raise HTTPException(429, str(error))
            except Conflict as error:
                raise HTTPException(409, str(error))

    @app.get('/api/v1/jobs')
    def list_jobs():
        return jobs.list() if jobs else []

    @app.get('/api/v1/jobs/{job_id}')
    def get_job(job_id: str):
        if not jobs:
            raise HTTPException(404, 'No live jobs in the recorded demo')
        return jobs.get(job_id)

    @app.post('/api/v1/jobs/{job_id}/cancel')
    def cancel_job(job_id: str):
        if not jobs:
            raise HTTPException(403, 'Recorded demo is read-only')
        return jobs.cancel(job_id)

    # Raw ingress preserves duplicate-key/nesting checks from the reviewed contract.
    # The injected service belongs to this local server's single authorization scope.
    async def experiment_operation(operation, request):
        try:
            if readonly:
                raise ContractError('not_authorized')
            if orchestration is None:
                raise ContractError('unavailable')
            # Keep blocking registry/SQLite/worker admission off the ASGI event loop.
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(orchestration.handle, operation, await request.body())
        except ContractError as error:
            headers = {'Retry-After': '5'} if error.code in (
                'rate_limited', 'queue_full', 'worker_unavailable') else {}
            return JSONResponse(error.response(), status_code=HTTP_STATUS[error.code], headers=headers)
        except Exception:
            error = ContractError('internal_error')
            return JSONResponse(error.response(), status_code=500)

    @app.post('/api/v1/experiments/export')
    async def experiment_export(request: Request):
        try:
            if readonly:
                raise ContractError('not_authorized')
            if orchestration is None:
                raise ContractError('unavailable')
            from starlette.concurrency import run_in_threadpool
            from .checkpoint_export import export_checkpoint
            output = await run_in_threadpool(export_checkpoint, orchestration, await request.body())
            return Response(output, media_type='application/json', headers={
                'Content-Disposition': 'attachment; filename="godseye-checkpoints-v1.json"'})
        except ContractError as error:
            headers = {'Retry-After': '5'} if error.code == 'rate_limited' else {}
            return JSONResponse(error.response(), status_code=HTTP_STATUS[error.code], headers=headers)
        except Exception:
            error = ContractError('not_found')
            return JSONResponse(error.response(), status_code=404)

    @app.post('/api/v1/experiments/plan')
    async def experiment_plan(request: Request):
        return await experiment_operation('plan', request)

    @app.post('/api/v1/experiments/start')
    async def experiment_start(request: Request):
        return await experiment_operation('start', request)

    @app.post('/api/v1/experiments/status')
    async def experiment_status(request: Request):
        return await experiment_operation('status', request)

    @app.post('/api/v1/experiments/cancel')
    async def experiment_cancel(request: Request):
        return await experiment_operation('cancel', request)

    @app.post('/api/v1/experiments/results')
    async def experiment_results(request: Request):
        return await experiment_operation('results', request)

    @app.get('/healthz')
    def health():
        return {'status': 'ok', 'mode': 'recorded-demo' if readonly else 'local'}

    @app.get('/', include_in_schema=False)
    def home():
        return FileResponse(STATIC / 'landing.html')

    @app.get('/lab', include_in_schema=False)
    @app.get('/lab.html', include_in_schema=False)
    def lab():
        return FileResponse(STATIC / 'index.html')

    @app.get('/{asset}', include_in_schema=False)
    def asset(asset: str):
        if asset not in {'app.js', 'style.css', 'landing.css', 'landing.js', 'api.html'}:
            raise HTTPException(404, 'Not found')
        return FileResponse(STATIC / asset)

    return app


def serve(port=8787, demo=False, host='127.0.0.1'):
    import uvicorn
    if host not in ('127.0.0.1', 'localhost') and not demo:
        raise ValueError('Writable server must bind to loopback. Use --demo for a read-only server.')
    hosts = [h.strip() for h in os.environ.get(
        'GODSEYE_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',')]
    orchestration = None
    if not demo and os.environ.get('GODSEYE_ORCHESTRATION_DIR'):
        from .orchestration import DockerWorker, Orchestrator
        orchestration = Orchestrator(os.environ['GODSEYE_ORCHESTRATION_DIR'],
                                     worker=DockerWorker(Path(__file__).resolve().parents[1]))
    app = create_app(readonly=demo, allowed_hosts=hosts, token=os.environ.get('GODSEYE_API_TOKEN'),
                     orchestration=orchestration)
    print(f"God's Eye at http://{host}:{port} · {'recorded demo' if demo else 'local CPU lab'}", flush=True)
    uvicorn.run(app, host=host, port=port, workers=1, proxy_headers=False, limit_concurrency=32,
                timeout_keep_alive=5, log_level='info')
