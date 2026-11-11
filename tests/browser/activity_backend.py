"""Loopback fixture for actual activity/export, with controlled artifact corruption.

No duplicate production routes, saved operator settings, provider calls or images.
"""
import json
from pathlib import Path
import sqlite3
import sys

from fastapi import Request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import goal_backend  # noqa: E402
from godseye.activity import Journal  # noqa: E402
from godseye.core import digest, load_weights  # noqa: E402

original_create_app = goal_backend.create_app
original_run = goal_backend.uvicorn.run


def create_app(*a, **kw):
    app = original_create_app(*a, **kw)
    service = kw['orchestration']
    assert '/api/v1/experiments/activity' in app.openapi()['paths']
    assert sum(getattr(route, 'path', None) == '/api/v1/experiments/export'
               for route in app.routes) == 1, 'Production export must be attached exactly once'
    backups = {}

    @app.post('/__fixture/export-mode')
    async def mode(request: Request):
        body = await request.json()
        row = service.load(body['experiment_id'], 'run')
        assert row['status'] == 'completed'
        manifest_id = row['evidence']['candidate_manifest_id']
        path = Path(row['artifacts'][manifest_id])
        # Corrupt only the temporary completed fixture manifest. The real export
        # handler must reject it; no API route or successful payload is replaced.
        if body['ok']:
            path.write_bytes(backups.pop(row['id']))
        else:
            assert row['id'] not in backups
            backups[row['id']] = path.read_bytes()
            path.write_bytes(b'{}')
        return dict(ok=True)

    @app.post('/__fixture/checkpoint-hashes')
    async def hashes(request: Request):
        row = service.load((await request.json())['experiment_id'], 'run')
        assert row['status'] == 'completed'
        private = Path(service.registration(row['spec']['baseline']['id'])['directory'])
        state = json.loads((private / 'agent/private-state.json').read_text())
        return dict(python_executable=sys.executable, source_root=str(Path(__file__).resolve().parents[2]),
                    hashes=[[digest(load_weights(private / 'agent' / (case['root_id'] + '.npz'))),
                             digest(load_weights(private / 'agent' / (case['final']['candidate_id'] + '.npz')))]
                            for case in state['cases']])

    @app.post('/__fixture/activity-gap')
    async def gap(request: Request):
        row = service.load((await request.json())['experiment_id'], 'run')
        private = service.registration(row['spec']['baseline']['id'])['directory']
        with sqlite3.connect(Journal(private).path) as db:
            db.execute('DELETE FROM events WHERE sequence=2')
        return dict(ok=True)
    return app


def run(app, **kwargs):
    kwargs['port'] = 8881
    original_run(app, **kwargs)


if __name__ == '__main__':
    goal_backend.create_app = create_app
    goal_backend.uvicorn.run = run
    goal_backend.main()
