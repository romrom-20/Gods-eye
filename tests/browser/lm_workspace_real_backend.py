"""Actual local LMService browser integration server: no intercepted LM responses.

Starting this server never runs inference. An explicitly authorized human/browser
Start is required. Use a NEW private directory and dedicated unused loopback port;
this runner refuses an existing directory so it cannot silently rerun an experiment.
Only read-only instrumentation and the ordinary real static export are added.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
from datetime import datetime, timezone

import uvicorn
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from godseye.core import Store
from godseye.export import export_demo
from godseye.server import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--port', type=int, default=18997)
    args = parser.parse_args()
    root = args.directory
    if not root.is_absolute() or root.exists():
        raise SystemExit('Use a NEW absolute private directory; existing evidence is never reused for new execution.')
    root.mkdir(mode=0o700)
    lm = root / 'lm'
    lm.mkdir(mode=0o700)
    os.environ['GODSEYE_LM_DIR'] = str(lm)
    # The cache/interpreter come only from explicit operator configuration.
    assert os.environ['GODSEYE_LM_CACHE'] == '/tmp/godseye-lm-local-real-20261113/weights'
    assert os.environ['GODSEYE_LM_PYTHON'] == '/tmp/godseye-lm-local-venv/bin/python'
    app = create_app(Store(root / 'breakout'))
    service = app.state.lm_service
    assert service.directory == lm and service.adapter.__class__.__name__ == 'LocalWorker'
    exported = export_demo(root / 'static')
    assert len(list(exported.iterdir())) == 13
    app.mount('/recorded', StaticFiles(directory=exported))
    audit = []
    manifest = dict(purpose='ONE authorized pretrained browser transport reproduction; not independent quality evidence',
                    created_at=datetime.now(timezone.utc).isoformat(), host=platform.platform(),
                    server_python=platform.python_version(), port=args.port,
                    lm_cache=os.environ['GODSEYE_LM_CACHE'], lm_python=os.environ['GODSEYE_LM_PYTHON'], lm_directory=str(lm),
                    server_packages={k: importlib.metadata.version(k) for k in ('fastapi','uvicorn','numpy')},
                    intercepted_lm_responses=False, export_file_count=13)
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')

    @app.middleware('http')
    async def read_only_audit(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith('/api/'):
            audit.append(dict(timestamp=datetime.now(timezone.utc).isoformat(), method=request.method,
                              path=request.url.path, status=response.status_code))
            (root / 'http-audit.json').write_text(json.dumps(audit, indent=2) + '\n')
        return response

    @app.get('/__integration/state')
    async def state():
        # Read-only control-store/journal instrumentation, never adapter calls.
        with sqlite3.connect(f'file:{lm / "control.sqlite3"}?mode=ro', uri=True) as db:
            bindings = [dict(zip(('id','idempotency_key','plan_id','spec_sha256'), row))
                        for row in db.execute('SELECT id,key,plan,hash FROM jobs ORDER BY created')]
        journals = []
        for file in sorted(lm.glob('*/run/journal.jsonl')):
            events = [json.loads(line) for line in file.read_text().splitlines()]
            journals.append(dict(path=str(file), events=len(events),
                                 reservations=sum(e['kind'] == 'reservation' for e in events),
                                 results=sum(e['kind'] == 'result' for e in events)))
        return JSONResponse(dict(jobs=service.jobs(), bindings=bindings, journals=journals,
                                 audit=audit, manifest=manifest))

    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
