"""Temporary, unconfigured local lab: no operator settings or provider calls.

Run GODSEYE_BROWSER_PORT=18980 PYTHONPATH=. python tests/browser/first_use_backend.py
then ego-browser nodejs < tests/browser/first_use_journey.cjs.
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import uvicorn

from godseye.core import Store, digest
from godseye.server import create_app


def main():
    with tempfile.TemporaryDirectory(prefix='first-use-browser-') as directory:
        store = Store(Path(directory))
        original_hash = digest(store.weights('paper'))
        app = create_app(store)

        @app.get('/__fixture/state')
        async def state():
            return {'original_preserved': digest(store.weights('paper')) == original_hash}

        with patch('urllib.request.urlopen', side_effect=AssertionError('External HTTP')), \
             patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('External HTTP')):
            uvicorn.run(app, host='127.0.0.1',
                        port=int(os.environ.get('GODSEYE_BROWSER_PORT', '18980')),
                        log_level='warning')


if __name__ == '__main__':
    main()
