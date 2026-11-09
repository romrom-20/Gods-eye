"""Re-run the first local experiments, preserving all runs including failures.

Run from the repository root: .venv/bin/python -m experiments.reproduce
"""
import json

from godseye.core import ROOT, Store, digest


def main():
    store = Store()
    ablated = store.patch('paper', 'W3[0:8:2, 1] = 0', 'Ablate left-action output connections')
    restored = store.patch(ablated['id'], 'W3[0:8:2, 1] = 30', 'Restore left-action output connections')
    reactive = store.patch('zero', (ROOT / 'experiments/ball-chaser.edits').read_text(),
                           'Write a reactive ball-chaser from zero weights')
    assert digest(store.weights(restored['id'])) == digest(store.weights('paper'))
    cases = [('paper', ablated['id'], 1000, 'ablation'),
             (ablated['id'], restored['id'], 1000, 'restoration'),
             ('zero', reactive['id'], 1000, 'reactive versus zero'),
             ('paper', reactive['id'], 1000, 'reactive versus paper'),
             ('paper', restored['id'], 10000, 'restoration on disjoint seeds')]
    rows = []
    for base, candidate, seed, name in cases:
        run = store.run(base, candidate, episodes=8, seed=seed, max_steps=3000)
        for model in ('base', 'candidate'):
            run[model].pop('trace')
        run['experiment'] = name
        rows.append(run)
        print(f"{name}: {run['base']['mean']:.3f} → {run['candidate']['mean']:.3f} (run {run['id']})")
    evidence = {'note': 'Exploratory local measurements; eight episodes per model. '
                        'Not a full paper reproduction. See README for the evaluation contract.',
                'checkpoints': {'ablated': ablated, 'restored': restored, 'reactive': reactive},
                'runs': rows}
    path = ROOT / 'experiments/first-session-results.json'
    path.write_text(json.dumps(evidence, indent=2))
    print(f'Evidence: {path}')


if __name__ == '__main__':
    main()
