"""One ephemeral fixed GPU invocation; dry-run never imports Modal or builds images."""
import argparse
import json
import shlex
from pathlib import Path
from godseye.lm.spec import plan, VERSIONS


def image_sources():
    """Exact source upload allowlist, shared with offline staging tests."""
    source = Path(__file__).resolve().parents[1]/'godseye'/'lm'
    return [(source.parent/'__init__.py', '/root/godseye/__init__.py')] + [
        (source/name, '/root/godseye/lm/'+name)
        for name in ('__init__.py', 'spec.py', 'delta.py', 'runtime.py', 'evaluate.py')]


def make_worker():
    """Return code serialized by value without capturing this launcher module."""
    def worker(profile):
        import tempfile
        from pathlib import Path
        from godseye.lm.evaluate import run
        folder = Path(tempfile.mkdtemp())/'evidence'
        error = None
        try:
            run(folder, profile)
        except Exception as exc:
            error = type(exc).__name__+': '+str(exc)[:2000]
        files = {p.name: p.read_text() for p in folder.glob('*') if p.is_file()}
        return dict(files=files, error=error)

    return worker


def execute(output, profile):
    # Create destination before touching Modal; refuse overwrite/resume.
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=False)
    (destination/'launch-plan.json').write_text(json.dumps(plan(profile), indent=2))
    import importlib.metadata
    if importlib.metadata.version('modal') != VERSIONS['modal']:
        raise RuntimeError('install the pinned optional Modal SDK')
    import modal
    # Explicit allowlist: upload only trusted pilot .py files, never repository data,
    # environment, credentials, homes, arbitrary user modules, or the workspace tree.
    image = modal.Image.debian_slim(python_version='3.12').pip_install(
        *[f'{k}=={v}' for k,v in VERSIONS.items() if k != 'modal'])
    image = image.env({'HF_HUB_DISABLE_IMPLICIT_TOKEN': '1', 'HF_HOME': '/tmp/lm-hf'})
    for local_path, remote_path in image_sources():
        image = image.add_local_file(str(local_path), remote_path)
    app = modal.App('godseye-lm-bounded-pilot', include_source=False)

    worker = app.function(image=image, gpu='L4', cpu=(2, 2), memory=(16384, 16384),
                  serialized=True, include_source=False, single_use_containers=True,
                  max_containers=1, min_containers=0, buffer_containers=0,
                  scaledown_window=2, timeout=600, startup_timeout=180, retries=0)(make_worker())

    # run context is ephemeral; no deployment, endpoint, Volume, or secrets.
    with app.run():
        call = worker.spawn(profile)
        (destination/'modal-call.json').write_text(json.dumps({'call_id': call.object_id}))
        try:
            result = call.get(timeout=800)
        except BaseException as exc:
            (destination/'client-failure.json').write_text(json.dumps(
                {'error_type': type(exc).__name__, 'status': 'incomplete',
                 'action': 'cancel requested; verify app stopped in Modal dashboard'}))
            call.cancel(terminate_containers=True)
            raise
    for name, content in result['files'].items():
        if name not in {'plan.json', 'runtime.json', 'frozen.json', 'cases.jsonl', 'summary.json',
                        'failure.json', 'rollback.json', 'reload.json', 'selected-delta.json',
                        'candidate-0.json', 'candidate-1.json', 'edit-checks.json'}:
            raise RuntimeError('unexpected returned evidence file')
        (destination/name).write_text(content)
    if result['error']:
        raise RuntimeError(result['error'])
    if json.loads(result['files']['summary.json'])['status'] != 'complete':
        raise RuntimeError('incomplete run: inspect all saved evidence')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('smoke', 'pilot'), default='pilot')
    parser.add_argument('--output', default='lm-modal-result')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.execute:
        execute(args.output, args.profile)
    else:
        config = plan(args.profile)
        config['command'] = shlex.join(['python', '-m', 'experiments.modal_lm_pilot', '--profile',
                                        args.profile, '--output', args.output, '--execute'])
        print(json.dumps(config, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
