"""Fixed public model, transparent fixture and resource plan (stdlib only)."""
import hashlib
import json
from pathlib import Path

MODEL = 'Qwen/Qwen3.5-0.8B'
REVISION = '2fc06364715b967f1860aea9cf38778875588b17'
VERSIONS = {'torch': '2.15.0', 'transformers': '5.22.2', 'safetensors': '0.8.0',
            'modal': '1.6.4', 'numpy': '2.2.6', 'accelerate': '1.12.0'}
PARAMETER = 'model.layers.0.mlp.down_proj.weight'
ARMS = ('unchanged', 'prompt', 'decoding', 'weight')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def cases(split):
    """Authored smoke fixture, CC0; no external benchmark or training claim."""
    words = {'train': ('amber', 'birch'), 'dev': ('cobalt', 'dahlia'),
             'heldout': ('elm', 'fuchsia')}[split]
    rows = []
    for word in words:
        rows.append(dict(id=f'{split}-repeat-{word}', task='completion',
                         prompt=f'Complete with exactly the next word: {word} {word} {word}',
                         answer=word))
    numbers = {'train': (1, 2), 'dev': (3, 4), 'heldout': (5, 6)}[split]
    for n in numbers:
        rows.append(dict(id=f'{split}-sum-{n}', task='exact_answer',
                         prompt=f'What is {n} + {n}? Reply with only the number.', answer=str(n+n)))
    return rows


def plan(profile='pilot'):
    if profile not in ('smoke', 'pilot'):
        raise ValueError('fixed profile required')
    seconds = 120 if profile == 'smoke' else 480
    return dict(schema_version=1, model=MODEL, revision=REVISION, runtime=VERSIONS,
                harness_digest=digest({name: hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()
                                       for name in ('spec.py','delta.py','runtime.py','evaluate.py')}),
                tokenizer_revision=REVISION,
                generation=dict(do_sample=False, num_beams=1, repetition_penalty=1.0,
                                decoding_arm_repetition_penalty=1.15, enable_thinking=False),
                prompt_baseline_prefix='Be concise. Return only the requested answer, no explanation.\n',
                profile=profile, seed=1729, dtype='float32', device='cuda',
                max_prompt_chars=512, max_prompt_tokens=128,
                max_new_tokens=8 if profile == 'smoke' else 24,
                cases_per_split=2 if profile == 'smoke' else 4,
                max_generations=18 if profile == 'smoke' else 36,
                evaluation_seconds=seconds, invocation_timeout=600, startup_timeout=180,
                arms=list(ARMS), candidates=[dict(column=0, scale=0.0),
                                             dict(column=1, scale=0.5)],
                parameter=PARAMETER, data_digest=digest({s: cases(s) for s in
                                                        ('train', 'dev', 'heldout')}),
                gpu='L4', cpu_physical_cores=2, memory_gib=16, max_containers=1,
                retries=0, pricing_date='2026-11-12',
                rates_usd_second=dict(gpu=0.000222, cpu_core=0.0000131, ram_gib=0.00000222),
                estimated_780s_compute_usd=round(780*(0.000222+2*0.0000131+16*0.00000222), 6),
                estimate_caveat='Not billed cost or hard cap; excludes image build, idle, storage, '
                                'network, tax; download/model load consume invocation time; '
                                'credits eligibility and remaining balance unknown',
                command=f'python -m experiments.modal_lm_pilot --profile {profile} '
                        '--output lm-result-'+profile+' --execute')


def cohort(split, config):
    rows = cases(split)
    return rows if config['cases_per_split'] == 4 else [rows[0], rows[2]]
