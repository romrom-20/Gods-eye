# Local language-model task contract v1

Implemented here: a pure standard-library preview, fixed public task pack,
strict scorer, development selector and supplied-output evidence assembler.
There is **no browser, service or runner integration in this slice**. This is
independent of the Qwen3.5 CUDA smoke pilot in `language-model-pilot.md` and the
Breakout-only `experiment-contract.md`. Neither existing contract changes.

The first supported goal is **correct JSON matching a specified bounded schema,
without markdown or preamble**. Success on formatting alone is insufficient:
semantic exact answers and unrelated simple text tasks must not regress.
Arbitrary natural-language weight editing remains unsupported.

## Preview and frozen identity

`godseye.lm.task_contract.preview(text, revision=..., model_id=...)` recognizes
only these phrases after case folding, whitespace normalization and removing one
terminal period:

- `Improve JSON schema adherence`
- `Return correct JSON matching the specified schema`
- `Improve JSON output without markdown or preamble`

All map to the same reviewable recipe. Text mentioning JSON/schema/format but
outside this list returns `clarification_required`, with an example supported
request. Other text returns `unsupported`. Both return null spec/hash.
`Make JSON better` needs clarification; `make it smarter`, `edit Qwen weights`
and `download https://example.org/model` are unsupported. Appending commands to
a recognized phrase makes it unrecognized. Requests are inert strings: no code,
path resolution, downloads, network calls, experiment creation or charges occur.
Raw requests should not be logged: users can paste secrets into them.

The only editable target ID is `Qwen/Qwen2.5-0.5B-Instruct`. A revision is
mandatory: exactly 40 lowercase hexadecimal commit characters, also used for
the tokenizer. Floating names such as `main`/`latest` fail. Offline validation
checks the immutable revision *form*, not that the commit exists or its license
and files are approved. At admission the trusted runtime registry must verify
the supplied commit, tokenizer/config/tensor manifests, safe serialization,
architecture and content hashes against its actual cached model. A made-up SHA
is not proof of an available model; the tests use one explicitly synthetic SHA.
There is no implicit lookup, download, model substitution or revision fallback.

`TaskSpec(canonical(preview_result['spec']))` validates the entire fixed recipe,
stores canonical JSON immutably and returns independent copies via `to_dict()`.
Its `.sha256` covers the schema version, exact model/tokenizer revision, dataset
identity/version/content digest, metrics, selection and split policy, decoding,
all permitted edits, baselines and finite budgets. Canonical serialization uses
sorted keys, compact separators, ASCII escaping and rejects NaN. Unknown fields
and modifications to the v1 recipe fail; changing limits or rules requires a new
contract version rather than silently changing an already reviewed plan. Hashes
provide identity/integrity, never authorization or proof of real execution.

The operation recipe permits only two alternative single-column scaling edits
on `model.layers.0.mlp.down_proj.weight`: column 0 × 0, or column 1 × 0.5.
Each is applied independently to the original, never composed. This is a bounded
engineering search, not a claim that either column controls JSON behavior.
The execution owner must check actual tensor shape, finite values, original
content preconditions and permitted operation, and verify reload and exact
rollback. Planning and scoring do not implement tensor mutation or verify a
weight artifact. The supplied evidence cannot establish usable model export.

## Fixture, schemas and measurements

`task_suite.py` contains the authored **CC0-1.0** pack as Python data, so wheel
installation needs no new package-data configuration. Dataset identity is
`godseye-authored-json`, version `1.0.0`, SHA-256
`8fed6ab63c06cb5fe22068695340e4412d2fa2dae3f3d6cd3871017e53819582`.
The digest covers prompts, schemas, reference answers, split IDs and families.
Intentional fixture changes need a version bump and hash/test review.

Each split has six extraction cases, four rule-based classifications and four
simple text regressions (28 cases total). They exercise nested objects,
integers/negative integers/zero, booleans, exact strings, escaping/quoting,
distractors, negation, threshold boundaries and conjunction/disjunction rules.
Development and heldout use disjoint named entities and authored template
families. Regression tasks use distinct basic arithmetic/copy/word controls.
These are modest checks, not broad preservation of unrelated model capabilities.
There is no train split, training claim or duplicated-case count inflation.

Schemas use a deliberately closed dialect: required objects with 1–8 named
properties and no extra fields; strings bounded at 256 characters with optional
1–8-value enums; bounded integers within ±1,000,000; booleans; nesting at most
three levels. All fields are required. Arrays, nullable types, arbitrary regexes,
references, executable validators and external schemas/datasets are unsupported.
The evaluator uses the fixed schemas in this pack. `validate_schema` documents
the dialect; this is not full JSON Schema support or a user-schema upload API.

`score_output(case, output)` rejects markdown, preamble, trailing text, duplicate
keys (including nested keys), NaN, infinities and overflowing numeric exponents.
It accepts surrounding JSON whitespace and arbitrary object-key order. JSON
output is capped at 16 KiB and nesting at 12; the case schema is stricter.
`schema_ok` measures conformance. `correct` compares canonical typed JSON to the
reference, so a well-formed wrong answer is schema-valid but incorrect; booleans
and floating-point values do not pass integer fields. Regression answers are
whitespace-trimmed exact text and have null `schema_ok`.

Reports include attempted/expected/paired sample counts, success counts, rates,
Wilson 95% intervals for complete-arm schema/semantic/control scores, paired
schema differences and a bounded Hoeffding 95% difference interval. Missing,
failed, cancelled, duplicate or incomplete arms have no complete-arm rate and
cannot produce improvement. Partial output scores remain inspectable, even for
failed attempts, and never confer eligibility. Unknown usage stays unknown.

These public authored fixtures are **not private, comprehensive,
contamination-free, or proof of generalization**. Heldout is publicly readable;
a pure function cannot stop an operator from inspecting it. Statistical intervals
are descriptive under independent-case assumptions; authored correlated cases
and model/fixture selection violate population-sampling assumptions. Small
samples produce wide bounds; do not market these as calibrated confidence in
real-world behavior. Even `improved_on_public_fixture` is a narrow fixture result.

## Execution adapter: exact supplied-output interface

No dependency on the independent local runtime is introduced. A trusted adapter
may map its generation result to this exact data record (all fields required,
unknown fields rejected):

```python
{
    'attempt_id': 'dev-weight-0-0',  # opaque [A-Za-z0-9_-]{1,64}, unique per job
    'spec_sha256': spec.sha256,
    'case_id': 'dev-badge',
    'split': 'dev',                 # dev | heldout
    'variant': 'weight-0',          # unchanged | prompt | decoding | weight-0 | weight-1
    'status': 'complete',           # complete | failed | budget_limited | cancelled | incomplete
    'output': '{"owner":"Mira","badge":17}',
    'input_tokens': 100,
    'output_tokens': 12,
    'elapsed_seconds': 0.3,
}
```

Counts must be nonnegative integers, never booleans; elapsed seconds finite and
nonnegative. Failed attempts can carry null usage; complete attempts require all
three measured values. `complete` must mean generation finished normally (EOS),
with no truncation, deadline, cancellation or missing usage. A token cap or
partial response is `budget_limited`, even if the partial text parses. Do not map
the older CUDA pilot's permissive `token_cap` completion policy into this one.
The adapter, not this data-only evaluator, must attest to actual generation,
revision identity, prompt/decoding settings, tokenization, completion cause and
mutation verification. No user-supplied `score` is accepted.

The spec permits greedy decoding, seed 1729, one beam, 96 output tokens,
512 input tokens and 60 seconds per attempt; one concurrent execution; no retries;
two edit candidates; 28 attempts per variant and 126 overall; an outer worker
limit of 1800 seconds. A global deadline can stop before these maxima are
reached. These are ceilings, not completion/performance guarantees. Each admitted
arm gets the same per-case token/time and split counts. The two weight candidates
consume separate dev allowances; only the selected one receives heldout calls.
A fixed prompt-prefix baseline and fixed repetition-penalty decoding baseline
are evaluated alongside unchanged and weight arms. Compare these alternatives
with identical cases/resources before attributing value to weight changes.
A fixture gain versus unchanged alone does not establish superiority to the
prompt/decoding alternatives; their comparisons remain visible in the report.

The control service must journal **every attempted record before aggregation**,
including failures, cancellations and budget stops. Supply ordered records;
no silently dropping failed retries or keeping only the best generation.
Unexpected envelope fields/identities, malformed JSON transport or invalid usage
raise `ValueError`: preserve that original adapter payload as rejected evidence
at the trusted journal boundary. Valid attempted records, including duplicate
case attempts, are returned unchanged in `report['records']`. Duplicates, unknown
usage, excess tokens/time/attempts and unexpected heldout variants block completion.
Summed generation elapsed time is a lower-bound accounting check, not a way to
enforce wall time: startup, model load, hashing and idle time also consume the
external worker deadline. This module has no journal, scheduler or clock policing.

1. Run all five variants over `cases('dev')` (70 records).
2. `freeze = freeze_selection(spec, dev_records)` recomputes scores. It rejects
   heldout inputs, requires all dev arms complete and valid accounting, and
   selects a weight candidate only for strictly higher schema adherence with no
   per-case semantic or regression loss. Rank by schema rate, semantic rate,
   then variant ID. A tie with unchanged retains unchanged.
3. Persist the freeze atomically before any heldout execution. It binds spec,
   ordered development evidence digest, selected variant and heldout allowlist.
   The function itself cannot prove durability or real-time ordering.
4. Evaluate `freeze['heldout_variants']` once over `cases('heldout')`: unchanged,
   prompt, decoding and the selected weight variant, if any. Do not relabel
   unchanged as a weight edit when nothing was selected.
5. `evaluate(spec, freeze, dev_records + heldout_records)` recomputes the freeze,
   rejects changed dev evidence or dev records after heldout, and assembles the
   comparison. Never reselection/retry/tune after viewing heldout scores; use a
   new genuinely independent suite/version to support further quality claims.

For a complete experiment, nonpositive schema gain or any per-case semantic or
control regression yields `no_improvement`. A positive observed gain whose
paired lower bound is not above the predeclared 0.1 threshold is `inconclusive`.
Only gain beyond that bound and zero regressions yields
`improved_on_public_fixture`. Incomplete evidence yields `not_evaluated`, even
when a complete subset looks favorable. This is an evaluation verdict, distinct
from whether execution completed. There is no manufactured winning edit.

## Independent runtime compatibility (not connected)

The coordinator supplied runtime commit `9a48109` and its
`docs/local-language-model.md` evidence. That slice pins revision
`7ae557604adf67be50417f59c2c2f167def9a775` and weight SHA-256
`fdf756fa7fcbe7404d5c60e26bff1a0c8b8aa1f72ced49e7dd0210fe288fb7fe`.
Those are supplied runtime evidence, not independently downloaded or reverified
by this task-contract slice. Its real arithmetic-only smoke returned the same
answer before/after the fixed edit; it does not establish JSON-task quality.

Current `Runtime.generate(prompt, max_new_tokens=32, seconds=20)` has hard
512-character/128-input-token/160-context limits, 32 output tokens, at most
30 seconds and **eight generation attempts process-wide**. This suite needs
70 dev attempts before selection and up to 56 heldout attempts; its longest raw
prompts are 528 dev and 537 heldout characters, even before the prompt baseline.
Its 96-output-token/512-input-token/60-second task ceilings also exceed that
smoke interface. The runtime fixes repetition penalty at 1.0 and cannot currently
execute the prescribed 1.1 decoding baseline. Do not shrink this meaningful
fixture to eight calls, truncate prompts, silently change decoding, reset process
counters, or pretend smoke outputs constitute suite completion.

A later separately authorized runtime extension must explicitly advertise/enforce
this task's capabilities and total budget under an outer deadline. The adapter
maps `generated_tokens` to `output_tokens`, `latency_seconds` to
`elapsed_seconds`, and `termination=eos` with `deadline_exceeded=False` to
`complete`; `token_cap`, `walltime` or deadline overrun map to `budget_limited`.
Missing/inconsistent metadata must fail closed. The task spec's model revision
must match the verified runtime identity before any call. None of that adapter,
capability extension or actual JSON-task execution is implemented here.

## Reproducible supplied-output example (synthetic)

This exercises the public API without importing a runner or optional packages.
`revision` below is intentionally synthetic, not an approved downloadable model.

```python
from godseye.lm.task_contract import TaskSpec, canonical, preview
from godseye.lm.task_suite import cases, VARIANTS, freeze_selection, evaluate

spec = TaskSpec(canonical(preview('Improve JSON schema adherence',
                                revision='a' * 40)['spec']))

def outputs(split, variants):
    rows = []
    for variant in variants:
        for i, case in enumerate(cases(split)):
            text = case['answer'] if case['task'] == 'regression' else canonical(case['answer'])
            if variant == 'unchanged' and case['task'] != 'regression':
                if split == 'dev' or i == 0:
                    text = 'Answer: ' + text
            rows.append(dict(attempt_id=f'{split}-{variant}-{i}',
                             spec_sha256=spec.sha256, case_id=case['id'], split=split,
                             variant=variant, status='complete', output=text,
                             input_tokens=100, output_tokens=20, elapsed_seconds=0.1))
    return rows

dev = outputs('dev', VARIANTS)
freeze = freeze_selection(spec, dev)  # weight-0 by deterministic dev tie break
heldout = outputs('heldout', freeze['heldout_variants'])
assert evaluate(spec, freeze, dev + heldout)['verdict'] == 'inconclusive'
# Ten paired targets, observed +0.1 schema gain; wide bounded interval crosses zero.
heldout[-1]['output'] = 'wrong'       # selected arm's unrelated control regresses
assert evaluate(spec, freeze, dev + heldout)['verdict'] == 'no_improvement'
heldout[-1]['status'] = 'budget_limited'
report = evaluate(spec, freeze, dev + heldout)
assert report['verdict'] == 'not_evaluated'
assert report['attempt_count'] == 126  # every attempt preserved
```

Validation: `python3 -m unittest discover -s tests -p 'test_lm_task_*.py' -v`.
The focused suite covers strict parsing, typed schemas, stable identities/splits,
conservative planning, selection/freeze guards, uncertainty, regressions,
resource accounting and retained failures. All outputs are synthetic; no real
Qwen quality, model compatibility, weight reload, RAM or latency was measured.
Remaining integration: trusted admission/journal/freeze ordering, runtime-to-record
mapping, real cached-model identity, verified delta artifacts/rollback, resource
enforcement, browser review/start/status/cancel and user-authorized real execution.

## Pre-execution clarification: prompt baseline scope (2026-11-13)

Before the first real task run, the fixed prompt recipe now includes
`scope: json_targets_only`. Its prefix applies only to extraction/classification
JSON targets; exact-text regression controls receive their original prompts.
The TaskSpec hash binds this scope. Dataset version/content, metrics, thresholds,
edit candidates and all resource ceilings are unchanged. No earlier real task
runs exist under the ambiguous recipe.
