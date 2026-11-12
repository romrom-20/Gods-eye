"""Offline by default: python -m experiments.lm_pilot [--execute]."""
import argparse
import json
import shlex
from godseye.lm.spec import plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('smoke', 'pilot'), default='pilot')
    parser.add_argument('--output', default='lm-result')
    parser.add_argument('--execute', action='store_true', help='explicitly download and run fixed model')
    args = parser.parse_args()
    if not args.execute:
        config = plan(args.profile)
        config['command'] = shlex.join(['python', '-m', 'experiments.lm_pilot', '--profile',
                                        args.profile, '--output', args.output, '--execute'])
        print(json.dumps(config, indent=2, sort_keys=True))
        return
    from godseye.lm.evaluate import run
    import signal
    def timeout(signum, frame):
        raise TimeoutError('local invocation walltime cap')
    if not hasattr(signal, 'SIGALRM'):
        raise RuntimeError('bounded local CLI requires POSIX SIGALRM')
    previous = signal.signal(signal.SIGALRM, timeout)
    signal.alarm(600)
    try:
        result = run(args.output, args.profile)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    print(json.dumps(result, indent=2))
    if result['status'] != 'complete':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
