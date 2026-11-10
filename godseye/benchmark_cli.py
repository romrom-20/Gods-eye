"""JSON command interface for the local concealed-fault benchmark."""
import argparse
import json
from pathlib import Path
import sys

from .benchmark import RepairBenchmark


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create', help='Administrator: create a new suite')
    create.add_argument('--seed', type=int, default=7)
    create.add_argument('--probes', type=int, default=4)
    create.add_argument('--forward-budget', type=int, default=8000)
    create.add_argument('--episodes', type=int, default=2)
    create.add_argument('--max-steps', type=int, default=200)
    sub.add_parser('list', help='List opaque cases and remaining budgets')
    inspect = sub.add_parser('inspect', help='Read a candidate tensor')
    inspect.add_argument('case')
    inspect.add_argument('tensor')
    inspect.add_argument('--candidate')
    patch = sub.add_parser('patch', help='Branch a candidate using numeric assignments')
    patch.add_argument('case')
    patch.add_argument('--parent', required=True)
    patch.add_argument('--file', type=Path, required=True)
    patch.add_argument('--hypothesis', required=True)
    for name in ('probe', 'finalize'):
        operation = sub.add_parser(name)
        operation.add_argument('case')
        operation.add_argument('candidate')
    sub.add_parser('report', help='Administrator: reveal results after ALL selections freeze')
    args = parser.parse_args(argv)
    try:
        benchmark = RepairBenchmark(args.workspace)
        if args.command == 'create':
            result = benchmark.create(seed=args.seed, probes=args.probes,
                                      forward_budget=args.forward_budget,
                                      episodes=args.episodes, max_steps=args.max_steps)
        elif args.command == 'list':
            result = benchmark.cases()
        elif args.command == 'inspect':
            result = benchmark.inspect(args.case, args.tensor, args.candidate)
        elif args.command == 'patch':
            if args.file.stat().st_size > 50000:
                raise ValueError('Patch file exceeds 50,000 bytes')
            result = benchmark.patch(args.case, args.parent, args.file.read_text(), args.hypothesis)
        elif args.command == 'probe':
            result = benchmark.probe(args.case, args.candidate)
        elif args.command == 'finalize':
            result = benchmark.finalize(args.case, args.candidate)
        else:
            result = benchmark.report()
    except (ValueError, KeyError, OSError) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
