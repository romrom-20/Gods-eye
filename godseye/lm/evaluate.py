"""Development-only selection, frozen heldout comparison, complete append-only evidence."""
import contextlib
import json
from pathlib import Path
import time
from .delta import applied, make_delta, load_delta, target, tensor_hash
from .spec import ARMS, cohort, digest, plan


def write(path, data):
    with Path(path).open('x') as f:
        json.dump(data, f, sort_keys=True, indent=2, allow_nan=False)


def score(case, output):
    return float(output.strip() == case['answer'])


def paired(rows, split):
    base = {r['id']: r for r in rows if r['split'] == split and r['arm'] == 'unchanged'}
    result = {}
    for arm in ARMS[1:]:
        values = [r for r in rows if r['split'] == split and r['arm'] == arm]
        pairs = [(base[r['id']]['score'], r['score']) for r in values if r['id'] in base]
        result[arm] = dict(n=len(pairs), mean_difference=(sum(b-a for a,b in pairs)/len(pairs)
                          if pairs else None), regressions=sum(b<a for a,b in pairs),
                          improvements=sum(b>a for a,b in pairs), verdict='inconclusive_tiny_fixture')
    return result


def run(output, profile='pilot', runtime_factory=None):
    config = plan(profile)
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=False)
    write(folder/'plan.json', config)
    rows = []
    runtime = None
    status = 'failed'
    freeze = None
    try:
        if runtime_factory is None:
            from .runtime import Runtime
            runtime_factory = Runtime
        runtime = runtime_factory(config)  # exactly one model load
        write(folder/'runtime.json', runtime.identity)
        baseline_hash = tensor_hash(target(runtime.model))
        deadline = time.monotonic()+config['evaluation_seconds']
        def evaluate(split, arm, candidate=None):
            for case in cohort(split, config):
                record = dict(id=case['id'], task=case['task'], split=split, arm=arm,
                              candidate=candidate, prompt=case['prompt'], answer=case['answer'])
                try:
                    if len(rows) >= config['max_generations'] or time.monotonic() >= deadline:
                        record.update(output='', score=0.0, termination='budget_exhausted',
                                      generated_tokens=0, latency_seconds=0.0)
                    else:
                        prompt = case['prompt']
                        if arm == 'prompt':
                            prompt = config['prompt_baseline_prefix']+prompt
                        result = runtime.generate(prompt, decoding=arm == 'decoding',
                                                  seconds=min(15, max(0.01, deadline-time.monotonic())))
                        record.update(result, prompt=prompt, score=score(case, result['output']))
                except Exception as exc:
                    record.update(output='', score=0.0, termination='error',
                                  generated_tokens=None, latency_seconds=None,
                                  error_type=type(exc).__name__, error=str(exc)[:1000])
                rows.append(record)
                with (folder/'cases.jsonl').open('a') as f:
                    f.write(json.dumps(record, sort_keys=True, allow_nan=False)+'\n')
                print(json.dumps({'lm_case_evidence': record}, sort_keys=True), flush=True)
        # Train is a disclosed unused demonstration split, never pooled into selection.
        for arm in ARMS[:3]:
            evaluate('dev', arm)
        candidates = []
        edit_checks = []
        for index, edit in enumerate(config['candidates']):
            artifact = make_delta(runtime.model, **edit)
            write(folder/f'candidate-{index}.json', artifact)
            edit_start = time.monotonic()
            with applied(runtime.model, load_delta(folder/f'candidate-{index}.json')):
                apply_seconds = time.monotonic()-edit_start
                evaluate('dev', 'weight', index)
                rollback_start = time.monotonic()
            edit_checks.append(dict(candidate=index, apply_hash_reload_seconds=apply_seconds,
                                    rollback_hash_seconds=time.monotonic()-rollback_start))
            dev = [r for r in rows if r['split']=='dev' and r['arm']=='weight'
                   and r['candidate']==index]
            candidates.append(dict(index=index, artifact=artifact,
                                   score=sum(r['score'] for r in dev)/len(dev),
                                   valid=all(r['termination'] in ('eos','token_cap') for r in dev)))
        write(folder/'edit-checks.json', edit_checks)
        base = [r for r in rows if r['split']=='dev' and r['arm']=='unchanged']
        base_mean = sum(r['score'] for r in base)/len(base)
        eligible = [c for c in candidates if c['valid'] and c['score'] > base_mean
                    and all(r['termination'] in ('eos','token_cap') for r in base)]
        selected = max(eligible, key=lambda c: (c['score'], -c['index'])) if eligible else None
        freeze = dict(config_sha256=digest(config), base_tensor_sha256=baseline_hash,
                      selected_candidate=selected['index'] if selected else None,
                      selected_delta_sha256=selected['artifact']['content_sha256'] if selected else None,
                      rule='strict dev mean improvement; valid generations only; ties lowest index',
                      selected_at_unix=time.time())
        write(folder/'frozen.json', dict(freeze, content_sha256=digest(freeze)))
        for arm in ARMS:
            ctx = applied(runtime.model, load_delta(folder/f"candidate-{selected['index']}.json")) \
                if arm=='weight' and selected else contextlib.nullcontext()
            with ctx:
                evaluate('heldout', arm, selected['index'] if arm=='weight' and selected else None)
        if tensor_hash(target(runtime.model)) != baseline_hash:
            raise RuntimeError('final rollback mismatch')
        if selected:
            write(folder/'selected-delta.json', selected['artifact'])
            # Independent file reload and reapplication, then exact original rollback.
            with applied(runtime.model, load_delta(folder/'selected-delta.json')) as edited_hash:
                write(folder/'reload.json', dict(edited_tensor_sha256=edited_hash))
        write(folder/'rollback.json', dict(base_tensor_sha256=tensor_hash(target(runtime.model)), verified=True))
        status = 'complete' if all(r['termination'] in ('eos','token_cap') for r in rows) else 'incomplete'
    except Exception as exc:
        write(folder/'failure.json', dict(error_type=type(exc).__name__, error=str(exc)[:2000]))
        raise
    finally:
        summary = dict(status=status, real_model_execution=runtime is not None and not runtime.identity.get('fixture', False),
                       frozen=freeze, per_case_records=len(rows),
                       heldout=paired(rows, 'heldout'),
                       heldout_by_task={task: paired([r for r in rows if r['task']==task], 'heldout')
                                        for task in ('completion', 'exact_answer')},
                       measurement_note='Tiny authored smoke fixture; all conclusions inconclusive; '
                                        'latency includes synchronization; no billed cost inferred')
        write(folder/'summary.json', summary)
    return summary
