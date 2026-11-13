"""Strict bounded HTTP transport for the trusted local LM control service."""
import re
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from .service import LMService, MAX_RESPONSE, STATUS, ServiceError
from .task_contract import canonical, strict_json


def lm_router(service=None, *, readonly=False):
    service = service or LMService()
    router = APIRouter(prefix='/api/v1/lm')

    def validate(body, fields):
        if (type(body) is not dict or set(body) != {'schema_version', *fields}
                or type(body['schema_version']) is not int or body['schema_version'] != 1):
            raise ValueError()
        for name in fields:
            value = body[name]
            if type(value) is not str:
                raise ValueError()
            if name in ('idempotency_key', 'plan_id'):
                if str(uuid.UUID(value)) != value:
                    raise ValueError()
            elif name == 'spec_sha256':
                if not re.fullmatch('[a-f0-9]{64}', value):
                    raise ValueError()
            elif name == 'request':
                if not 1 <= len(value) <= 2000:
                    raise ValueError()
            elif name == 'kind' and value not in ('evidence', 'selected_delta'):
                raise ValueError()
        return body

    async def respond(request, action, *, fields=None, mutate=False, attachment=None):
        try:
            if mutate and readonly:
                raise ServiceError('readonly', 'Recorded demo is read-only. Run a configured local lab.')
            body = None
            if fields is not None:
                try:
                    body = validate(strict_json((await request.body()).decode(), max_bytes=16384), fields)
                except (ValueError, UnicodeError, TypeError, AttributeError):
                    raise ServiceError('invalid_request', 'Use the exact version 1 JSON request fields and types.') from None
            result = await run_in_threadpool(action, body)
            status = 200
            if isinstance(result, tuple):
                result, first = result
                status = 202 if first else 200
            raw = canonical(result).encode()
            if len(raw) > MAX_RESPONSE:
                raise ServiceError('internal', 'Local LM response exceeds its safe bound; inspect evidence locally.')
            headers = {'Content-Disposition': f'attachment; filename="lm-{attachment}.json"'} if attachment else None
            return Response(raw, status_code=status, media_type='application/json', headers=headers)
        except ServiceError as exc:
            return JSONResponse(exc.response(), status_code=STATUS[exc.code])
        except Exception:
            failure = ServiceError('internal', 'Local LM operation failed safely. Inspect operator setup and retained job status before retrying.')
            return JSONResponse(failure.response(), status_code=500)

    @router.get('/capabilities')
    async def capabilities(request: Request):
        return await respond(request, lambda _: service.capabilities(readonly))

    @router.post('/plan')
    async def plan(request: Request):
        return await respond(request, lambda b: service.plan(b['request']), fields={'request'}, mutate=True)

    @router.post('/jobs')
    async def start(request: Request):
        return await respond(request, lambda b: (lambda pair: (dict(schema_version=1, job=pair[0]), pair[1]))(
            service.start(b['plan_id'], b['spec_sha256'], b['idempotency_key'])),
            fields={'plan_id', 'spec_sha256', 'idempotency_key'}, mutate=True)

    @router.post('/resolve')
    async def resolve(request: Request):
        return await respond(request, lambda b: dict(schema_version=1,
            job=service.resolve(b['idempotency_key'], b['spec_sha256'])),
            fields={'spec_sha256', 'idempotency_key'})

    @router.get('/jobs')
    async def jobs(request: Request):
        return await respond(request, lambda _: dict(schema_version=1, jobs=service.jobs()))

    @router.get('/jobs/{job_id}')
    async def job(job_id: str, request: Request):
        return await respond(request, lambda _: dict(schema_version=1, job=service.job(job_id)))

    @router.post('/jobs/{job_id}/cancel')
    async def cancel(job_id: str, request: Request):
        return await respond(request, lambda _: dict(schema_version=1, job=service.cancel(job_id)),
                             fields=set(), mutate=True)

    @router.get('/jobs/{job_id}/result')
    async def result(job_id: str, request: Request):
        return await respond(request, lambda _: service.result(job_id))

    @router.post('/jobs/{job_id}/export')
    async def export(job_id: str, request: Request):
        return await respond(request, lambda b: service.export(job_id, b['kind']),
                             fields={'kind'}, mutate=True, attachment='evidence')

    return router
