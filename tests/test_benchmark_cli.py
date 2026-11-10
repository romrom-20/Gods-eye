"""External process tests for the persistent benchmark agent interface."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class BenchmarkCLITests(unittest.TestCase):
    def test_persistent_agent_workflow_and_report_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / 'suite'

            def command(*arguments, expected=0):
                process = subprocess.run(
                    [sys.executable, '-m', 'godseye.benchmark_cli', '--workspace',
                     str(workspace), *arguments], capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, expected, process.stderr)
                return json.loads(process.stdout if expected == 0 else process.stderr)

            cases = command('create', '--probes', '1', '--forward-budget', '10',
                            '--episodes', '1', '--max-steps', '10')
            self.assertEqual(len(cases), 4)
            self.assertEqual(command('list'), cases)
            command('report', expected=2)
            first = cases[0]
            values = command('inspect', first['id'], 'b3')
            self.assertEqual(values['shape'], [6])
            patch = Path(directory) / 'candidate.edits'
            patch.write_text('b3[:] = 0\n')
            candidate = command('patch', first['id'], '--parent', first['root_id'],
                                '--file', str(patch), '--hypothesis', 'Remove output bias')
            result = command('probe', first['id'], candidate['id'])
            public = json.dumps([cases, values, candidate, result])
            for forbidden in ('heldout', 'clean_score', 'fault_type', 'fault_label'):
                self.assertNotIn(forbidden, public)
            command('probe', first['id'], candidate['id'], expected=2)
            command('finalize', first['id'], candidate['id'])
            command('report', expected=2)
            for case in cases[1:]:
                command('finalize', case['id'], case['root_id'])
            self.assertIsInstance(command('report'), dict)
            command('create', expected=2)

    def test_demo_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'evidence.json'
            target.write_text('preserve me')
            result = subprocess.run(
                [sys.executable, '-m', 'experiments.benchmark_demo', '--output', str(target)],
                capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_text(), 'preserve me')
