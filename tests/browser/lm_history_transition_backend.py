"""No-inference route/history fixture using an isolated copy of retained LM history.

The source SQLite is opened read-only for its backup; only the corresponding
journals are copied for actual LMService progress reads. No runtime or weight
cache is configured. GET responses come from the real app/service unchanged.
"""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

import uvicorn
from fastapi.staticfiles import StaticFiles

from godseye.core import Store
from godseye.export import export_demo
from godseye.lm.service import LMService
from godseye.server import create_app


class HistoryOnlyAdapter:
    def readiness(self):
        return 'History inspection only. No inference runtime is configured.'

    def launch(self, *args):
        raise AssertionError('Inference is forbidden in the history fixture')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18998)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='qwen-history-transition-') as directory:
        root = Path(directory)
        lm = root / 'lm'
        lm.mkdir(mode=0o700)
        with sqlite3.connect(f'file:{args.source / "control.sqlite3"}?mode=ro', uri=True) as source:
            with sqlite3.connect(lm / 'control.sqlite3') as destination:
                source.backup(destination)
                jobs = list(destination.execute('SELECT id,status FROM jobs'))
        assert jobs and all(status in ('completed', 'failed', 'cancelled', 'interrupted') for _, status in jobs)
        for job_id, _ in jobs:
            journal = args.source / job_id / 'run/journal.jsonl'
            if journal.is_file():
                copied = lm / job_id / 'run/journal.jsonl'
                copied.parent.mkdir(parents=True)
                shutil.copyfile(journal, copied)
        service = LMService(lm, adapter=HistoryOnlyAdapter())
        app = create_app(Store(root / 'breakout'), lm_service=service)
        app.mount('/recorded', StaticFiles(directory=export_demo(root / 'recorded')))
        audit = []

        @app.middleware('http')
        async def observe(request, call_next):
            response = await call_next(request)
            if request.url.path.startswith('/api/'):
                audit.append(dict(path=request.url.path, method=request.method, status=response.status_code))
            return response

        @app.get('/__fixture/state')
        async def state():
            return dict(purpose='Copied retained history; inference disabled', jobs=service.jobs(), audit=audit)

        print(json.dumps(dict(fixture=str(root), port=args.port, copied_jobs=len(jobs))), flush=True)
        uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
