"""Reproduce baseline-only HTTP protocol evidence; NOT an isolated agent run."""
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from http.server import HTTPServer

from godseye.evaluator import Evaluator, handler
from isolation.agent_adapter import Client, baseline


class Rows:
    def __init__(self):
        self.rows = []

    def write(self, row):
        self.rows.append(row)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    plan = Path(__file__).with_name('isolated-pilot-plan.md')
    # Exclusive destination and durable initial record retain unsuccessful runs.
    with args.output.open('x') as stream:
        evidence = dict(schema_version=1, status='running',
                        scope='Baseline-only HTTP protocol validation; evaluator in same user process, NOT isolated.',
                        plan_sha256=hashlib.sha256(plan.read_bytes()).hexdigest(),
                        real_agent=dict(status='unexecuted', reason='No OPENAI_API_KEY configured; no Docker/Podman installed.'),
                        attempts={})
        def save():
            stream.seek(0)
            json.dump(evidence, stream, indent=2, allow_nan=False)
            stream.truncate()
            stream.flush()
        save()
        try:
            with tempfile.TemporaryDirectory(prefix='godseye-protocol-') as temporary:
                evaluator = Evaluator.create(temporary, participants=('unchanged', 'heuristic'))
                server = HTTPServer(('127.0.0.1', 0), handler(evaluator))
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    url = 'http://127.0.0.1:' + str(server.server_port)
                    for name in ('unchanged', 'heuristic'):
                        rows = Rows()
                        evidence['attempts'][name] = rows.rows
                        baseline(Client(url, (Path(temporary) / (name + '.token')).read_text()), name, rows)
                        save()
                    evidence['report'] = evaluator.report()
                    for report in evidence['report']['participants'].values():
                        report['limitations'] = evidence['scope'] + ' ' + report['limitations']
                finally:
                    server.shutdown()
                    server.server_close()
            evidence['status'] = 'completed'
            save()
        except BaseException:
            evidence['status'] = 'failed'
            save()
            raise
    print(args.output)


if __name__ == '__main__':
    main()
