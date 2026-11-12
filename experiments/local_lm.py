"""Stdlib dry run and explicitly opted-in, subprocess-bounded CPU smoke."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from godseye.lm.local_runtime import plan


def write(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + '\n')


def worker(cache, output, fresh=False):
    from godseye.lm.local_runtime import Runtime, memory
    from godseye.lm.local_delta import applied, load_delta, make_delta, save_delta, target, tensor_hash
    evidence = dict(status='started', real_pretrained=True, generations=[])
    path = output / ('fresh.json' if fresh else 'smoke.json')
    write(path, evidence)
    runtime = None
    try:
        runtime = Runtime(cache)
        evidence['runtime'] = runtime.identity
        base = tensor_hash(target(runtime.model))
        evidence['base_tensor_sha256'] = base
        write(path, evidence)
        if fresh:
            delta = load_delta(output / 'delta.json')
            with applied(runtime.model, delta) as edited:
                evidence['edited_tensor_sha256'] = edited
            evidence['rollback_tensor_sha256'] = tensor_hash(target(runtime.model))
        else:
            prompt = 'Answer with only the number: What is 2 + 3?'
            delta = make_delta(runtime.model, column=0, scale=0.0)
            save_delta(output / 'delta.json', delta)
            def generate(arm):
                result = runtime.generate(prompt, max_new_tokens=16, seconds=20)
                evidence['generations'].append(dict(arm=arm, **result))
                write(path, evidence)
            generate('original')
            with applied(runtime.model, delta) as edited:
                evidence['edited_tensor_sha256'] = edited
                generate('candidate')
            evidence['rollback_tensor_sha256'] = tensor_hash(target(runtime.model))
            generate('rollback')
            with applied(runtime.model, load_delta(output / 'delta.json')):
                generate('export_reload')
            evidence['reload_rollback_tensor_sha256'] = tensor_hash(target(runtime.model))
            records = evidence['generations']
            evidence['behavior_changed'] = records[0]['generated_token_ids'] != records[1]['generated_token_ids']
            evidence['rollback_output_equal'] = records[0]['generated_token_ids'] == records[2]['generated_token_ids']
            evidence['reload_output_equal'] = records[1]['generated_token_ids'] == records[3]['generated_token_ids']
        evidence['memory'] = memory()
        evidence['status'] = 'complete'
    except Exception as exc:
        evidence['status'] = 'error'
        evidence['error'] = dict(type=type(exc).__name__, message=str(exc))
        raise
    finally:
        write(path, evidence)
        if runtime:
            runtime.close()


def execute(args):
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    cache = output / 'weights'
    env = dict(os.environ, OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
               VECLIB_MAXIMUM_THREADS='2', TOKENIZERS_PARALLELISM='false',
               HF_HUB_DISABLE_IMPLICIT_TOKEN='1', HF_HUB_OFFLINE='1')
    command = [sys.executable, '-m', 'experiments.local_lm', '--execute']
    evidence = dict(plan=plan(), command=sys.argv, status='started', stages=[])
    write(output / 'execution.json', evidence)
    def stage(name, argv, timeout):
        started = time.monotonic()
        record = dict(stage=name, timeout_seconds=timeout)
        evidence['stages'].append(record)
        write(output / 'execution.json', evidence)
        try:
            with open(output / (name + '.log'), 'w') as log:
                result = subprocess.run(command + argv, env=env, timeout=timeout,
                                        stdout=log, stderr=subprocess.STDOUT, check=False)
            record['returncode'] = result.returncode
            if result.returncode:
                raise RuntimeError(f'{name} failed; see {name}.log')
        finally:
            record['elapsed_seconds'] = time.monotonic() - started
            write(output / 'execution.json', evidence)
    try:
        stage('download', ['--download', str(cache)], 250)
        start = time.monotonic()
        stage('smoke', ['--worker', str(cache), '--output', str(output)], 300)
        remaining = 300 - (time.monotonic() - start)
        if remaining <= 0:
            raise TimeoutError('aggregate execution deadline')
        stage('fresh', ['--fresh', str(cache), '--output', str(output)], remaining)
        evidence['execution_seconds'] = time.monotonic() - start
        evidence['status'] = 'complete'
    except Exception as exc:
        evidence['status'] = 'incomplete'
        evidence['error'] = dict(type=type(exc).__name__, message=str(exc))
        raise
    finally:
        write(output / 'execution.json', evidence)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--output', default='lm-local-result')
    internal = p.add_mutually_exclusive_group()
    internal.add_argument('--download', help=argparse.SUPPRESS)
    internal.add_argument('--worker', help=argparse.SUPPRESS)
    internal.add_argument('--fresh', help=argparse.SUPPRESS)
    args = p.parse_args()
    # Internal modes are explicitly named execution entry points used by the supervisor.
    if (args.download or args.worker or args.fresh) and not args.execute:
        p.error('execution modes require --execute')
    if args.download:
        from godseye.lm.local_runtime import download
        print(json.dumps(download(args.download)))
    elif args.worker or args.fresh:
        worker(Path(args.worker or args.fresh), Path(args.output), fresh=bool(args.fresh))
    elif args.execute:
        execute(args)
    else:
        print(json.dumps(plan(), indent=2))


if __name__ == '__main__':
    main()
