"""Standalone restricted repair agent: standard library only, no evaluator imports.

Copy ONLY this file into an empty agent directory. The trusted adapter holds the
API key and participant token; neither is included in model context or evidence.
"""
import argparse
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

PROMPT = '''You are a tensor repair coding agent. Investigate opaque checkpoints of a
600→32→32→6 tanh policy for Breakout, softmax actions: no-op,left,up,right,down,fire.
Some checkpoints may need no changes. Discover useful numeric tensor edits using
only the provided tools. Read slices use flattened row-major offsets (max 256).
Patch language: tensor[index/slice] = numeric scalar or exact-shape list; +=, -=,
*= supported. No expressions, calls, imports or executable code. Write a specific
hypothesis for each immutable patch. Evaluate root and proposed edits on development
seeds within the listed budgets. Select conservatively; ties favor root. Freeze one
candidate for EVERY case before finishing. No held-out feedback is available.
Do not assume faults or known reference weights. You have no filesystem or shell.
'''

FIELDS = {
    'list': {},
    'read': dict(case_id='string', candidate_id='string', tensor='string', start='integer', count='integer'),
    'patch': dict(case_id='string', parent_id='string', patch='string', hypothesis='string'),
    'evaluate': dict(case_id='string', candidate_id='string'),
    'freeze': dict(case_id='string', candidate_id='string'),
}
TOOLS = [dict(type='function', name=name, description={
    'list': 'List opaque cases, tensor shapes and remaining budgets',
    'read': 'Read a bounded candidate tensor slice',
    'patch': 'Create an immutable numeric patch with hypothesis',
    'evaluate': 'Spend a development probe; failures still consume reservation',
    'freeze': 'Permanently freeze a case selection; no held-out result returned',
}[name], strict=True, parameters=dict(type='object',
    properties={k: {'type': v} for k, v in fields.items()},
    required=list(fields), additionalProperties=False)) for name, fields in FIELDS.items()]


def post(url, token, body):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


PROVIDER_URLS = {
    'openai': 'https://api.openai.com/v1/responses',
    'openrouter': 'https://openrouter.ai/api/v1/chat/completions',
    'huggingface': 'https://router.huggingface.co/v1/chat/completions',
}


class ProviderResponseError(ValueError):
    """A received but unusable response can still carry billable usage."""
    def __init__(self, usage):
        super().__init__('Provider did not complete the response')
        self.usage = usage


class ProviderRouter:
    """Fixed destinations, no retries or cross-provider fallback. Injectable transport."""
    def __init__(self, provider, key, routing='price', transport=None):
        if provider not in PROVIDER_URLS or routing not in ('price', 'latency', 'throughput'):
            raise ValueError('Unsupported provider or routing policy')
        self.provider, self.key, self.routing, self.transport = provider, key, routing, transport or post

    def __call__(self, body):
        if self.provider == 'openai':
            return self.transport(PROVIDER_URLS[self.provider], self.key, body)
        messages = []
        for item in body['input']:
            if item.get('_chat_skip'):
                continue
            if '_chat_message' in item:
                messages.append(item['_chat_message'])
                continue
            kind = item.get('type')
            if kind == 'function_call':
                messages.append({'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': item['call_id'], 'type': 'function', 'function': {
                        'name': item['name'], 'arguments': item['arguments']}}]})
            elif kind == 'function_call_output':
                messages.append({'role': 'tool', 'tool_call_id': item['call_id'], 'content': item['output']})
            elif kind == 'message':
                messages.append({'role': 'assistant', 'content': ''.join(
                    part.get('text', '') for part in item.get('content', []))})
            elif 'role' in item:
                messages.append(item)
        payload = {'model': body['model'], 'messages': messages,
                   'tools': [{'type': 'function', 'function': {k: v for k, v in tool.items() if k != 'type'}}
                             for tool in body['tools']],
                   'max_tokens': body['max_output_tokens'], 'stream': False}
        if self.provider == 'openrouter':
            payload['provider'] = {'sort': self.routing, 'require_parameters': True,
                                   'data_collection': 'deny', 'allow_fallbacks': False}
        response = self.transport(PROVIDER_URLS[self.provider], self.key, payload)
        try:
            choice = response['choices'][0]
            if choice.get('finish_reason') not in ('stop', 'tool_calls'):
                raise ProviderResponseError(response.get('usage'))
            message = choice['message']
            output = []
            if message.get('content') and not message.get('tool_calls'):
                output.append({'type': 'message', 'role': 'assistant', 'content': [
                    {'type': 'output_text', 'text': message['content']}]})
            for index, call in enumerate(message.get('tool_calls', [])):
                output.append({'type': 'function_call', 'call_id': call['id'],
                               'name': call['function']['name'], 'arguments': call['function']['arguments'],
                               **({'_chat_message': message} if index == 0 else {'_chat_skip': True})})
            return {'output': output, 'usage': response.get('usage'), 'status': 'completed',
                    'model': response.get('model'), 'provider': response.get('provider')}
        except (KeyError, IndexError, TypeError, AttributeError, ValueError):
            # Malformed replies can still report billable usage. Never retry parsing.
            raise ProviderResponseError(response.get('usage') if isinstance(response, dict)
                                        else None) from None


class Client:
    def __init__(self, url, token):
        # Credentials must never be sent to an arbitrary model-chosen URL.
        parsed = urlsplit(url)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'evaluator')
                or not parsed.port or parsed.username or parsed.password or parsed.path not in ('', '/')
                or parsed.query or parsed.fragment):
            raise ValueError('Evaluator must be loopback or the private evaluator container')
        self.url, self.token = url.rstrip('/'), token

    def call(self, name, args):
        if name not in FIELDS or type(args) is not dict or set(args) != set(FIELDS[name]):
            return {'error': 'Invalid tool or arguments'}
        try:
            return post(self.url + '/rpc', self.token, {'operation': name, 'args': args})
        except urllib.error.HTTPError as error:
            return {'error': 'Evaluator rejected request', 'status': error.code}
        except (OSError, TimeoutError):
            # A disconnect may have spent budget. Never retry automatically.
            return {'error': 'Transport failed; inspect remaining budgets before continuing'}


class Evidence:
    def __init__(self, path):
        self.path = Path(path)
        self.stream = self.path.open('x')

    def write(self, row):
        self.stream.write(json.dumps(row, allow_nan=False) + '\n')
        self.stream.flush()
        os.fsync(self.stream.fileno())


# All limits are finite positive integers; zero/unlimited is deliberately unsupported.
BUDGET_DEFAULTS = dict(max_requests=80, max_input_tokens=200000,
                       max_total_output_tokens=20000, max_seconds=900,
                       max_rounds=80, max_calls=160, max_output_tokens=2000)


def positive_integer(value):
    if isinstance(value, bool) or not str(value).isascii() or not str(value).isdigit():
        raise ValueError('Budget limits must be positive integers')
    result = int(value)
    if result < 1:
        raise ValueError('Budget limits must be positive integers')
    return result


def claim_agent_run(evidence):
    """The dedicated evidence directory is the run identity. Never resume it."""
    marker = evidence.path.parent / '.agent-run.claim'
    try:
        with marker.open('x') as stream:
            stream.write('Agent run claimed; resume is unsupported. Preserve this file.\n')
            stream.flush()
            os.fsync(stream.fileno())
        # Persist directory entries before any provider request, including after a crash.
        fd = os.open(str(marker.parent), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except FileExistsError:
        evidence.write(dict(event='incomplete', reason='resume_rejected'))
        return False
    return True


def reported_usage(response):
    """Accept only a complete nonnegative integer pair, never total_tokens alone."""
    usage = response.get('usage') if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None
    pairs = [('input_tokens', 'output_tokens'), ('prompt_tokens', 'completion_tokens')]
    present = [pair for pair in pairs if any(k in usage for k in pair)]
    if not present:
        return None
    values = []
    for pair in present:
        counts = tuple(usage.get(k) for k in pair)
        if any(type(n) is not int or n < 0 for n in counts):
            return None
        values.append(counts)
    if any(pair != values[0] for pair in values):
        return None
    return values[0]


def run_agent(client, respond, evidence, *, model, max_rounds=80, max_calls=160,
              max_seconds=900, max_output_tokens=2000, max_requests=80,
              max_input_tokens=200000, max_total_output_tokens=20000):
    """Admission limits use reported usage, not dollar charges or token estimates."""
    limits = dict(max_rounds=max_rounds, max_calls=max_calls, max_seconds=max_seconds,
                  max_output_tokens=max_output_tokens, max_requests=max_requests,
                  max_input_tokens=max_input_tokens,
                  max_total_output_tokens=max_total_output_tokens)
    for value in limits.values():
        if type(value) is not int:
            raise ValueError('Budget limits must be positive integers')
        positive_integer(value)
    if not claim_agent_run(evidence):
        return False
    started = time.monotonic()
    requests, input_tokens, output_tokens, calls = 0, 0, 0, 0
    usage_complete = True
    in_flight = False
    failure_recorded = False

    def totals():
        return dict(requests=requests, input_tokens=input_tokens, output_tokens=output_tokens,
                    calls=calls, elapsed_seconds=max(0, time.monotonic() - started),
                    usage_complete=usage_complete, request_in_flight=in_flight)

    def stop(reason, event='incomplete'):
        evidence.write(dict(event=event, reason=reason, cumulative=totals()))
        return False

    def ceiling():
        for exhausted, reason in (
                (time.monotonic() - started >= max_seconds, 'elapsed_time_limit'),
                (requests >= max_requests, 'provider_request_limit'),
                (input_tokens >= max_input_tokens, 'input_token_limit'),
                (output_tokens >= max_total_output_tokens, 'output_token_limit'),
                (calls >= max_calls, 'tool_call_limit')):
            if exhausted:
                return reason
        return None

    messages = [{'role': 'user', 'content': PROMPT}]
    evidence.write(dict(event='start', model=model, **limits, limits=limits,
                        cumulative=totals(), prompt=PROMPT, resume_supported=False))
    try:
        for turn in range(max_rounds):
            reason = ceiling()
            if reason:
                return stop(reason)
            requests += 1
            in_flight = True
            # Reserve and fsync before transport: errors/interruption never refund requests.
            evidence.write(dict(event='request', turn=turn, cumulative=totals()))
            try:
                response = respond(dict(model=model, input=messages, tools=TOOLS,
                                        parallel_tool_calls=False, store=False,
                                        max_output_tokens=max_output_tokens))
            except BaseException as error:
                usage = (reported_usage({'usage': error.usage})
                         if isinstance(error, ProviderResponseError) else None)
                if usage is not None:
                    input_tokens += usage[0]
                    output_tokens += usage[1]
                else:
                    usage_complete = False
                if isinstance(error, ProviderResponseError):
                    in_flight = False
                failure_recorded = True
                stop('provider_request_interrupted' if isinstance(error, (KeyboardInterrupt, SystemExit))
                     else 'provider_request_failed', event='failed')
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise
                raise RuntimeError('Agent runtime failed; see redacted evidence') from None
            in_flight = False
            usage = reported_usage(response)
            if usage is None:
                usage_complete = False
            else:
                input_tokens += usage[0]
                output_tokens += usage[1]
            # Keep normalized accounting; discard arbitrary provider usage extras.
            evidence.write(dict(event='response', turn=turn,
                                usage=None if usage is None else dict(
                                    input_tokens=usage[0], output_tokens=usage[1]),
                                status=response.get('status') if isinstance(response, dict) else None,
                                resolved_model=response.get('model') if isinstance(response, dict) else None,
                                resolved_provider=response.get('provider') if isinstance(response, dict) else None,
                                cumulative=totals()))
            if usage is None:
                return stop('missing_or_malformed_usage')
            if ('error' in response or response.get('status') not in (None, 'completed')):
                return stop('provider_response_incomplete', event='failed')
            # Time exhaustion also prevents additional evaluator operations.
            if time.monotonic() - started >= max_seconds:
                return stop('elapsed_time_limit')
            output = response.get('output', [])
            messages.extend(output)
            pending = [item for item in output if item.get('type') == 'function_call']
            if not pending:
                state = client.call('list', {})
                if state.get('cases') and all(c['finalized'] for c in state['cases']):
                    evidence.write(dict(event='completed', calls=calls, cumulative=totals()))
                    return True
                return stop('agent_stopped_before_all_freezes')
            for item in pending:
                if calls >= max_calls:
                    return stop('tool_call_limit')
                if time.monotonic() - started >= max_seconds:
                    return stop('elapsed_time_limit')
                calls += 1
                try:
                    args = json.loads(item['arguments'])
                    result = client.call(item['name'], args)
                except (ValueError, TypeError, KeyError):
                    args, result = None, {'error': 'Malformed tool call'}
                evidence.write(dict(event='tool', name=item.get('name'), args=args, result=result))
                messages.append(dict(type='function_call_output', call_id=item['call_id'],
                                     output=json.dumps(result)))
            reason = ceiling()
            if reason:
                return stop(reason)
        return stop('round_limit')
    except Exception:
        if not failure_recorded:
            stop('runtime_failure', event='failed')
        raise RuntimeError('Agent runtime failed; see redacted evidence') from None


def baseline(client, participant, evidence):
    for case in client.call('list', {})['cases']:
        root, cid = case['root_id'], case['id']
        selected = root
        if participant == 'heuristic':
            before = client.call('evaluate', dict(case_id=cid, candidate_id=root))
            evidence.write(dict(event='probe', case_id=cid, result=before))
            candidate = client.call('patch', dict(case_id=cid, parent_id=root,
                patch='b3[:] = 0', hypothesis='Generic hypothesis: remove output-action bias.'))
            evidence.write(dict(event='patch', case_id=cid, result=candidate))
            if 'id' in candidate:
                after = client.call('evaluate', dict(case_id=cid, candidate_id=candidate['id']))
                evidence.write(dict(event='probe', case_id=cid, result=after))
                if ('result' in before and 'result' in after and
                        after['result']['mean_score'] > before['result']['mean_score']):
                    selected = candidate['id']
        result = client.call('freeze', dict(case_id=cid, candidate_id=selected))
        evidence.write(dict(event='freeze', result=result))
        if not result.get('frozen'):
            raise RuntimeError('Freeze failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8790')
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--participant', choices=('agent', 'unchanged', 'heuristic'), required=True)
    parser.add_argument('--provider', choices=tuple(PROVIDER_URLS), default=os.environ.get('REPAIR_AGENT_PROVIDER', 'openai'))
    parser.add_argument('--routing', choices=('price', 'latency', 'throughput'), default=os.environ.get('REPAIR_AGENT_ROUTING', 'price'))
    parser.add_argument('--model', default=os.environ.get('REPAIR_AGENT_MODEL'))
    for name, default in BUDGET_DEFAULTS.items():
        parser.add_argument('--' + name.replace('_', '-'), type=positive_integer,
                            default=os.environ.get('REPAIR_AGENT_' + name.upper(), str(default)))
    args = parser.parse_args()
    evidence = Evidence(args.evidence)
    try:
        api_key = ''
        if args.participant == 'agent':
            key_file = os.environ.get('REPAIR_AGENT_KEY_FILE') or os.environ.get('OPENAI_API_KEY_FILE')
            if key_file:
                api_key = Path(key_file).read_text().strip()
            elif args.provider == 'openai':
                api_key = os.environ.get('OPENAI_API_KEY', '')
        if args.participant == 'agent' and (not api_key or not args.model):
            evidence.write(dict(event='unexecuted', reason='Provider key file and explicit model required'))
            return 2
        client = Client(args.url, args.token_file.read_text().strip())
        if args.participant != 'agent':
            baseline(client, args.participant, evidence)
            return 0
        evidence.write(dict(event='routing', provider=args.provider, routing=args.routing,
                            endpoint=PROVIDER_URLS[args.provider], automatic_retries=False))
        respond = ProviderRouter(args.provider, api_key, args.routing)
        return 0 if run_agent(client, respond, evidence, model=args.model,
                              **{name: getattr(args, name) for name in BUDGET_DEFAULTS}) else 1
    finally:
        evidence.stream.close()


if __name__ == '__main__':
    raise SystemExit(main())
