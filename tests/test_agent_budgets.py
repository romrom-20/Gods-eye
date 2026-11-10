"""Offline admission/accounting tests: no secrets, network, or experiment."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from isolation.agent_adapter import (BUDGET_DEFAULTS, Evidence, ProviderRouter,
                                     main, run_agent)


def response(input_tokens=2, output_tokens=3, *, pending=True):
    return dict(usage=dict(input_tokens=input_tokens, output_tokens=output_tokens),
                output=[dict(type='function_call', name='list', arguments='{}', call_id='x')]
                if pending else [])


class FakeClient:
    def __init__(self, finalized=False):
        self.calls = []
        self.finalized = finalized

    def call(self, name, args):
        self.calls.append((name, args))
        return {'cases': [{'finalized': self.finalized}]}


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.evidence = Evidence(self.folder / 'agent.jsonl')
        self.addCleanup(self.evidence.stream.close)
        self.client = FakeClient()
        self.requests = []

    def rows(self):
        return [json.loads(line) for line in self.evidence.path.read_text().splitlines()]

    def run_fake(self, result=None, **limits):
        def respond(body):
            self.requests.append(body)
            return result if result is not None else response()
        return run_agent(self.client, respond, self.evidence, model='dummy', **limits)

    def test_request_boundary_and_per_response_limit(self):
        self.assertFalse(self.run_fake(max_requests=2, max_output_tokens=17))
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(r['max_output_tokens'] == 17 for r in self.requests))
        self.assertEqual(self.rows()[-1]['reason'], 'provider_request_limit')
        self.assertEqual(self.rows()[-1]['cumulative']['requests'], 2)
        self.assertEqual(self.rows()[0]['limits']['max_requests'], 2)

    def test_input_equality(self):
        self.assertFalse(self.run_fake(max_input_tokens=4))
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.rows()[-1]['reason'], 'input_token_limit')

    def test_output_overshoot(self):
        self.assertFalse(self.run_fake(max_total_output_tokens=4))
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.rows()[-1]['reason'], 'output_token_limit')
        self.assertEqual(self.rows()[-1]['cumulative']['output_tokens'], 6)

    def test_tool_boundary(self):
        self.assertFalse(self.run_fake(max_calls=1))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(self.rows()[-1]['reason'], 'tool_call_limit')

    def test_round_boundary(self):
        self.assertFalse(self.run_fake(max_rounds=1))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.rows()[-1]['reason'], 'round_limit')

    def test_time_equality_before_request(self):
        with patch('isolation.agent_adapter.time.monotonic', side_effect=[0, 0, 5, 5]):
            self.assertFalse(self.run_fake(max_seconds=5))
        self.assertEqual(self.requests, [])
        self.assertEqual(self.rows()[-1]['reason'], 'elapsed_time_limit')

    def test_inflight_time_exhaustion_records_usage_without_tools(self):
        now = [0]
        def respond(body):
            now[0] = 6
            return response()
        with patch('isolation.agent_adapter.time.monotonic', side_effect=lambda: now[0]):
            self.assertFalse(run_agent(self.client, respond, self.evidence, model='dummy', max_seconds=5))
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.rows()[-1]['cumulative']['input_tokens'], 2)
        self.assertEqual(self.rows()[-1]['reason'], 'elapsed_time_limit')

    def test_missing_malformed_usage_is_terminal(self):
        bad = [None, {}, {'total_tokens': 4}, {'input_tokens': 1},
               {'input_tokens': True, 'output_tokens': 2},
               {'input_tokens': -1, 'output_tokens': 2},
               {'input_tokens': 1.5, 'output_tokens': 2},
               {'input_tokens': '1', 'output_tokens': 2},
               {'input_tokens': 1, 'output_tokens': float('nan')},
               {'input_tokens': 1, 'output_tokens': 2, 'prompt_tokens': 3, 'completion_tokens': 2}]
        for index, usage in enumerate(bad):
            with self.subTest(usage=usage):
                folder = self.folder / str(index)
                folder.mkdir()
                evidence = Evidence(folder / 'agent.jsonl')
                requests = []
                with contextlib.closing(evidence.stream):
                    def respond(body):
                        requests.append(body)
                        return dict(response(), usage=usage)
                    self.assertFalse(run_agent(self.client, respond, evidence, model='dummy'))
                rows = [json.loads(x) for x in evidence.path.read_text().splitlines()]
                self.assertEqual(rows[-1]['reason'], 'missing_or_malformed_usage')
                self.assertFalse(rows[-1]['cumulative']['usage_complete'])
                self.assertEqual(len(requests), 1)
        self.assertEqual(self.client.calls, [])

    def test_chat_usage_and_no_raw_usage_secrets(self):
        value = response(pending=False)
        value['usage'] = dict(prompt_tokens=2, completion_tokens=3, arbitrary='secret-canary')
        self.client.finalized = True
        self.assertTrue(self.run_fake(value, max_requests=1))
        self.assertNotIn('secret-canary', self.evidence.path.read_text())
        self.assertEqual(self.rows()[-1]['cumulative']['output_tokens'], 3)

    def test_zero_usage_still_counts_requests(self):
        self.assertFalse(self.run_fake(response(0, 0), max_requests=2))
        self.assertEqual(len(self.requests), 2)

    def test_errors_and_interruptions_reserve_request_and_redact(self):
        for index, error in enumerate([RuntimeError('secret-canary'), KeyboardInterrupt(), SystemExit()]):
            folder = self.folder / str(index)
            folder.mkdir()
            evidence = Evidence(folder / 'agent.jsonl')
            seen = []
            def fail(body):
                seen.append(body)
                # Reservation must already be durable before entering provider code.
                self.assertEqual(json.loads(evidence.path.read_text().splitlines()[-1])['event'], 'request')
                raise error
            with contextlib.closing(evidence.stream), self.assertRaises(type(error)):
                run_agent(self.client, fail, evidence, model='dummy')
            saved = evidence.path.read_text()
            self.assertNotIn('secret-canary', saved)
            last = json.loads(saved.splitlines()[-1])
            self.assertEqual(last['cumulative']['requests'], 1)
            self.assertFalse(last['cumulative']['usage_complete'])
            self.assertEqual(len(seen), 1)
            self.assertEqual(last['event'], 'failed')

    def test_incomplete_chat_response_retains_reported_usage(self):
        router = ProviderRouter('openrouter', 'dummy', transport=lambda *args: {
            'usage': {'prompt_tokens': 7, 'completion_tokens': 8},
            'choices': [{'finish_reason': 'length'}]})
        with self.assertRaises(RuntimeError):
            run_agent(self.client, router, self.evidence, model='dummy')
        self.assertEqual(self.rows()[-1]['cumulative']['input_tokens'], 7)
        self.assertTrue(self.rows()[-1]['cumulative']['usage_complete'])

    def test_error_response_counts_usage_without_executing_tools(self):
        value = dict(response(), status='failed', error={'message': 'secret-canary'})
        self.assertFalse(self.run_fake(value))
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.rows()[-1]['reason'], 'provider_response_incomplete')
        self.assertEqual(self.rows()[-1]['cumulative']['input_tokens'], 2)
        self.assertNotIn('secret-canary', self.evidence.path.read_text())

    def test_malformed_chat_response_counts_usage(self):
        router = ProviderRouter('huggingface', 'dummy', transport=lambda *args: {
            'usage': {'prompt_tokens': 7, 'completion_tokens': 8}, 'choices': []})
        with self.assertRaises(RuntimeError):
            run_agent(self.client, router, self.evidence, model='dummy')
        self.assertEqual(self.rows()[-1]['cumulative']['input_tokens'], 7)

    def test_cli_environment_and_override_without_real_secrets(self):
        key, token = self.folder / 'key', self.folder / 'token'
        key.write_text('dummy-key-canary')
        token.write_text('dummy-token-canary')
        path = self.folder / 'cli.jsonl'
        argv = ['adapter', '--participant', 'agent', '--token-file', str(token),
                '--evidence', str(path), '--max-requests', '2']
        requests = []
        def respond(body):
            requests.append(body)
            return response()
        with patch.dict(os.environ, {'REPAIR_AGENT_KEY_FILE': str(key),
                                     'REPAIR_AGENT_MODEL': 'dummy',
                                     'REPAIR_AGENT_MAX_REQUESTS': '1',
                                     'REPAIR_AGENT_MAX_INPUT_TOKENS': '99'}, clear=True), \
                patch('sys.argv', argv), \
                patch('isolation.agent_adapter.Client', return_value=self.client), \
                patch('isolation.agent_adapter.ProviderRouter', return_value=respond):
            self.assertEqual(main(), 1)
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        start = next(row for row in rows if row['event'] == 'start')
        self.assertEqual(start['limits']['max_requests'], 2)
        self.assertEqual(start['limits']['max_input_tokens'], 99)
        self.assertEqual(len(requests), 2)
        self.assertNotIn('canary', path.read_text())

    def test_restart_new_filename_rejected_even_after_success(self):
        self.client.finalized = True
        self.assertTrue(self.run_fake(response(pending=False)))
        other = Evidence(self.folder / 'restart.jsonl')
        with contextlib.closing(other.stream):
            self.assertFalse(run_agent(self.client, lambda _: self.fail('must not request'), other, model='dummy'))
        self.assertEqual(json.loads(other.path.read_text())['reason'], 'resume_rejected')
        with self.assertRaises(FileExistsError):
            Evidence(self.evidence.path)

    def test_invalid_limits_before_claim_or_request(self):
        for name in BUDGET_DEFAULTS:
            for value in (0, -1, True, 1.5, float('inf'), '2'):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    self.run_fake(**{name: value})
        self.assertFalse((self.folder / '.agent-run.claim').exists())
        self.assertEqual(self.requests, [])

    def test_cli_env_validation_before_secret_read(self):
        argv = ['adapter', '--participant', 'agent', '--token-file', '/never-read',
                '--evidence', str(self.folder / 'cli.jsonl')]
        for value in ('0', '-1', 'nan', '1.2', ''):
            with patch.dict(os.environ, {'REPAIR_AGENT_MAX_REQUESTS': value}), patch('sys.argv', argv), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 2)
        self.assertFalse((self.folder / 'cli.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
