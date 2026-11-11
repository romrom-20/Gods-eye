import argparse
import json
from pathlib import Path

from .core import Store, tensor_summary, digest


def main():
    parser = argparse.ArgumentParser(
        description="God's Eye · local Breakout weight-space workbench",
        epilog="First run: godseye serve, then open http://127.0.0.1:8787/lab. "
               "The local CPU example needs no provider key or Docker.")
    sub = parser.add_subparsers(dest='command', required=True)
    web = sub.add_parser('serve', help='Start the local browser app (requires the server extra)',
                         description='Serve the Breakout browser app. Open /lab on the printed URL. '
                         'No browser opens and no provider work starts automatically.')
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
    importer = sub.add_parser('import-checkpoint', help='Import a local fixed-schema Breakout NPZ')
    importer.add_argument('--file', type=Path, required=True)
    importer.add_argument('--name', required=True)
    importer.add_argument('--provenance', default='')
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
        try:
            import uvicorn  # noqa: F401 — check both optional dependencies before startup
            from .server import serve
        except ModuleNotFoundError as error:
            if error.name not in ('fastapi', 'uvicorn'):
                raise
            parser.error("The browser app needs server dependencies. Install your wheel with "
                         "'[server]' (see docs/install.md), or from a checkout run "
                         "python -m pip install -e '.[server]'.")
        print(f"Open http://{args.host}:{args.port}/lab in your browser. Stop with Ctrl+C.",
              flush=True)
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
    elif args.command == 'import-checkpoint':
        from .checkpoint_import import read_local
        try:
            result = store.import_checkpoint(read_local(args.file), args.name, args.provenance)
        except (ValueError, OSError) as error:
            parser.error(str(error))
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
