"""Controlled loopback browser fixture: real activity, synthetic download transport only.

No export correctness is claimed by the inert test attachment. No operator settings,
provider requests, image builds, or production server changes are used.
"""
from pathlib import Path
import sqlite3
import sys

from fastapi import Request
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import goal_backend  # noqa: E402
from godseye.activity import Journal  # noqa: E402
from godseye.activity_api import activity_router  # noqa: E402
from godseye.experiment_spec import ContractError  # noqa: E402

original_create_app = goal_backend.create_app
original_run = goal_backend.uvicorn.run


def create_app(*a, **kw):
    app = original_create_app(*a, **kw)
    service = kw['orchestration']
    app.include_router(activity_router(service))
    fixture = dict(export_ok=False, export_calls=0)

    @app.post('/__fixture/export-mode')
    async def mode(request: Request):
        fixture['export_ok'] = (await request.json())['ok']
        return fixture

    @app.post('/__fixture/activity-gap')
    async def gap(request: Request):
        row = service.load((await request.json())['experiment_id'], 'run')
        private = service.registration(row['spec']['baseline']['id'])['directory']
        with sqlite3.connect(Journal(private).path) as db:
            db.execute('DELETE FROM events WHERE sequence=2')
        return dict(ok=True)

    @app.post('/api/v1/experiments/export')
    async def export_transport(request: Request):
        fixture['export_calls'] += 1
        body = await request.json()
        result = service.results(dict(schema_version=1, experiment_id=body['experiment_id']))
        assert result['status'] == 'completed'
        assert body == dict(schema_version=1, experiment_id=result['experiment_id'],
                            artifact_id=result['evidence']['candidate_manifest_id'])
        if not fixture['export_ok']:
            return JSONResponse(ContractError('unavailable').response(), status_code=503)
        # Inert download fixture: explicitly not a model or verified exporter result.
        return JSONResponse(dict(test_transport_only=True), headers={
            'Content-Disposition': 'attachment; filename="fixture.json"'})
    return app


def run(app, **kwargs):
    kwargs['port'] = 8881
    original_run(app, **kwargs)


if __name__ == '__main__':
    goal_backend.create_app = create_app
    goal_backend.uvicorn.run = run
    goal_backend.main()
