"""Loopback-only browser fixture; all state and credentials are temporary.

Run with the project's server/dev dependencies. Never uses operator settings.
Control endpoints exist only in this test app, never in the production server.
"""
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

import uvicorn
from fastapi import Request
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from goal_acceptance_support import PROVIDER_SECRET, ScriptedWorker  # noqa: E402
from godseye.core import Store, digest  # noqa: E402
from godseye.evaluator import Evaluator  # noqa: E402
from godseye.experiment_spec import ContractError  # noqa: E402
from godseye.orchestration import AdmissionLimits, Orchestrator  # noqa: E402
from godseye.provider_setup import ProviderSettings  # noqa: E402
from godseye.server import create_app  # noqa: E402


def main():
    with tempfile.TemporaryDirectory(prefix='goal-browser-') as directory:
        root = Path(directory)
        settings = ProviderSettings(root / 'keys')
        settings.save(PROVIDER_SECRET, 'scripted-acceptance')
        class BrowserBarrier(threading.Event):
            def wait(self, timeout=None):
                return super().wait(60)

        worker = ScriptedWorker()
        worker.release = BrowserBarrier()
        clock_offset = [0]
        service = Orchestrator(root / 'service', worker=worker, settings=settings,
                               clock=lambda: time.time() + clock_offset[0],
                               limits=AdmissionLimits(plans_per_minute=1000,
                                                      starts_per_minute=1000,
                                                      reads_per_minute=10000))
        store = Store(root / 'lab')
        original_hash = digest(store.weights('paper'))
        app = create_app(store, orchestration=service)
        fixture = dict(requests=[], drop=False, errors=[], operation='start', registrations=0)

        def register():
            fixture['registrations'] += 1
            private = root / ('private-' + str(fixture['registrations']))
            Evaluator.create(private, instances=1, episodes=2, max_steps=1,
                             probes=2, forward_budget=4)
            service.register(private, baseline_id='browser-' + str(fixture['registrations']),
                             suite_id='browser-suite', revision='v1')

        register()

        @app.post('/__fixture/config')
        async def configure(request: Request):
            body = await request.json()
            worker.release.set()
            # Tests wait for terminal before configuring a fresh baseline.
            worker.release.clear()
            worker.block = body.get('block', False)
            worker.mode = body.get('mode', 'complete')
            fixture.update(drop=body.get('drop', False), errors=body.get('errors', []),
                           operation=body.get('operation', 'start'))
            if body.get('fresh', True):
                register()
            return {'ok': True}

        @app.post('/__fixture/expire')
        async def expire():
            # Advance only the injected service clock; use the real expiry check.
            clock_offset[0] += 901
            return {'ok': True}

        @app.post('/__fixture/release')
        async def release():
            worker.release.set()
            return {'ok': True}

        @app.get('/__fixture/state')
        async def state():
            return dict(requests=fixture['requests'], workers=len(worker.calls),
                        key_reads=worker.key_reads,
                        original_preserved=digest(store.weights('paper')) == original_hash)

        @app.middleware('http')
        async def script(request, call_next):
            operation = request.url.path.rsplit('/', 1)[-1]
            if request.url.path.startswith('/api/v1/experiments/'):
                body = await request.json()
                fixture['requests'].append(dict(operation=operation, body=body))
                if fixture['errors'] and operation == fixture['operation']:
                    code = fixture['errors'].pop(0)
                    status = {'rate_limited':429, 'queue_full':503,
                              'worker_unavailable':503, 'unavailable':503}[code]
                    return JSONResponse(ContractError(code).response(), status_code=status,
                                        headers={'Retry-After':'5'} if code != 'unavailable' else {})
                response = await call_next(request)
                if operation == 'start' and fixture['drop']:
                    fixture['drop'] = False
                    # Admission succeeded, but the client cannot parse its acknowledgment.
                    return JSONResponse({'truncated': True}, status_code=200)
                return response
            return await call_next(request)

        # Block every outbound provider transport; loopback inbound server is unaffected.
        with patch('urllib.request.urlopen', side_effect=AssertionError('External HTTP')), \
             patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('External HTTP')):
            try:
                uvicorn.run(app, host='127.0.0.1', port=8879, log_level='warning')
            finally:
                worker.release.set()
                service.close()


if __name__ == '__main__':
    main()
