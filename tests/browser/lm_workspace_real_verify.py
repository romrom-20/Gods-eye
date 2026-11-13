"""Independently verify retained real browser evidence with stdlib only.

Read-only: no service startup, runtime imports, inference, cache access or retries.
Usage: python tests/browser/lm_workspace_real_verify.py /absolute/private/directory
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def verify(root):
    def load(path):
        return json.loads(path.read_text())

    response = load(root / 'service-result.json')
    attachment = load(root / 'downloaded-evidence.json')
    browser = load(root / 'browser-verification.json')
    state = load(root / 'final-service-state.json')
    job = response['job']
    assert job['status'] in ('completed', 'failed', 'cancelled', 'interrupted')
    output = root / 'lm' / job['id'] / 'run'
    raw = load(output / 'report.json')
    spec = load(output / 'spec.json')
    journal = output / 'journal.jsonl'
    events = [json.loads(line) for line in journal.read_text().splitlines()]
    previous = None
    for index, event in enumerate(events):
        assert event['sequence'] == index
        assert event['previous_sha256'] == previous
        assert event['sha256'] == digest({k: v for k, v in event.items() if k != 'sha256'})
        previous = event['sha256']
    assert events[-1]['kind'] == 'finish'
    assert events[-1]['report_sha256'] == digest(raw)
    assert digest(spec['spec']) == spec['sha256'] == job['spec_sha256']
    records = [e['record'] for e in events if e['kind'] == 'result']
    reservations = [e for e in events if e['kind'] == 'reservation']
    assert records == response['attempts'] == raw['records'] == attachment['attempts']
    assert response == attachment
    assert len(reservations) == job['progress']['reserved_attempts']
    assert len(records) == job['progress']['finished_attempts']
    assert all(r['spec_sha256'] == job['spec_sha256'] for r in records)
    assert all(e['rollback_tensor_sha256'] == raw['original_tensor_sha256']
               for e in events if e['kind'] == 'variant_end')
    assert raw['original_tensor_sha256'] == raw['final_tensor_sha256']
    assert len(state['jobs']) == 1 and state['jobs'][0]['id'] == job['id']
    assert sum(e['method'] == 'POST' and e['path'] == '/api/v1/lm/jobs'
               for e in state['audit']) == 1
    assert not any(e['path'].endswith('/cancel') for e in state['audit'])
    assert browser['original_candidate_text_equality']
    if not job['selected_delta_available']:
        assert not (output / 'selected-delta.json').exists()
    return dict(job_id=job['id'], spec_sha256=job['spec_sha256'],
                journal_sha256=hashlib.sha256(journal.read_bytes()).hexdigest(),
                journal_head_sha256=previous, journal_events=len(events),
                attempts=len(records), reservations=len(reservations),
                status_counts=dict(collections.Counter(r['status'] for r in records)),
                journal_chain_verified=True, finish_report_identity_verified=True,
                attempt_envelopes_and_download_equal=True,
                all_recorded_rollbacks_match_original=True,
                exactly_one_admission_and_start=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory), indent=2))
