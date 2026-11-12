"""Publish only bundled, recorded evidence to an ordinary static web directory."""
import json
from pathlib import Path
import shutil

from .backends import DATA_DIR
from .core import Store, digest, tensor_summary
from .web_assets import page_html


def export_demo(destination):
    destination = Path(destination)
    # No overwriting existing sites and no accidental publication of a user's workspace.
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Export destination must be empty')
    destination.mkdir(parents=True, exist_ok=True)
    static = Path(__file__).parent / 'static'
    for name in ('app.js', 'style.css', 'landing.css', 'landing.js', 'api.html', 'LICENSE.txt', 'THIRD_PARTY_NOTICES.md'):
        shutil.copyfile(static / name, destination / name)
    (destination / 'index.html').write_text(page_html('landing.html', static))
    lab = page_html('index.html', static).replace('<html lang="en">', '<html lang="en" data-static-demo="true">')
    lab = lab.replace('<title>God’s Eye — Describe an experiment</title>',
                      '<title>God’s Eye — Recorded demo</title>')
    start = lab.index('        <section data-view="goal"')
    end = lab.index('        <section data-view="overview"', start)
    lab = lab[:start] + """        <section data-view="goal" class="view" aria-label="Recorded demo">
          <div class="panel first-experiment">
            <span class="overline">RECORDED PUBLIC DEMO · READ ONLY</span>
            <h2>Inspect the change. Replay the evidence.</h2>
            <p>Explore two bundled comparisons and four checkpoints of a 20,486-parameter
            Breakout policy. These are saved measurements and gameplay, not a live AI experiment.</p>
            <p>Ablation and restoration demonstrate a known circuit. They do not establish
            AI-discovered repair, general improvement, or cost savings.</p>
            <div class="first-actions">
              <a class="primary" href="#overview">Watch the recordings →</a>
              <a class="secondary" href="#workbench">Inspect saved tensors →</a>
            </div>
            <p>To create edits or run a supported goal, install the local lab.
            AI-guided goals additionally require the operator service, Docker, a private
            evaluation suite, an explicitly selected provider model, and reviewed limits.</p>
            <a href="./#start">Local installation instructions →</a>
          </div>
        </section>

""" + lab[end:]
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
