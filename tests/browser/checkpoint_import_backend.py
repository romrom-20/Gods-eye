"""Temporary loopback fixture for the real checkpoint-import browser journey.

Requires the checkpoint import backend merge; never substitutes a successful route.
Run with PYTHONPATH=. python tests/browser/checkpoint_import_backend.py, then
run checkpoint_import_journey.cjs with ego-browser nodejs. No provider is configured.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import uvicorn
from fastapi import Request
from fastapi.responses import Response

from godseye.core import Store, digest
from godseye.server import create_app


def main():
    with tempfile.TemporaryDirectory(prefix='checkpoint-import-browser-') as directory:
        path = Path(directory)
        store = Store(path / 'store')
        original = digest(store.weights('paper'))
        checkpoint = path / 'breakout.npz'
        np.savez(checkpoint, **store.weights('paper'))
        app = create_app(store)
        assert sum(getattr(route, 'path', None) == '/api/v1/checkpoints/import'
                   for route in app.routes) == 1, 'Real import backend must be merged first'
        control = {'drop_ack': False, 'writes': 0}

        @app.middleware('http')
        async def lost_ack(request, call_next):
            importing = request.method == 'POST' and request.url.path == '/api/v1/checkpoints/import'
            if importing:
                control['writes'] += 1
            response = await call_next(request)
            if importing and control['drop_ack'] and response.status_code == 201:
                control['drop_ack'] = False
                # The real handler saved successfully; lose only the acknowledgment.
                return Response('{', status_code=201, media_type='application/json')
            return response

        @app.post('/__fixture/drop-ack')
        async def drop_ack(request: Request):
            assert await request.json() == {'drop': True}
            control['drop_ack'] = True
            return {'ok': True}

        @app.get('/__fixture/state')
        async def state():
            return {'file': str(checkpoint), 'writes': control['writes'],
                    'original_preserved': digest(store.weights('paper')) == original,
                    'checkpoints': store.checkpoints()}

        with patch('urllib.request.urlopen', side_effect=AssertionError('External HTTP')), \
             patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('External HTTP')):
            uvicorn.run(app, host='127.0.0.1',
                        port=int(os.environ.get('GODSEYE_BROWSER_PORT', '18992')),
                        log_level='warning')


if __name__ == '__main__':
    main()
