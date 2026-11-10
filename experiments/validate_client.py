"""Independent local HTTP acceptance experiment; no external services.

Run: .venv/bin/python -m experiments.validate_client --output /tmp/godseye-evidence
The output directory must not exist. The temporary workspace and server are
always cleaned up; an artifact copy and compact evidence remain in output.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import socket
import statistics
import subprocess
import sys
import tempfile
import time

from godseye.client import APIError, Client


def files(directory):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.iterdir() if p.is_file()}


def rejected(operation, status):
    try:
        operation()
    except APIError as error:
        assert error.status == status, (error.status, error.payload)
        return {'status': error.status, 'response': error.payload}
    raise AssertionError('Invalid request was accepted')


def independent_summary(run):
    base, candidate = run['base']['episodes'], run['candidate']['episodes']
    assert [r['seed'] for r in base] == [r['seed'] for r in candidate]
    delta = [b['score'] - a['score'] for a, b in zip(base, candidate)]
    mean = statistics.mean(delta)
    se = statistics.stdev(delta) / math.sqrt(len(delta))
    assert math.isclose(mean, run['paired_mean_delta'], abs_tol=1e-12)
    assert math.isclose(se, run['paired_se'], abs_tol=1e-12)
    for side in ('base', 'candidate'):
        rows = run[side]['episodes']
        assert run[side]['forward_calls'] == sum(r['steps'] for r in rows)
        assert all(0 < r['steps'] <= run['max_steps'] for r in rows)
        assert all(r['steps'] == run['max_steps'] for r in rows if r['truncated'])
        scores = [r['score'] for r in rows]
        assert math.isclose(statistics.mean(scores), run[side]['mean'], abs_tol=1e-12)
        assert math.isclose(statistics.stdev(scores) / math.sqrt(len(rows)),
                            run[side]['se'], abs_tol=1e-12)
    return {'paired_differences': delta, 'paired_mean_delta': mean, 'paired_se': se,
            'caps': {side: sum(r['truncated'] for r in run[side]['episodes'])
                     for side in ('base', 'candidate')}}


def compact_run(run, *, require_identical=False):
    """Check complete recorded replay before removing it from compact evidence."""
    verified = False
    if require_identical:
        assert run['base']['trace'] and run['candidate']['trace'], 'Missing replay evidence'
        assert run['base']['trace'] == run['candidate']['trace'], 'Recorded replays differ'
        assert run['base'] == run['candidate'], 'Restored evaluation differs from original'
        verified = True
    compact = dict(run)
    for side in ('base', 'candidate'):
        compact[side] = {key: value for key, value in run[side].items() if key != 'trace'}
    return compact, verified


def exercise(client, workspace):
    evidence = {'started_utc': datetime.now(timezone.utc).isoformat(),
                'url': client.url, 'python': sys.version,
                'scope': 'Known-circuit mechanics test; not discovery of a novel repair.'}
    state = client.state()
    assert state['mode'] == 'local' and state['parameters'] == 20486
    assert {r['id'] for r in state['checkpoints']} == {'paper', 'zero'}
    evidence['state'] = state
    names = ('W1', 'b1', 'W2', 'b2', 'W3', 'b3')
    tensors = {name: client.tensor('paper', name) for name in names}
    original_hash = tensors['W3']['sha256']
    # Independently reconstruct the documented float32 content hash from HTTP
    # values; no Store/core/compare helper is used by this experiment.
    import struct
    digest = hashlib.sha256()
    for name, tensor in tensors.items():
        assert tensor['sha256'] == original_hash
        digest.update(name.encode())
        values = tensor['values']
        flat = [v for row in values for v in row] if isinstance(values[0], list) else values
        digest.update(struct.pack('<' + 'f' * len(flat), *flat))
    assert digest.hexdigest() == original_hash
    original = [tensors['W3']['values'][row][1] for row in (0, 2, 4, 6)]
    assert original == [30.0] * 4
    evidence['inspection'] = {'sha256': original_hash, 'W3_left_rows_0_2_4_6': original,
                              'summary': tensors['W3']['summary']}
    patch = 'W3[0:8:2, 1] = 0'
    hypothesis = 'Removing the four known left-action connections reduces score.'
    before = files(workspace)
    preview = client.preview('paper', patch, hypothesis)
    assert preview['changed'] == 4 and files(workspace) == before
    evidence['preview'] = preview
    evidence['stale_parent'] = rejected(lambda: client.patch(
        'paper', patch, hypothesis, expected_parent_sha256='0' * 64), 409)
    assert files(workspace) == before
    ablated = client.patch('paper', patch, hypothesis,
                           expected_parent_sha256=preview['parent_sha256'])
    assert ablated['sha256'] == preview['sha256']
    assert ablated['parent'] == 'paper' and ablated['parent_sha256'] == original_hash
    assert client.tensor('paper', 'W3')['sha256'] == original_hash
    assert [client.tensor(ablated['id'], 'W3')['values'][r][1] for r in (0, 2, 4, 6)] == [0] * 4

    def evaluate(name, base, candidate, seed, *, require_identical=False):
        job = client.evaluate(base, candidate, episodes=8, seed=seed,
                              max_steps=3000, idempotency_key=name)
        assert client.evaluate(base, candidate, episodes=8, seed=seed,
                               max_steps=3000, idempotency_key=name)['id'] == job['id']
        run = client.wait(job['id'], timeout=120, interval=.02)
        final = client.job(job['id'])
        assert final['status'] == 'succeeded' and final['completed'] == 16
        summary = independent_summary(run)
        run, replay_verified = compact_run(run, require_identical=require_identical)
        print(name, json.dumps(summary), flush=True)
        return {'name': name, 'job': final, 'run': run, 'verified_summary': summary,
                'recorded_replay_equality_verified': replay_verified}

    runs = [evaluate('ablation', 'paper', ablated['id'], 1000)]
    restoration_patch = 'W3[0:8:2, 1] = ' + repr(original)
    restore_preview = client.preview(ablated['id'], restoration_patch,
                                     'Restore the inspected original four values.')
    assert restore_preview['changed'] == 4 and restore_preview['sha256'] == original_hash
    restored = client.patch(ablated['id'], restoration_patch,
                            'Restore the inspected original four values.',
                            expected_parent_sha256=ablated['sha256'])
    assert restored['id'] != ablated['id'] and restored['parent'] == ablated['id']
    assert restored['sha256'] == original_hash
    assert client.tensor(restored['id'], 'W3')['sha256'] == original_hash
    assert client.tensor(ablated['id'], 'W3')['sha256'] == ablated['sha256']
    runs.append(evaluate('restoration-held-out-parent', ablated['id'], restored['id'], 10000))
    runs.append(evaluate('restoration-held-out-paper', 'paper', restored['id'], 10000,
                         require_identical=True))
    assert runs[-1]['run']['base'] == runs[-1]['run']['candidate']
    assert set(range(1000, 1008)).isdisjoint(range(10000, 10008))
    evidence.update(checkpoints={'ablated': ablated, 'restored': restored}, runs=runs,
                    restored_hash_equals_original=True, restoration_preview=restore_preview)

    # An otherwise valid first assignment must not be saved when a later
    # executable statement is rejected. Inspect every file, not only metadata.
    before = files(workspace)
    sentinel = workspace / 'executed'
    attacks = ["__import__('pathlib').Path(" + repr(str(sentinel)) + ").touch()",
               "b3[0] = 1\n__import__('os').getcwd()",
               'b3[0:2] = [True, 2]', 'W1[0, 0] = 1\nb3[9] = 1']
    rejections = []
    for code in attacks:
        for operation in (client.preview, client.patch):
            response = rejected(lambda: operation('paper', code, 'Synthetic rejection test'), 400)
            assert files(workspace) == before and not sentinel.exists()
            rejections.append(dict(operation=operation.__name__, patch=code, **response))
    evidence['rejections'] = rejections
    evidence['budget_rejection'] = rejected(lambda: client.evaluate(
        'paper', 'paper', episodes=64, max_steps=10000), 422)
    assert files(workspace) == before

    # Wait for actual episode progress so this tests a live MinAtar job, rather
    # than merely cancelling a queued job. The total bound is 240,000 forwards.
    job = client.evaluate('paper', 'paper', episodes=12, seed=30000, max_steps=10000)
    deadline = time.monotonic() + 15
    while True:
        live = client.job(job['id'])
        if live['status'] == 'running' and 0 < live['completed'] < live['total']:
            break
        assert live['status'] in ('queued', 'running'), live
        assert time.monotonic() < deadline, live
        time.sleep(.002)
    start = time.monotonic()
    acknowledgement = client.cancel(job['id'])
    while True:
        cancelled = client.job(job['id'])
        if cancelled['status'] == 'cancelled':
            break
        assert cancelled['status'] == 'cancelling', cancelled
        assert time.monotonic() - start < 5, cancelled
        time.sleep(.002)
    latency = time.monotonic() - start
    assert cancelled['run_id'] is None
    assert not any(p.name.startswith('run-') for p in workspace.iterdir()
                   if p.name not in before)
    probe = client.evaluate('paper', 'paper', episodes=1, seed=40000, max_steps=10)
    probe_run = client.wait(probe['id'], timeout=10, interval=.01)
    assert probe_run['base']['forward_calls'] == 10
    assert client.job(job['id']) == cancelled
    persisted = json.loads((workspace / ('job-' + job['id'] + '.json')).read_text())
    assert persisted == cancelled
    evidence['cancellation'] = dict(live=live, acknowledgement=acknowledgement,
                                    terminal=cancelled, seconds_to_terminal=latency,
                                    followup_job=client.job(probe['id']),
                                    no_cancelled_run_saved=True, terminal_stable=True)
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='godseye-client-validation-') as temporary:
        workspace = Path(temporary)
        env = dict(os.environ, GODSEYE_DATA_DIR=temporary)
        env.pop('GODSEYE_API_TOKEN', None)
        # Keep the ephemeral loopback socket bound and pass it to uvicorn. This
        # avoids the free-port race between closing a probe and starting a server.
        with socket.socket() as sock, (output / 'server.log').open('w') as log:
            sock.bind(('127.0.0.1', 0))
            sock.listen()
            port = sock.getsockname()[1]
            command = ('import sys, uvicorn; from godseye.server import create_app; '
                       'uvicorn.run(create_app(), fd=int(sys.argv[1]), '
                       'proxy_headers=False, log_level="info")')
            process = subprocess.Popen([sys.executable, '-c', command, str(sock.fileno())],
                                       env=env, pass_fds=(sock.fileno(),), stdout=log, stderr=log)
            try:
                client = Client('http://127.0.0.1:' + str(port), timeout=1)
                deadline = time.monotonic() + 15
                while True:
                    assert process.poll() is None, 'Server failed; see server.log'
                    try:
                        client.state()
                        break
                    except OSError:
                        assert time.monotonic() < deadline, 'Server did not become ready'
                client.timeout = 30
                evidence = exercise(client, workspace)
                shutil.copytree(workspace, output / 'artifacts')
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            evidence['server'] = {'pid': process.pid, 'exit_code': process.returncode,
                                  'stopped': process.poll() is not None, 'port': port}
        evidence['temporary_workspace_removed'] = temporary
    assert not workspace.exists()
    evidence['temporary_workspace_removed'] = True
    (output / 'results.json').write_text(json.dumps(evidence, indent=2, allow_nan=False) + '\n')
    print('Evidence:', output, flush=True)


if __name__ == '__main__':
    main()
