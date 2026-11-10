"""Publish only bundled, recorded evidence to an ordinary static web directory."""
import json
from pathlib import Path
import shutil

from .backends import DATA_DIR
from .core import Store, digest, tensor_summary


def export_demo(destination):
    destination = Path(destination)
    # No overwriting existing sites and no accidental publication of a user's workspace.
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Export destination must be empty')
    destination.mkdir(parents=True, exist_ok=True)
    static = Path(__file__).parent / 'static'
    for name in ('app.js', 'style.css', 'landing.css', 'landing.js', 'api.html', 'LICENSE.txt', 'THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(static / name, destination / name)
    shutil.copyfile(static / 'landing.html', destination / 'index.html')
    lab = (static / 'index.html').read_text().replace('<html lang="en">', '<html lang="en" data-static-demo="true">')
    (destination / 'lab.html').write_text(lab)
    store = Store(DATA_DIR / 'demo')
    tensors = {}
    for checkpoint in store.checkpoints():
        weights = store.weights(checkpoint['id'])
        tensors[checkpoint['id']] = {
            name: {'name': name, 'values': v.tolist(), 'summary': tensor_summary(weights), 'sha256': digest(weights)}
            for name, v in weights.items()
        }
    runs = store.runs()
    payload = {'state': {'checkpoints': store.checkpoints(), 'backend': store.backend.id,
                        'parameters': 20486, 'architecture': '600 → 32 → 32 → 6 · tanh',
                        'mode': 'recorded-demo', 'capabilities': ['tensor_read'],
                        'limits': {'max_forwards': 250000, 'queue_capacity': 0}},
               'tensors': tensors, 'runs': runs,
               'traces': {r['id']: store.read_run(r['id']) for r in runs},
               'preset': {'patch': (DATA_DIR / 'presets/ball-chaser.edits').read_text()}}
    (destination / 'demo.json').write_text(json.dumps(payload, allow_nan=False, separators=(',', ':')))
    (destination / '.nojekyll').touch()
    shutil.copyfile(DATA_DIR / 'breakout/UPSTREAM-LICENSE.txt', destination / 'NETWORK-LICENSE.txt')
    shutil.copyfile(DATA_DIR / 'breakout/PROVENANCE.md', destination / 'NETWORK-PROVENANCE.md')
    return destination.resolve()
