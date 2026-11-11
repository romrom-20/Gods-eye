"""Attach only to create_app: its existing Boundary supplies Host/Origin/auth/body caps."""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .activity import activity_request
from .experiment_spec import ContractError, HTTP_STATUS, loads_message


def activity_router(service=None, *, readonly=False):
    router = APIRouter()

    @router.post('/api/v1/experiments/activity')
    async def activity(request: Request):
        try:
            if readonly or getattr(request.app.state, 'jobs', None) is None:
                raise ContractError('not_authorized')
            if service is None:
                raise ContractError('unavailable')
            # Parse bounded strict JSON without adding activity to the v1 schemas.
            value = activity_request(loads_message(await request.body()))
            result = await run_in_threadpool(service.activity, value)
            return JSONResponse(result, headers={'Cache-Control': 'no-store'})
        except ContractError as error:
            headers = {'Cache-Control': 'no-store'}
            if error.code == 'rate_limited':
                headers['Retry-After'] = '5'
            return JSONResponse(error.response(), status_code=HTTP_STATUS[error.code], headers=headers)
        except Exception:
            return JSONResponse(ContractError('internal_error').response(), status_code=500,
                                headers={'Cache-Control': 'no-store'})
    return router
