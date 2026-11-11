"""Private evaluator RPC. Run inside the supplied container, never as an agent tool.

The host/daemon operator and this code are trusted. The model receives only the
allowlisted RPC tools. No report, paths, seeds, labels or executable uploads are
part of that interface. Local HTTP tests alone do not establish OS isolation.
"""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer

from .activity import Journal
from .benchmark import RepairBenchmark
from .core import NAMES, difference
from .storage import write_json

PARTICIPANTS = ('unchanged', 'heuristic', 'agent')
MAX_BODY = 65536


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Evaluator:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.config = json.loads((self.directory / 'experiment.json').read_text())

    @classmethod
    def create(cls, directory, *, seed=71, instances=3, probes=2,
               forward_budget=800, episodes=2, max_steps=200, participants=PARTICIPANTS):
        if not participants or len(set(participants)) != len(participants) or any(p not in PARTICIPANTS for p in participants):
            raise ValueError('Invalid participants')
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Exclusive directory creation is the initialization lock. Partial setup
        # is deliberately not silently reused after a crash.
        (directory / 'initializing').mkdir()
        keys = {name: secrets.token_urlsafe(32) for name in (*participants, 'admin')}
        settings = dict(seed=seed, instances=instances, probes=probes,
                        forward_budget=forward_budget, episodes=episodes, max_steps=max_steps)
        for name in participants:
            RepairBenchmark(directory / name).create(**settings)
        for name, key in keys.items():
            path = directory / (name + '.token')
            with open(path, 'x', opener=lambda p, f: os.open(p, f, 0o600)) as stream:
                stream.write(key)
        write_json(directory / 'experiment.json', dict(settings=settings, participants=list(participants),
                   tokens={name: token_hash(key) for name, key in keys.items()}))
        return cls(directory)

    def authenticate(self, token):
        if not isinstance(token, str):
            return None
        hashed = token_hash(token)
        return next((name for name, value in self.config['tokens'].items()
                     if hmac.compare_digest(hashed, value)), None)

    def dispatch(self, role, operation, args):
        if role not in self.config['participants'] or type(args) is not dict:
            raise ValueError('Operation unavailable')
        fields = {
            'list': (), 'read': ('case_id', 'candidate_id', 'tensor', 'start', 'count'),
            'patch': ('case_id', 'parent_id', 'patch', 'hypothesis'),
            'evaluate': ('case_id', 'candidate_id'), 'freeze': ('case_id', 'candidate_id'),
        }
        if operation not in fields or set(args) != set(fields[operation]):
            raise ValueError('Invalid operation or fields')
        # Reject arbitrary JSON objects before they reach ID/path lookups.
        for name, value in args.items():
            if name in ('start', 'count'):
                if type(value) is not int:
                    raise ValueError('Slice offsets must be integers')
            elif not isinstance(value, str):
                raise ValueError('Expected string')
        with Journal(self.directory).operation(operation, role) as observe:
            return self._dispatch(role, operation, args, observe)

    def _dispatch(self, role, operation, args, observe):
        bench = RepairBenchmark(self.directory / role, observe=observe)
        if operation == 'list':
            rows = bench.cases()
            for row in rows:
                # Hashes and full patch history need not be tensor-reading shortcuts.
                row['candidates'] = [{'id': c['id'], 'parent': c['parent']}
                                     for c in row['candidates']]
                row['probes_remaining'] = row['probe_limit'] - row['probes_used']
                row['forwards_remaining'] = row['forward_budget'] - row['forward_reserved']
            return dict(cases=rows, tensors={k: list(v[1]) for k, v in NAMES.items()})
        if operation == 'read':
            start, count = args['start'], args['count']
            if start < 0 or not 1 <= count <= 256:
                raise ValueError('Read 1–256 flattened tensor values')
            # Membership checked inside the same lock as the actual load.
            with bench._locked():
                case = bench._case(bench._read(), args['case_id'])
                weights = bench._weights(case, args['candidate_id'])
                if args['tensor'] not in weights:
                    raise ValueError('Unknown tensor')
                value = weights[args['tensor']]
                if start + count > value.size:
                    raise ValueError('Slice exceeds tensor')
                observe('edit_started', count=count)
                return dict(tensor=args['tensor'], shape=list(value.shape), start=start,
                            values=value.ravel()[start:start + count].tolist())
        if operation == 'patch':
            return bench.patch(**args)
        if operation == 'evaluate':
            return bench.probe(**args)
        result = bench.finalize(**args, defer=True)
        observe('selection_frozen')
        return result

    def report(self):
        # Nothing held out is even executed until every participant freezes.
        benches = {name: RepairBenchmark(self.directory / name) for name in self.config['participants']}
        if not all(c['finalized'] for bench in benches.values() for c in bench.cases()):
            raise ValueError('Freeze all participants and cases before reveal')
        with Journal(self.directory).operation('report', 'administrator') as observe:
            for bench in benches.values():
                bench.observe = observe
                bench.finish_frozen()
        reports = {name: bench.report() for name, bench in benches.items()}
        for name, report in reports.items():
            bench = benches[name]
            with bench._locked():
                state = bench._read()
                for case, row in zip(state['cases'], report['cases']):
                    diff = difference(bench._weights(case, case['root_id']),
                                      bench._weights(case, case['final']['candidate_id']))
                    row['selected_diff_from_root'] = diff
                    row['weights_changed'] = sum(d['changed'] for d in diff)
            report['limitations'] = ('Container configuration isolates evaluator files from model tools; '
                'trusted host administrators can read them. Source familiarity or memorization may '
                'limit blindness. Small capped CPU pilot, not novel repair discovery.')
        return dict(settings=self.config['settings'], participants=reports)


def handler(evaluator):
    class Handler(BaseHTTPRequestHandler):
        # Avoid credential/prompt/error logging; no default access log.
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.connection.settimeout(30)
            authorization = self.headers.get('Authorization', '')
            role = evaluator.authenticate(authorization[7:]) if authorization.startswith('Bearer ') else None
            if role is None:
                return self.reply(401, {'error': 'Unauthorized'})
            if self.path not in ('/rpc', '/report'):
                return self.reply(404, {'error': 'Unavailable'})
            try:
                if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/json':
                    raise ValueError()
                size = int(self.headers.get('Content-Length', '-1'))
                if not 0 < size <= MAX_BODY:
                    raise ValueError()
                request = json.loads(self.rfile.read(size))
                if self.path == '/report':
                    if role != 'admin':
                        return self.reply(403, {'error': 'Unavailable'})
                    if request != {}:
                        raise ValueError()
                    result = evaluator.report()
                else:
                    if type(request) is not dict or set(request) != {'operation', 'args'}:
                        raise ValueError()
                    result = evaluator.dispatch(role, request['operation'], request['args'])
                self.reply(200, result)
            except (ValueError, TypeError, KeyError, IndexError, SyntaxError, OverflowError):
                self.reply(400, {'error': 'Invalid request or exhausted/frozen budget'})
            except Exception:
                # Reservation persists. Never leak exception paths or private data.
                self.reply(500, {'error': 'Evaluation failed; reservation retained'})

        def reply(self, code, result):
            body = json.dumps(result, allow_nan=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=71, help='Private suite generation seed; use fresh seeds after reveal')
    parser.add_argument('--initialize', action='store_true')
    parser.add_argument('--initialize-only', action='store_true')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8790)
    args = parser.parse_args()
    if args.initialize or args.initialize_only:
        Evaluator.create(args.state, seed=args.seed)
    if args.initialize_only:
        return
    HTTPServer((args.host, args.port), handler(Evaluator(args.state))).serve_forever()


if __name__ == '__main__':
    main()
