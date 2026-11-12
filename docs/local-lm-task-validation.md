# Bounded cached-model JSON task validation

Pre-execution plan recorded 2026-11-13. This is one separately authorized local CPU
run of the fixed public JSON task, using existing verified cached weights. It is
not the earlier arithmetic smoke and does not authorize retries or a larger search.
The prompt baseline scope was clarified before execution in the fixed TaskSpec:
`baselines.prompt.scope = json_targets_only`. JSON targets get the prefix; exact
text controls keep their original prompt. The TaskSpec hash binds that choice;
the dataset/version, metrics/thresholds and two candidate edits are unchanged.

Execution command (after deterministic focused tests pass):

```sh
/tmp/godseye-lm-local-venv/bin/python -m unittest discover -s tests -p 'test_lm_local*.py' -v
python3 -S -m experiments.local_lm_task
/tmp/godseye-lm-local-venv/bin/python -m experiments.local_lm_task --execute \
  --cache /tmp/godseye-lm-local-real-20261113/weights \
  --output /tmp/godseye-lm-json-task-20261113
```

The supervisor permits at most 1800 seconds including hash verification, loading,
preflight, development, freeze, heldout and any selected-delta fresh-process check.
One resident CPU model, two intra-op threads and one inter-op thread; no downloads,
GPU/cloud/provider calls, credentials, retries or server changes. All 140 complete
split/variant prompts are tokenized before generation; no truncation is allowed.
There are 70 planned development calls; heldout has 42 calls if unchanged is kept,
or 56 if a weight candidate is selected. Overall ceiling 126 calls, 28 per variant,
512 input tokens, 96 new tokens, 60 cooperative seconds per call, 608 total context.
Native blocking kernels require the outer owned-process deadline; token checks
alone cannot hard-bound them. The old smoke profile still has eight native attempts.

The durable append-only ordered journal records a reservation and fsync before
each call, then the returned metadata or failure with unknown usage retained.
Every event is hash chained. An interrupted reservation remains evidence of an
attempt with unknown output/usage, never an automatic resume request. Incomplete
or invalid development forbids heldout. Freeze is written atomically, fsynced
with its directory, read back and journaled before any heldout call. Heldout
cannot reselect candidates. Every candidate starts from the original projection
and rolls back in `finally`; exact hashes verify all boundaries. If a candidate
is selected, its numeric delta is reloaded and checked, then checked again with
a freshly loaded pinned model in a sequential child without extra generations.
No selected artifact is manufactured when unchanged wins.

Synthetic tests use injected runtimes/editors/processes. They cover mismatched
policy before inference, durable admission, interrupted journals, failed-call
accounting, freeze persistence failure, frozen heldout selection, timeout/Ctrl-C
kill-and-wait cleanup, exact baseline settings, cap classification, unknown usage,
and rollback on errors. These tests are not pretrained quality evidence.

The CLI is a trusted local operator tool, not a service authentication boundary,
hosted multiuser isolation or browser support. The fixed public authored fixture
has 10 JSON targets and four simple text controls per split. Its statistical
intervals are descriptive; no broad quality, contamination-free generalization,
inference speedup or cost savings follow from this run. Process peak RSS includes
loading and is not current RSS or model allocator memory.

## First and only pretrained run: incomplete, not evaluated

The focused local tests passed 22/22 and the existing task-contract/scorer tests
passed 20/20 before inference. They are synthetic checks. The real command above
ran once on macOS arm64, Python 3.12.14, the isolated pinned environment and the
previously verified Qwen checkpoint. No dependencies or weights were downloaded.
TaskSpec SHA256:
`3a49a9cd1b743ba8935582e1e22673bf402d80e68a6136e559dd75fdf73aa08d`.
The public dataset remains version `1.0.0`, SHA256
`8fed6ab63c06cb5fe22068695340e4412d2fa2dae3f3d6cd3871017e53819582`.

Preflight tokenized all 140 full split/variant prompts without generation:
maximum 161 rendered input tokens and 597 prompt characters. The actual run
reserved and completed 70 native calls (14 per development variant), with 69 EOS
completions and one token-capped response. There were no inference exceptions,
unknown usages, interrupted reservations or retries. Total measured usage was
6,515 input tokens and 1,154 generated tokens, including EOS. The supervisor took
40.74 seconds including verification/loading/hashing/journaling and returned
nonzero intentionally because the task was incomplete. This was a budget-limited
model outcome, not a failing implementation test.

Development counts, each out of 10 JSON targets and four text controls:

- Unchanged: schema 3/10, semantic 1/10, controls 4/4; all 14 complete.
- Prompt prefix: schema 1/10, semantic 0/10, controls 4/4; all 14 complete.
- Repetition penalty 1.1: schema 3/10, semantic 1/10, controls 4/4;
  13 complete, `dev-inventory` reached the 96-token cap.
- Column 0 × 0: schema 2/10, semantic 0/10, controls 4/4; all 14 complete.
- Column 1 × 0.5: schema 2/10, semantic 0/10, controls 4/4; all 14 complete.

The capped partial output remains inspectable and scored, but its arm has no
complete-arm rate and cannot confer selection eligibility. The implementation
correctly stopped before freeze/heldout: zero heldout calls, no persisted freeze,
no selected weight variant, no selected delta export and no fresh-model selected
reload to claim. Unused numeric candidate artifacts remain labeled by variant.
The result is `status=incomplete`, `verdict=not_evaluated`; development counts do
not substitute for heldout quality evidence. Neither hand edit nor the prompt
baseline improved these observed counts. No candidate was tuned or run again.

All five variants ended at the exact original projection hash:
`cdba20f7429dd67092a8861e2d3d51e28318ecd4a6b007e7f417f1c5aeac3ee5`.
Column 0 candidate hash:
`a5287989d14914fe1aba521739d1c1cc96decbddfa659c8d3f37b2ded1e78577`.
Column 1 candidate hash:
`3f4a6e80e857d6a45d326c8acaffb4b8c637f523bd3db70be0b9ee7815fe65cc`.
The journal contains 155 valid ordered hash-chained events, with 70 durable
reservations and 70 result records. All candidate application/reload and rollback
checks passed. Peak observed process RSS was 2,733,539,328 bytes (about 2.55 GiB).
Generation latency totals were 7.29 seconds unchanged, 7.15 prompt, 8.93 decoding,
7.17 column 0 and 7.19 column 1; per-call ranges and exact values are in the report.
These sequential, warm-up-sensitive timings do not establish a speedup.
Transformers emitted the retained eager/sliding-window warning; the verified
model config sets `use_sliding_window=false`.

The compact redacted artifact is
`experiments/local_lm_task_validation.json`, including every attempted completion,
status, token count, latency, per-case score, source hashes and journal identity.
Raw local evidence remains at `/tmp/godseye-lm-json-task-20261113/`: supervisor
manifest/log, canonical spec/model/dataset manifest, full preflight prompts,
append-only journal, two unused candidate deltas and detailed report. The journal
is read-only after the run; an existing output directory is rejected and there is
no automatic resume. Do not rerun/tune this fixture to erase the first capped
result. Browser review/start/status/cancel, a local control service and hosted
security boundaries remain separate work, not implemented by this CLI slice.

## Review correction: explicit runtime output required

A follow-up review found that missing or non-string runtime `output` could be
silently converted to an empty successful response. `to_record` now rejects a
non-dict payload or absent/non-string output with a useful `ValueError`; the
runner retains that raw payload, records a failed attempt with unknown usage and
forbids heldout when development is incomplete. An explicitly returned empty
string remains actual output and is scored normally. All 13 focused task-runner
tests pass, including direct rejection, explicit empty output and malformed raw
payload retention through the runner.

Read-only revalidation of the first-run journal confirmed that all 70 actual
responses contain explicit string output, and the corrected converter reproduces
every historical record exactly. The journal SHA256 remains
`d547e3fe7dd238662e188c1d9b1d15022ba7f06788946898f2b925321e35d924`,
matching the committed validation artifact. No historical artifact was rewritten;
its source hashes describe the code used for that run. No inference was rerun,
no candidate was tuned and the incomplete/not-evaluated verdict is unchanged.
