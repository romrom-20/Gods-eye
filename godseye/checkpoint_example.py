"""No-key scripted export example. Mechanics evidence, never intelligent repair.

Run: python -m godseye.checkpoint_example --output /tmp/new-checkpoint-example
Requires dev dependencies for FastAPI TestClient; no network or saved settings.
"""
from .evaluator import Evaluator


class NumericWorker:
    """Scripted sign inversion; select only a measured dev improvement, never held-out."""
    capacity = 1

    def __init__(self):
        self.calls = []

    def available(self):
        return True

    def recover(self, *args):
        pass

    def execute(self, row, registration, directory, settings, check, accounting):
        self.calls.append(row['id'])
        evaluator = Evaluator(registration['directory'])
        for role in ('unchanged', 'heuristic', 'agent'):
            for case in evaluator.dispatch(role, 'list', {})['cases']:
                check()
                args = dict(case_id=case['id'], candidate_id=case['root_id'])
                root = evaluator.dispatch(role, 'evaluate', args)
                if role == 'agent':
                    candidate = evaluator.dispatch(role, 'patch', dict(case_id=case['id'],
                        parent_id=case['root_id'], patch='W3[:, :] *= -1',
                        hypothesis='Scripted inversion fixture; development selection only'))
                    chosen = dict(case_id=case['id'], candidate_id=candidate['id'])
                    probe = evaluator.dispatch(role, 'evaluate', chosen)
                    if probe['result']['mean_score'] > root['result']['mean_score']:
                        args = chosen
                evaluator.dispatch(role, 'freeze', args)
        evaluator.report()



def main():
    import argparse
    import json
    from pathlib import Path
    import tempfile
    import time
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from .checkpoint_artifact import reload_artifact
    from .core import Store, save_weights
    from .experiment_spec import TERMINAL
    from .orchestration import Orchestrator
    from .server import create_app

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='New directory for the downloaded artifact and reloadable NPZ files')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output must be a new directory; originals are never overwritten')

    class NoSettings:
        def __getattr__(self, name):
            raise AssertionError('Example must never access credentials or provider settings')

    with tempfile.TemporaryDirectory(prefix='godseye-export-example-') as temporary:
        root = Path(temporary)
        private = root / 'evaluator'
        Evaluator.create(private, instances=1, episodes=2, max_steps=200,
                         probes=2, forward_budget=800)
        service = Orchestrator(root / 'service', worker=NumericWorker(), settings=NoSettings())
        try:
            service.register(private, baseline_id='example_roots', suite_id='example_suite', revision='v1')
            # Prohibit outbound connections even if an accidental provider path is introduced.
            with patch('socket.socket.connect', side_effect=AssertionError('No network')), \
                 patch('socket.socket.connect_ex', side_effect=AssertionError('No network')), \
                 TestClient(create_app(Store(root / 'lab'), orchestration=service)) as client:
                plan = client.post('/api/v1/experiments/plan', json=dict(
                    schema_version=1, text='Improve Breakout score',
                    provider=dict(name='openai', model='scripted-local-example', routing='price'),
                    limits=dict(max_requests=40, max_input_tokens=10000, max_total_output_tokens=2000,
                                max_seconds=30, max_rounds=40, max_calls=80, max_output_tokens=100))).json()
                started = client.post('/api/v1/experiments/start', json=dict(schema_version=1,
                    draft_id=plan['draft_id'], spec_hash=plan['spec_hash'], confirmed=True,
                    idempotency_key='scripted_example')).json()
                query = dict(schema_version=1, experiment_id=started['experiment_id'])
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    status = service.status(query)
                    if status['status'] in TERMINAL:
                        break
                    time.sleep(.05)
                if status['status'] != 'completed':
                    raise RuntimeError('Scripted example did not complete')
                result = client.post('/api/v1/experiments/results', json=query).json()
                downloaded = client.post('/api/v1/experiments/export', json=dict(query,
                    artifact_id=result['evidence']['candidate_manifest_id']))
                downloaded.raise_for_status()
                value = downloaded.json()
                pairs = reload_artifact(downloaded.content, expected_sha256=value['content_sha256'])
                args.output.mkdir(parents=True)
                (args.output / 'checkpoints.json').write_bytes(downloaded.content)
                for slot, (original, selected) in enumerate(pairs):
                    save_weights(args.output / ('original-%d.npz' % slot), original)
                    save_weights(args.output / ('selected-%d.npz' % slot), selected)
                (args.output / 'expected-sha256.txt').write_text(value['content_sha256'] + '\n')
                print(json.dumps(dict(content_sha256=value['content_sha256'],
                    checkpoints=len(pairs), changed=sum(r['outcome'] == 'changed' for r in value['checkpoints']),
                    verdict=result['verdict'], limitation='Scripted mechanics fixture, not intelligent repair')))
        finally:
            service.close()


if __name__ == '__main__':
    main()
