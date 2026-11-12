"""Trusted local adapter for the fixed JSON task; no service or hosted isolation."""
import contextlib
import json
import math
import os
from pathlib import Path
import time

from .task_contract import TaskSpec, canonical, digest, preview
from .task_suite import VARIANTS, cases, dataset_identity, evaluate, freeze_selection, validate_record
from .local_runtime import REVISION, capabilities, task_profile


def approved_spec():
    return TaskSpec(canonical(preview('Improve JSON schema adherence', revision=REVISION)['spec']))


def plan():
    spec = approved_spec()
    return dict(mode='local-cached-json-task', spec=spec.to_dict(), spec_sha256=spec.sha256,
                capabilities=capabilities(task_profile(spec)), downloads=False,
                max_worker_seconds=1800, execution_required=True)


def atomic_json(path, value):
    """Publish complete bytes, fsync file and containing directory before returning."""
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    with open(temp, 'x') as f:
        f.write(canonical(value) + '\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Journal:
    def __init__(self, path):
        self.file = open(path, 'x')
        self.sequence = 0
        self.previous = None

    def append(self, kind, **data):
        if {'sequence', 'previous_sha256', 'kind', 'sha256'} & set(data):
            raise ValueError('reserved journal envelope field')
        body = dict(sequence=self.sequence, previous_sha256=self.previous, kind=kind, **data)
        event = dict(body, sha256=digest(body))
        self.file.write(canonical(event) + '\n')
        self.file.flush()
        os.fsync(self.file.fileno())
        self.sequence += 1
        self.previous = event['sha256']
        return event

    def close(self):
        self.file.close()


def inspect_journal(path):
    """Read-only crash evidence: never resume, retry or synthesize model usage."""
    events = []
    issue = None
    previous = None
    path = Path(path)
    if not path.exists():
        return dict(events=[], interrupted_reservations=[], issue='journal_not_created')
    for line in path.read_bytes().splitlines(keepends=True):
        try:
            if not line.endswith(b'\n'):
                raise ValueError('partial final journal line')
            event = json.loads(line)
            body = {k: v for k, v in event.items() if k != 'sha256'}
            if (event['sequence'] != len(events) or event['previous_sha256'] != previous
                    or event['sha256'] != digest(body)):
                raise ValueError('journal chain mismatch')
            events.append(event)
            previous = event['sha256']
        except (ValueError, KeyError, TypeError) as exc:
            issue = str(exc)
            break
    admitted = {e['attempt_id']: e for e in events if e['kind'] == 'reservation'}
    finished = {e['record']['attempt_id'] for e in events if e['kind'] == 'result'}
    return dict(events=events, interrupted_reservations=[v for k, v in admitted.items()
                                                       if k not in finished], issue=issue)


def settings(spec, case, variant):
    data = spec.to_dict()
    prompt = case['prompt']
    if variant == 'prompt' and case['task'] != 'regression':
        prompt = data['baselines']['prompt']['prefix'] + prompt
    return dict(prompt=prompt, max_new_tokens=data['generation']['max_new_tokens'],
                seconds=data['budgets']['max_seconds_per_attempt'], variant=variant,
                repetition_penalty=(data['baselines']['decoding']['repetition_penalty']
                                    if variant == 'decoding' else 1.0))


def validate_policy(runtime, spec):
    expected = capabilities(task_profile(spec))  # rejects unapproved revision before inference
    if runtime.identity.get('capabilities') != expected:
        raise ValueError('runtime model/tokenizer/hash/generation capabilities mismatch')


def to_record(raw, *, attempt_id, spec, case, variant):
    def count(key):
        value = raw.get(key)
        return value if type(value) is int and value >= 0 else None
    seconds = raw.get('latency_seconds')
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        seconds = None
    input_tokens, output_tokens = count('input_tokens'), count('generated_tokens')
    reason = raw.get('termination')
    # Missing/ambiguous deadline metadata never confers completion.
    status = 'incomplete'
    if reason in ('token_cap', 'walltime') or raw.get('deadline_exceeded') is True:
        status = 'budget_limited'
    elif (reason == 'eos' and raw.get('deadline_exceeded') is False
          and None not in (input_tokens, output_tokens, seconds)):
        status = 'complete'
    limits = spec.to_dict()['budgets']
    if ((input_tokens is not None and input_tokens > limits['max_input_tokens_per_attempt'])
            or (output_tokens is not None and output_tokens > limits['max_output_tokens_per_attempt'])
            or (seconds is not None and seconds > limits['max_seconds_per_attempt'])):
        status = 'budget_limited'
    record = dict(attempt_id=attempt_id, spec_sha256=spec.sha256, case_id=case['id'],
                  split=case['split'], variant=variant, status=status,
                  output=raw.get('output', '') if isinstance(raw.get('output', ''), str) else '',
                  input_tokens=input_tokens, output_tokens=output_tokens, elapsed_seconds=seconds)
    return validate_record(record, spec)


class Editor:
    def __init__(self, runtime, output):
        self.runtime, self.output = runtime, output
        self.deltas = {}

    def hash(self):
        from .local_delta import target, tensor_hash
        return tensor_hash(target(self.runtime.model))

    def prepare(self):
        from .local_delta import make_delta, save_delta
        for variant, column, scale in [('weight-0', 0, 0.0), ('weight-1', 1, 0.5)]:
            delta = make_delta(self.runtime.model, column, scale)
            save_delta(self.output / (variant + '.json'), delta)
            self.deltas[variant] = delta
        return self.deltas

    def applied(self, variant):
        from .local_delta import applied, load_delta
        if variant not in self.deltas:
            return contextlib.nullcontext(self.hash())
        # Independently parse exported numeric artifact every time it is applied.
        return applied(self.runtime.model, load_delta(self.output / (variant + '.json')))

    def verify_selected(self, variant):
        from .local_delta import load_delta, save_delta
        if variant == 'unchanged':
            return None
        artifact = load_delta(self.output / (variant + '.json'))
        save_delta(self.output / 'selected-delta.json', artifact)
        base = self.hash()
        with self.applied(variant) as edited:
            pass
        return dict(variant=variant, base_tensor_sha256=base, edited_tensor_sha256=edited,
                    rollback_tensor_sha256=self.hash(), content_sha256=artifact['content_sha256'])


def run_task(runtime, spec, output, *, editor_factory=Editor):
    """Injected runtimes/editors are for deterministic tests, never CLI model payloads."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    journal = Journal(output / 'journal.jsonl')
    records, hashes = [], []
    frozen = None
    error = None
    base = None
    start = time.monotonic()
    editor = editor_factory(runtime, output)
    selected_check = None
    try:
        validate_policy(runtime, spec)
        atomic_json(output / 'spec.json', dict(spec=spec.to_dict(), sha256=spec.sha256,
                                             model=runtime.identity, dataset=dataset_identity()))
        journal.append('identity', spec_sha256=spec.sha256, dataset=dataset_identity(),
                       runtime=runtime.identity)
        preflight = []
        # Tokenize complete prompts, including heldout, without generating or scoring labels.
        for split in ('dev', 'heldout'):
            for variant in VARIANTS:
                for case in cases(split):
                    opts = settings(spec, case, variant)
                    rendered, _, count = runtime.prepare(opts['prompt'], opts['max_new_tokens'])
                    preflight.append(dict(split=split, variant=variant, case_id=case['id'],
                                          prompt=opts['prompt'], rendered_sha256=digest(rendered),
                                          input_tokens=count, settings=opts))
        atomic_json(output / 'preflight.json', preflight)
        journal.append('preflight_complete', prompt_count=len(preflight), artifact_sha256=digest(preflight))
        base = editor.hash()
        deltas = editor.prepare()
        journal.append('candidates', base_tensor_sha256=base,
                       artifacts={v: d['content_sha256'] for v, d in deltas.items()})
        limits = spec.to_dict()['budgets']
        counts = {v: 0 for v in VARIANTS}

        def execute_split(split, variants):
            for variant in variants:
                if editor.hash() != base:
                    raise RuntimeError('candidate must start from exact original')
                try:
                    with editor.applied(variant) as edited:
                        hashes.append(dict(split=split, variant=variant, base_tensor_sha256=base,
                                           edited_tensor_sha256=edited))
                        journal.append('variant_begin', **hashes[-1])
                        for case in cases(split):
                            if (len(records) >= limits['max_attempts'] or
                                    counts[variant] >= limits['max_attempts_per_variant'] or
                                    time.monotonic() - start >= limits['max_worker_seconds']):
                                raise RuntimeError('finite task budget exhausted; no retry')
                            opts = settings(spec, case, variant)
                            attempt = f'{split}-{variant}-{counts[variant]}'
                            # Admission is durable BEFORE calling a potentially blocking runtime.
                            journal.append('reservation', attempt_id=attempt, spec_sha256=spec.sha256,
                                           case_id=case['id'], split=split, variant=variant,
                                           ordinal=len(records) + 1, settings=opts)
                            counts[variant] += 1
                            raw = None
                            failure = None
                            try:
                                raw = runtime.generate(**opts)
                                record = to_record(raw, attempt_id=attempt, spec=spec,
                                                   case=case, variant=variant)
                            except Exception as exc:
                                failure = dict(type=type(exc).__name__, message=str(exc))
                                record = dict(attempt_id=attempt, spec_sha256=spec.sha256,
                                              case_id=case['id'], split=split, variant=variant,
                                              status='failed', output='', input_tokens=None,
                                              output_tokens=None, elapsed_seconds=None)
                            journal.append('result', record=record, runtime_result=raw, error=failure)
                            records.append(record)
                finally:
                    rollback = editor.hash()
                    journal.append('variant_end', split=split, variant=variant,
                                   rollback_tensor_sha256=rollback)
                    if rollback != base:
                        raise RuntimeError('candidate rollback hash mismatch')

        execute_split('dev', VARIANTS)
        proposed = freeze_selection(spec, records)
        if not proposed['selection_eligible']:
            raise RuntimeError('development incomplete or invalid; heldout forbidden')
        # os.replace + fsync(file) + fsync(directory) must all succeed before heldout.
        atomic_json(output / 'freeze.json', proposed)
        if json.loads((output / 'freeze.json').read_text()) != proposed:
            raise RuntimeError('persisted freeze mismatch; heldout forbidden')
        frozen = proposed
        journal.append('freeze', freeze=frozen)
        selected_check = editor.verify_selected(frozen['selected_weight'])
        if selected_check is not None:
            journal.append('selected_delta_verified', **selected_check)
        execute_split('heldout', frozen['heldout_variants'])
    except Exception as exc:
        error = dict(type=type(exc).__name__, message=str(exc))
        journal.append('stopped', error=error)
    finally:
        # Report uses a recomputed ineligible freeze for incomplete dev only; never a persisted selection.
        assessment = frozen or freeze_selection(spec, records)
        report = evaluate(spec, assessment, records)
        report.update(runtime=runtime.identity, error=error, elapsed_wall_seconds=time.monotonic()-start,
                      persisted_freeze=frozen, selected_delta_check=selected_check,
                      tensor_hashes=hashes, original_tensor_sha256=base,
                      final_tensor_sha256=editor.hash() if base is not None else None)
        if error:
            report['status'], report['verdict'] = 'incomplete', 'not_evaluated'
        atomic_json(output / 'report.json', report)
        journal.append('finish', status=report['status'], verdict=report['verdict'],
                       attempt_count=len(records), report_sha256=digest(report))
        journal.close()
    return report
