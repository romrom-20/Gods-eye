"""Injected synthetic runtimes/processes only; no pretrained inference or downloads."""
import contextlib
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from godseye.lm import local_task_runner as runner
from godseye.lm.local_runtime import capabilities, task_profile, REVISION
from godseye.lm.task_contract import TaskSpec, canonical
from godseye.lm.task_suite import cases, VARIANTS
from experiments.local_lm_task import supervise


class FakeRuntime:
    def __init__(self, directory, *, selected=False, fail=False, cap=False):
        self.directory = Path(directory)
        self.identity = dict(synthetic=True, capabilities=capabilities(task_profile(runner.approved_spec())))
        self.calls = []
        self.selected, self.fail, self.cap = selected, fail, cap
        self.active = 'original'

    def prepare(self, prompt, max_new_tokens):
        return 'synthetic-rendered:' + prompt, None, 100

    def generate(self, **opts):
        journal = runner.inspect_journal(self.directory / 'journal.jsonl')
        assert journal['events'][-1]['kind'] == 'reservation'
        assert len(journal['interrupted_reservations']) == 1  # durable before call
        self.calls.append(opts)
        if self.fail and len(self.calls) == 1:
            raise RuntimeError('synthetic inference error')
        case = next(c for split in ('dev', 'heldout') for c in cases(split)
                    if opts['prompt'].endswith(c['prompt']))
        answer = case['answer'] if case['task'] == 'regression' else canonical(case['answer'])
        if self.selected and opts['variant'] == 'unchanged' and case['task'] != 'regression':
            answer = 'Preamble ' + answer
        # Dev selects weight-0; heldout weight-0 loses one control. Selection must stay frozen.
        if self.selected and opts['variant'] == 'weight-0' and case['id'] == 'heldout-subtraction':
            answer = 'wrong'
        return dict(output=answer, input_tokens=100, generated_tokens=10, latency_seconds=.1,
                    termination='token_cap' if self.cap else 'eos', deadline_exceeded=False)


class FakeEditor:
    def __init__(self, runtime, output):
        self.runtime = runtime
    def hash(self):
        return self.runtime.active
    def prepare(self):
        return {v: {'content_sha256': 'synthetic-' + v} for v in ('weight-0', 'weight-1')}
    @contextlib.contextmanager
    def applied(self, variant):
        self.runtime.active = variant if variant.startswith('weight') else 'original'
        try:
            yield self.hash()
        finally:
            self.runtime.active = 'original'
    def verify_selected(self, variant):
        return None if variant == 'unchanged' else dict(variant=variant,
             base_tensor_sha256='original', edited_tensor_sha256=variant,
             rollback_tensor_sha256='original')


class TaskRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'run'
        self.spec = runner.approved_spec()

    def run_fake(self, **kwargs):
        runtime = FakeRuntime(self.output, **kwargs)
        report = runner.run_task(runtime, self.spec, self.output, editor_factory=FakeEditor)
        return runtime, report

    def test_stdlib_plan_and_scope(self):
        code = """
import socket, sys
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(AssertionError('network'))
from experiments.local_lm_task import main
main()
assert 'torch' not in sys.modules and 'transformers' not in sys.modules
"""
        result = subprocess.run([sys.executable, '-S', '-c', code], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        planned = json.loads(result.stdout)
        self.assertEqual(planned['spec']['baselines']['prompt']['scope'], 'json_targets_only')
        bad = self.spec.to_dict()
        bad['baselines']['prompt']['scope'] = 'all_cases'
        with self.assertRaises(ValueError):
            TaskSpec(canonical(bad))

    def test_policy_mismatch_before_inference(self):
        runtime = FakeRuntime(self.output)
        runtime.identity['capabilities']['weight_sha256'] = '0' * 64
        report = runner.run_task(runtime, self.spec, self.output, editor_factory=FakeEditor)
        self.assertEqual(runtime.calls, [])
        self.assertEqual(report['status'], 'incomplete')
        other = self.spec.to_dict()
        other['model']['revision'] = other['model']['tokenizer_revision'] = 'a' * 40
        with self.assertRaisesRegex(ValueError, 'not approved'):
            task_profile(TaskSpec(canonical(other)))

    def test_reservation_freeze_order_and_exact_baselines(self):
        runtime, report = self.run_fake()
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['attempt_count'], 112)
        events = runner.inspect_journal(self.output / 'journal.jsonl')['events']
        freeze = next(e for e in events if e['kind'] == 'freeze')
        held = next(e for e in events if e['kind'] == 'reservation' and e['split'] == 'heldout')
        self.assertLess(freeze['sequence'], held['sequence'])
        self.assertEqual(json.loads((self.output / 'freeze.json').read_text()), freeze['freeze'])
        self.assertEqual(report['final_tensor_sha256'], 'original')
        for call in runtime.calls:
            self.assertEqual((call['max_new_tokens'], call['seconds']), (96, 60))
            self.assertEqual(call['repetition_penalty'], 1.1 if call['variant'] == 'decoding' else 1.0)
        control = next(c for c in cases('dev') if c['task'] == 'regression')
        self.assertEqual(runner.settings(self.spec, control, 'prompt')['prompt'], control['prompt'])
        target = cases('dev')[0]
        self.assertEqual(runner.settings(self.spec, target, 'prompt')['prompt'],
                         self.spec.to_dict()['baselines']['prompt']['prefix'] + target['prompt'])

    def test_failed_calls_count_and_rollback_no_heldout(self):
        runtime, report = self.run_fake(fail=True)
        self.assertEqual(len(runtime.calls), 70)
        self.assertEqual(report['attempt_count'], 70)
        self.assertEqual(report['records'][0]['status'], 'failed')
        self.assertIsNone(report['records'][0]['output_tokens'])
        self.assertEqual(report['status'], 'incomplete')
        self.assertFalse((self.output / 'freeze.json').exists())
        self.assertEqual(runtime.active, 'original')
        self.assertEqual(len(runner.inspect_journal(self.output / 'journal.jsonl')['events']),
                         1 + 1 + 1 + 5 * 2 + 70 * 2 + 1 + 1)

    def test_candidate_error_restores_original(self):
        class FailingEditor(FakeEditor):
            @contextlib.contextmanager
            def applied(self, variant):
                with super().applied(variant) as value:
                    if variant == 'weight-0':
                        raise RuntimeError('synthetic edit error')
                    yield value
        runtime = FakeRuntime(self.output)
        report = runner.run_task(runtime, self.spec, self.output, editor_factory=FailingEditor)
        self.assertEqual(report['attempt_count'], 42)
        self.assertEqual(report['status'], 'incomplete')
        self.assertEqual(runtime.active, 'original')

    def test_freeze_persistence_failure_forbids_heldout(self):
        original = runner.atomic_json
        def disk_failure(path, data):
            if path.name == 'freeze.json':
                raise OSError('synthetic fsync failure')
            return original(path, data)
        with patch.object(runner, 'atomic_json', side_effect=disk_failure):
            runtime, report = self.run_fake()
        self.assertEqual(len(runtime.calls), 70)
        self.assertEqual(report['status'], 'incomplete')
        self.assertIsNone(report['persisted_freeze'])

    def test_frozen_selection_never_reselects_on_heldout(self):
        runtime, report = self.run_fake(selected=True)
        self.assertEqual(report['attempt_count'], 126)
        self.assertEqual(report['persisted_freeze']['selected_weight'], 'weight-0')
        self.assertEqual(report['verdict'], 'no_improvement')
        self.assertNotIn('weight-1', report['heldout'])
        self.assertEqual(report['selected_delta_check']['variant'], 'weight-0')

    def test_token_cap_unknown_usage_and_incomplete_dev(self):
        runtime, report = self.run_fake(cap=True)
        self.assertEqual(report['attempt_count'], 70)
        self.assertTrue(all(r['status'] == 'budget_limited' for r in report['records']))
        self.assertEqual(report['verdict'], 'not_evaluated')
        case = cases('dev')[0]
        raw = dict(output='{}', termination='eos', deadline_exceeded=False)
        record = runner.to_record(raw, attempt_id='unknown', spec=self.spec, case=case, variant='unchanged')
        self.assertEqual(record['status'], 'incomplete')
        self.assertIsNone(record['output_tokens'])

    def test_crash_journal_retains_interrupted_reservation(self):
        self.output.mkdir()
        path = self.output / 'journal.jsonl'
        journal = runner.Journal(path)
        with patch.object(runner.os, 'fsync', wraps=runner.os.fsync) as sync:
            journal.append('reservation', attempt_id='interrupted')
            self.assertEqual(sync.call_count, 1)
        journal.close()
        with open(path, 'ab') as f:
            f.write(b'{"partial":')
        audit = runner.inspect_journal(path)
        self.assertEqual(audit['interrupted_reservations'][0]['attempt_id'], 'interrupted')
        self.assertIn('partial', audit['issue'])

    def test_aggregate_deadline_prevents_launch(self):
        ticks = iter([0, 1801, 1802])
        with patch('experiments.local_lm_task.subprocess.Popen') as launch:
            result = supervise(['synthetic-only'], Path(self.temp.name) / 'expired',
                               clock=lambda: next(ticks), process_factory=launch)
        launch.assert_not_called()
        self.assertEqual(result['status'], 'incomplete')

    def test_supervisor_timeout_cancel_kills_and_waits(self):
        for index, exception in enumerate((subprocess.TimeoutExpired('fake', 1), KeyboardInterrupt())):
            class Process:
                pid = 123
                returncode = None
                killed = False
                waits = 0
                def wait(self, timeout=None):
                    self.waits += 1
                    if self.waits == 1:
                        raise exception
                    self.returncode = -9
                    return -9
                def poll(self):
                    return None
                def kill(self):
                    self.killed = True
            process = Process()
            result = supervise(['synthetic-only'], Path(self.temp.name) / f'supervisor-{index}',
                               seconds=1, process_factory=lambda *a, **k: process)
            self.assertTrue(process.killed)
            self.assertEqual(process.waits, 2)
            self.assertTrue(result['children'][0]['cleanup_waited'])
            self.assertEqual(result['status'], 'cancelled' if index else 'incomplete')
        with self.assertRaises(FileExistsError):
            supervise(['synthetic-only'], Path(self.temp.name) / 'supervisor-0')


if __name__ == '__main__':
    unittest.main()
