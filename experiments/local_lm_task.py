"""One trusted cached-model task run, with an owned-process wall deadline."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from godseye.lm.local_task_runner import approved_spec, atomic_json, inspect_journal, plan


def supervise(command, output, *, seconds=1800, process_factory=subprocess.Popen, clock=time.monotonic):
    """No retries. Always kill/wait our direct child on timeout or interruption."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    start = clock()
    evidence = dict(status='started', plan=plan(), command=command, children=[])
    child = None
    def save():
        atomic_json(output / 'supervisor.json', evidence)
    save()
    try:
        stages = [('task', command)]
        for name, argv in stages:
            remaining = seconds - (clock() - start)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, seconds)
            with open(output / (name + '.log'), 'x') as log:
                child = process_factory(argv, stdout=log, stderr=subprocess.STDOUT,
                                        start_new_session=True, env=dict(os.environ,
                        OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2',
                        VECLIB_MAXIMUM_THREADS='2', HF_HUB_OFFLINE='1',
                        HF_HUB_DISABLE_IMPLICIT_TOKEN='1', TOKENIZERS_PARALLELISM='false'))
                entry = dict(stage=name, pid=child.pid, deadline_seconds=remaining)
                evidence['children'].append(entry)
                save()
                code = child.wait(timeout=remaining)
                entry['returncode'] = code
                child = None
                if code != 0:
                    raise RuntimeError('task worker failed/incomplete; inspect journal and report; no retry')
            report_path = output / 'run' / 'report.json'
            report = json.loads(report_path.read_text())
            if report['status'] != 'complete':
                raise RuntimeError('task evidence incomplete; no retry or heldout tuning')
            if name == 'task' and report['selected_delta_check'] is not None:
                # Main child is gone: fresh pinned model, no further generations.
                verify_command = [a if a != '--worker' else '--verify-selected' for a in command]
                stages.append(('selected-reload', verify_command))
            if name == 'selected-reload':
                checked = json.loads((output / 'selected-reload.json').read_text())
                for key in ('base_tensor_sha256', 'edited_tensor_sha256', 'rollback_tensor_sha256'):
                    if checked[key] != report['selected_delta_check'][key]:
                        raise RuntimeError('fresh-process selected delta hash mismatch')
        evidence['status'] = 'complete'
    except KeyboardInterrupt:
        evidence['status'] = 'cancelled'
        evidence['error'] = 'operator interrupted; owned worker killed and waited; no automatic resume'
    except subprocess.TimeoutExpired:
        evidence['status'] = 'incomplete'
        evidence['error'] = 'aggregate wall deadline exhausted; owned worker killed and waited; no retry'
    except Exception as exc:
        evidence['status'] = 'incomplete'
        evidence['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        if child is not None:
            if child.poll() is None:
                child.kill()
            child.wait()
            evidence['children'][-1]['returncode'] = child.returncode
            evidence['children'][-1]['cleanup_waited'] = True
        evidence['elapsed_wall_seconds'] = clock() - start
        audit = inspect_journal(output / 'run' / 'journal.jsonl')
        evidence['journal_audit'] = dict(valid_events=len(audit['events']), issue=audit['issue'],
                                        interrupted_reservations=audit['interrupted_reservations'])
        save()
    return evidence


def worker(cache, output, verify=False):
    from godseye.lm.local_runtime import Runtime
    from godseye.lm.local_task_runner import run_task
    runtime = Runtime(cache, task_spec=approved_spec())
    try:
        if verify:
            from godseye.lm.local_delta import applied, load_delta, target, tensor_hash
            artifact = load_delta(output / 'run' / 'selected-delta.json')
            base = tensor_hash(target(runtime.model))
            with applied(runtime.model, artifact) as edited:
                pass
            atomic_json(output / 'selected-reload.json', dict(status='complete',
                base_tensor_sha256=base, edited_tensor_sha256=edited,
                rollback_tensor_sha256=tensor_hash(target(runtime.model)), runtime=runtime.identity))
        else:
            report = run_task(runtime, approved_spec(), output / 'run')
            if report['status'] != 'complete':
                raise RuntimeError('incomplete evaluation; see durable task report')
    finally:
        runtime.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--cache')
    parser.add_argument('--output', default='lm-local-task-result')
    internal = parser.add_mutually_exclusive_group()
    internal.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    internal.add_argument('--verify-selected', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if (args.worker or args.verify_selected) and not args.execute:
        parser.error('internal execution requires --execute')
    if not args.execute:
        print(json.dumps(plan(), indent=2))
        return
    if not args.cache:
        parser.error('--execute requires an explicitly selected verified --cache directory; no downloads')
    output = Path(args.output).resolve()
    cache = Path(args.cache).resolve()
    if args.worker or args.verify_selected:
        worker(cache, output, args.verify_selected)
        return
    command = [sys.executable, '-m', 'experiments.local_lm_task', '--execute',
               '--worker', '--cache', str(cache), '--output', str(output)]
    evidence = supervise(command, output)
    if evidence['status'] != 'complete':
        raise SystemExit('Local task incomplete/cancelled; inspect supervisor.json and run/journal.jsonl; no retry.')


if __name__ == '__main__':
    main()
