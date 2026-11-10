"""Acceptance-only scripted worker. No real provider, Docker, or user data.

Used by test_goal_service_acceptance.py when the orchestration backend is present.
The real adapter/evaluator enforce tools, reservations and the global freeze gate.
This fixture does not claim container isolation or model improvement.
"""
import json
import threading
import urllib.error

from godseye.evaluator import Evaluator
from godseye.storage import write_json
from isolation.agent_adapter import Evidence, baseline, run_agent

PROVIDER_SECRET = 'sk-acceptance-temporary-only-87324'
PRIVATE_MARKER = 'PRIVATE_EVALUATION_CANARY_93824'
UPSTREAM_MARKER = 'PRIVATE_UPSTREAM_ERROR_57833'


def goal_request(**changes):
    body = dict(schema_version=1, text='Improve Breakout score',
                provider=dict(name='openai', model='scripted-acceptance', routing='price'),
                limits=dict(max_requests=40, max_input_tokens=10000,
                            max_total_output_tokens=2000, max_seconds=30,
                            max_rounds=40, max_calls=80, max_output_tokens=100))
    body.update(changes)
    return body


def start_request(plan, key='acceptance_click'):
    return dict(schema_version=1, draft_id=plan['draft_id'], spec_hash=plan['spec_hash'],
                confirmed=True, idempotency_key=key)


def query(run):
    return dict(schema_version=1, experiment_id=run['experiment_id'])


class ScriptedWorker:
    capacity = 1

    def __init__(self):
        self.mode = 'complete'
        self.calls, self.provider_bodies, self.recovered = [], [], []
        self.entered, self.release = threading.Event(), threading.Event()
        self.block = False
        self.key_reads = 0
        self.at_root = None
        self.before_report = None
        self.evaluator = None

    def available(self):
        return True

    def recover(self, row, registration, directory):
        # No process survives this in-process fixture. Production recovery is separate.
        self.recovered.append(row['id'])

    def execute(self, row, registration, directory, settings, check, accounting):
        from godseye.orchestration import WorkerFailure, read_accounting

        self.calls.append(row['id'])
        credential = settings.credential(row['spec']['provider']['name'])
        self.key_reads += 1
        if credential != PROVIDER_SECRET:
            raise AssertionError('Acceptance must use only its temporary key')
        evaluator = self.evaluator = Evaluator(registration['directory'])
        fixture = self

        class Client:
            def __init__(self, role):
                self.role = role

            def call(self, operation, args):
                check()
                result = evaluator.dispatch(self.role, operation, args)
                if self.role == 'agent' and operation == 'evaluate' and fixture.at_root:
                    fixture.at_root(evaluator)
                return result

        class AccountingEvidence(Evidence):
            def write(self, value):
                super().write(value)
                accounting()

        # Exercise the real unchanged and heuristic baseline arms too.
        for role in ('unchanged', 'heuristic'):
            with (directory / 'evidence' / (role + '.jsonl')).open('x') as stream:
                class BaselineEvidence:
                    def write(self, value):
                        stream.write(json.dumps(value) + '\n')
                baseline(Client(role), role, BaselineEvidence())

        pending = []
        for case in evaluator.dispatch('agent', 'list', {})['cases']:
            args = dict(case_id=case['id'], candidate_id=case['root_id'])
            pending.extend([('evaluate', args), ('freeze', args)])

        def provider(body):
            # Called only by the real adapter after its request reservation.
            self.provider_bodies.append(json.loads(json.dumps(body)))
            self.entered.set()
            if self.block and not self.release.wait(5):
                raise AssertionError('Acceptance barrier was not released')
            check()
            if self.mode == 'provider_429':
                raise urllib.error.HTTPError('https://unused.invalid/private', 429,
                                             UPSTREAM_MARKER + credential, {}, None)
            if self.mode == 'provider_error':
                raise ConnectionError(UPSTREAM_MARKER + credential)
            if self.mode == 'missing_selections':
                return dict(output=[], **usage())
            if self.mode == 'spin':
                operation, args = 'list', {}
            elif pending:
                operation, args = pending.pop(0)
            else:
                return dict(output=[], **usage())
            return dict(output=[dict(type='function_call', call_id='c' + str(len(pending)),
                                     name=operation, arguments=json.dumps(args))], **usage())

        def usage():
            return {} if self.mode == 'unknown_usage' else dict(
                usage=dict(input_tokens=2, output_tokens=3))

        log = AccountingEvidence(directory / 'evidence' / 'agent.jsonl')
        try:
            try:
                ok = run_agent(Client('agent'), provider, log,
                               model=row['spec']['provider']['model'], **row['spec']['limits'])
            except RuntimeError:
                check()
                raise WorkerFailure('provider_error') from None
        finally:
            log.stream.close()
        check()
        if not ok:
            _, reason, _ = read_accounting(log.path)
            raise WorkerFailure('budget_exhausted' if (reason or '').endswith('_limit')
                                else 'provider_error')
        if self.before_report:
            self.before_report(evaluator)
        # Do not synthesize measurements: use actual tiny held-out rollouts.
        write_json(directory / 'held-out.json', evaluator.report())
        check()
