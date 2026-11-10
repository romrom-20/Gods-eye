"""Bounded CPU comparison of two deterministic benchmark participants.

Run: python -m experiments.benchmark_demo --output /tmp/repair-evidence.json
Existing output files are never overwritten. No model API or GPU is used.
"""
import argparse
import json
from pathlib import Path
import tempfile

from godseye.benchmark import RepairBenchmark


def run_participant(workspace, participant):
    benchmark = RepairBenchmark(workspace)
    cases = benchmark.create(seed=7, probes=2, forward_budget=800,
                             episodes=2, max_steps=200)
    decisions = []
    for case in cases:
        root = case['root_id']
        selected = root
        decision = {'case_id': case['id'], 'root_id': root}
        if participant == 'zero-output-bias':
            baseline = benchmark.probe(case['id'], root)
            candidate = benchmark.patch(case['id'], root, 'b3[:] = 0',
                                        'Generic hypothesis: remove output-action bias.')
            edited = benchmark.probe(case['id'], candidate['id'])
            decision['probes'] = [baseline, edited]
            if edited['result']['mean_score'] > baseline['result']['mean_score']:
                selected = candidate['id']
        decision['selected_id'] = selected
        benchmark.finalize(case['id'], selected)
        decisions.append(decision)
    return {'participant': participant, 'decisions': decisions, 'report': benchmark.report()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    # Reserve the destination exclusively before doing expensive work.
    try:
        stream = args.output.open('x')
    except OSError as error:
        parser.error(str(error))
    try:
        with tempfile.TemporaryDirectory(prefix='godseye-benchmark-') as temporary:
            results = [run_participant(Path(temporary) / name, name)
                       for name in ('unchanged', 'zero-output-bias')]
        evidence = {
            'schema_version': 1,
            'scope': 'Deterministic baseline comparison, not autonomous repair discovery.',
            'selection_rule': 'Use edited candidate only when probe mean strictly exceeds root.',
            'limits': {'episodes': 2, 'max_steps': 200, 'probes_per_case': 2,
                       'forward_budget_per_case': 800},
            'participants': results,
        }
        with stream:
            json.dump(evidence, stream, indent=2, allow_nan=False)
            stream.write('\n')
    except BaseException:
        stream.close()
        args.output.unlink(missing_ok=True)
        raise
    print(args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
