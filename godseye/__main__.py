import argparse
import json
from pathlib import Path

from .core import Store, tensor_summary, digest


def main():
    parser = argparse.ArgumentParser(description="God's Eye · direct weight-space workbench")
    sub = parser.add_subparsers(dest='command', required=True)
    web = sub.add_parser('serve')
    web.add_argument('--port', type=int, default=8787)
    web.add_argument('--demo', action='store_true', help='Serve bundled evidence read-only')
    web.add_argument('--host', default='127.0.0.1')
    export = sub.add_parser('export-demo', help='Export the recorded demo as a static website')
    export.add_argument('--output', type=Path, default=Path('dist/demo'))
    inspect = sub.add_parser('inspect')
    inspect.add_argument('checkpoint', nargs='?', default='paper')
    patch = sub.add_parser('patch')
    patch.add_argument('--base', default='paper')
    patch.add_argument('--file', type=Path, required=True)
    patch.add_argument('--hypothesis', required=True)
    compare = sub.add_parser('compare')
    compare.add_argument('--base', default='zero')
    compare.add_argument('--candidate', default='paper')
    compare.add_argument('--episodes', type=int, default=8)
    compare.add_argument('--seed', type=int, default=1000)
    compare.add_argument('--max-steps', type=int, default=3000)
    from .local_setup import add_commands, execute
    add_commands(sub)
    args = parser.parse_args()
    if args.command in ('bootstrap', 'launch', 'readiness'):
        raise SystemExit(execute(args))
    if args.command == 'serve':
        from .server import serve
        serve(args.port, demo=args.demo, host=args.host)
        return
    if args.command == 'export-demo':
        from .export import export_demo
        print(export_demo(args.output))
        return
    store = Store()
    if args.command == 'inspect':
        weights = store.weights(args.checkpoint)
        result = {'sha256': digest(weights), 'tensors': tensor_summary(weights)}
    elif args.command == 'patch':
        result = store.patch(args.base, args.file.read_text(), args.hypothesis)
    else:
        result = store.run(args.base, args.candidate, episodes=args.episodes,
                           seed=args.seed, max_steps=args.max_steps)
        for model in ('base', 'candidate'):
            result[model].pop('trace')
        result['artifact'] = str(store.path / ('run-' + result['id'] + '.json'))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
