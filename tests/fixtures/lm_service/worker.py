"""Explicitly SYNTHETIC HTTP/service acceptance worker. Never loads a model."""
import contextlib
import json
from pathlib import Path
import signal
import sys
import time

from godseye.lm.local_delta import FORMAT, MODEL, PARAMETER, REVISION, SHAPE, WEIGHT_SHA256, digest
from godseye.lm.local_runtime import capabilities, task_profile
from godseye.lm.local_task_runner import Journal, approved_spec, atomic_json, run_task
from godseye.lm.task_contract import canonical
from godseye.lm.task_suite import cases

mode, stage, output = sys.argv[1:]
output = Path(output)
BASE = 'a' * 64
EDITED = 'b' * 64


class Runtime:
    identity = dict(synthetic=True, capabilities=capabilities(task_profile(approved_spec())))
    active = BASE

    def prepare(self, prompt, max_new_tokens):
        return prompt, None, 100

    def generate(self, **opts):
        case = next(c for s in ('dev', 'heldout') for c in cases(s) if opts['prompt'].endswith(c['prompt']))
        answer = case['answer'] if case['task'] == 'regression' else canonical(case['answer'])
        if mode.startswith('selected') and opts['variant'] == 'unchanged' and case['task'] != 'regression':
            answer = 'Preamble ' + answer
        return dict(output=answer, input_tokens=100, generated_tokens=10, latency_seconds=.1,
                    termination='token_cap' if mode == 'incomplete' else 'eos', deadline_exceeded=False)


class Editor:
    def __init__(self, runtime, output):
        self.runtime, self.output = runtime, output
        self.deltas = {}

    def hash(self):
        return self.runtime.active

    def prepare(self):
        from godseye.lm.local_delta import save_delta
        for variant, column, scale in [('weight-0', 0, 0.0), ('weight-1', 1, 0.5)]:
            body = dict(format=FORMAT, model=MODEL, revision=REVISION, weight_sha256=WEIGHT_SHA256,
                        parameter=PARAMETER, shape=SHAPE, dtype='float32', column=column, scale=scale,
                        before=[1.0] * 896, after=[scale] * 896,
                        base_tensor_sha256=BASE, edited_tensor_sha256=EDITED)
            delta = dict(body, content_sha256=digest(body))
            self.deltas[variant] = delta
            save_delta(self.output / (variant + '.json'), delta)
        return self.deltas

    @contextlib.contextmanager
    def applied(self, variant):
        self.runtime.active = EDITED if variant.startswith('weight') else BASE
        try:
            yield self.hash()
        finally:
            self.runtime.active = ('c' * 64) if mode == 'rollback' else BASE

    def verify_selected(self, variant):
        if variant == 'unchanged':
            return None
        from godseye.lm.local_delta import save_delta
        delta = self.deltas[variant]
        save_delta(self.output / 'selected-delta.json', delta)
        return dict(variant=variant, base_tensor_sha256=BASE, edited_tensor_sha256=EDITED,
                    rollback_tensor_sha256=BASE, content_sha256=delta['content_sha256'])


if stage == 'selected-reload':
    atomic_json(output / 'selected-reload.json', dict(status='complete', base_tensor_sha256=BASE,
                edited_tensor_sha256=EDITED, rollback_tensor_sha256=BASE if mode != 'selected-bad' else EDITED))
elif mode in ('hold', 'crash'):
    (output / 'run').mkdir()
    journal = Journal(output / 'run/journal.jsonl')
    case = cases('dev')[0]
    journal.append('reservation', attempt_id='partial', spec_sha256=approved_spec().sha256,
                   case_id=case['id'], split='dev', variant='unchanged')
    journal.close()
    if mode == 'crash':
        sys.exit(2)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    (output / 'ready').touch()
    while True:
        time.sleep(.1)
else:
    report = run_task(Runtime(), approved_spec(), output / 'run', editor_factory=Editor)
    if mode == 'malformed':
        (output / 'run/report.json').write_text('[]')
    sys.exit(0 if report['status'] == 'complete' else 1)
