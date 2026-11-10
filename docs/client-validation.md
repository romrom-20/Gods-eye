# Independent client validation

Executed locally on 2026-11-09 after reading README.md, docs/security.md, and
docs/roadmap.md. This is a **known-circuit mechanics test**, not discovery of a
novel repair. The four coordinates and restoration recipe were already known.
The original values were inspected before ablation; no edit was selected using
held-out performance.

## Isolation and method

`experiments/validate_client.py` uses `godseye.client.Client` over real HTTP,
not FastAPI TestClient or direct Store operations. It starts its own uvicorn
subprocess with a pre-bound unused loopback socket, sets GODSEYE_DATA_DIR to a
fresh temporary directory, and terminates and waits for the subprocess in
`finally`. It archives evidence and removes its temporary workspace. No
publication, compute purchase, external model service, or remote request was used.

All six tensors were inspected through Client: 600 → 32 → 32 → 6, 20,486
parameters, 815 nonzeros. The original hash was independently reconstructed
from HTTP float32 tensor values. The four W3 left-action values were all 30.
Preview changed exactly four weights without writing files. A stale parent
hash returned 409 without writes. The original and ablated parent remained
unchanged after restoration.

Lineage (checkpoint branches, not Git branches):

- `paper` → `b74f4b9070774e2a`: `W3[0:8:2, 1] = 0`.
- `b74f4b9070774e2a` → `bd33c0e2badf4e38`: `W3[0:8:2, 1] = [30.0, 30.0, 30.0, 30.0]`.
- Original and restored SHA256: `38c50a4f4d7185697176687792834d50970e239f452b764ccd1ec6d8439db128`.
- Ablated SHA256: `658cfaf36d8c280cc2b5eaf76004e7a4b6bf9d5e924fcd6a9e845dde3245b2c7`.

## Evaluation evidence

Every comparison uses eight episodes/model, a 3,000-step episode cap, MinAtar
1.0.15 Breakout, six official actions, softmax sampling, and sticky-action
probability 0.1. Ablation uses seeds 1000–1007; restoration uses the disjoint
range 10000–10007. Delta is candidate minus base score. Standard errors are
sample standard deviation (ddof=1) divided by sqrt(8), independently recomputed
from API episode scores. They are not confidence intervals. Same-seed pairs can
follow different trajectories.

- Ablation versus paper: mean 186.375 → 0; paired delta **−186.375**, SE
  **26.226307**. Capped base/candidate: **7/8, 0/8**. Forward calls: 21114/48.
- Held-out restoration versus ablated parent: mean 0 → 137.875; paired delta
  **+137.875**, SE **30.987577**. Capped base/candidate: **0/8, 5/8**.
  Forward calls: 48/16576.
- Held-out restoration versus paper: mean 137.875 → 137.875; paired delta
  **0**, SE **0**. Capped base/candidate: **5/8, 5/8**. Forward calls:
  16576/16576. Every episode, step count, truncation flag, and recorded trace
  matched exactly. Trace equality for this historical run was checked manually
  against retained artifacts; the original script compared metadata after removing traces.

Individual model mean SEs: paper on seeds 1000–1007 = 26.226307; ablated = 0;
paper and restored on seeds 10000–10007 = 30.987577.

## Rejection and cancellation

Executable statements returned HTTP 400 in both preview and checkpoint
creation, including a valid assignment followed by executable code. A synthetic
file-creation sentinel was never created. Every workspace filename and content
hash remained identical after each rejection; no checkpoint, tensor, workspace
marker, or run was saved. Out-of-bounds assignments and mixed boolean/numeric
literals were also rejected without writes. A 1,280,000-forward request exceeded
the 250,000 admission limit and returned 422 without saving a job.

Cancellation job `a04fca60a254450a` was observed running with **1/24** completed
model episodes (12 episodes/model, 10,000-step cap, at most 240,000 forwards).
It transitioned through `cancelling` to `cancelled` in **5.396 ms** from the cancel
request. It saved no run and had no run ID. The persisted terminal state stayed
unchanged while a subsequent real evaluation succeeded, demonstrating that the
worker was available again. This is observed cooperative cancellation latency,
not a universal deadline guarantee.

## Bug fixed and validation

Before the fix, a real client request
`client.patch('paper', 'b3[0:2] = [True, 2]', 'Synthetic invalid input probe')`
saved a checkpoint with two changed weights. Scalar booleans were already
rejected, but NumPy coerced mixed lists to a numeric dtype before validation.

`godseye/core.py` now rejects boolean literals before conversion, including
nested matrix literals. The focused regression in `tests/test_platform.py`
covers mixed integer/boolean and float/boolean literals, nested lists, augmented
assignments, and a valid statement before an invalid one. It checks both preview
and creation return 400, with unchanged files, checkpoint listing, and parent hash.

The initial suite passed 17 tests; the final suite passed **18 tests**. Ruff on
changed Python files and `git diff --check` passed.

## Changed files and retained evidence

- Modified `godseye/core.py`: five inserted lines reject boolean coercion.
- Modified `tests/test_platform.py`: focused rejection regression.
- Added `experiments/validate_client.py`: independent HTTP acceptance experiment.
- Added `experiments/client-validation-results.json`: complete compact episode
  evidence, settings, checkpoints, job states, and independent statistics.
- Added `docs/client-validation.md`: this report.

All 39 pre-existing edited/untracked files were backed up before writing. A
content-hash comparison confirmed only the two intentionally extended existing
files changed, preserving their prior content. No Git checkout, reset, commit,
or publication occurred. Existing experiment evidence and bundled demo data
were untouched.

Full traces, run/checkpoint/job artifacts, and the server log remain locally at
`/private/tmp/godseye-client-validation-20261109/` (temporary storage, not committed).
The compact repository JSON retains the reported results. Our server PID 47523
on `127.0.0.1:55002` exited; its log records completed application shutdown.
The temporary experiment workspace was removed.

## Automated replay check and CI follow-up

The acceptance script now checks equality of the complete nonempty **recorded**
replay and the complete base/candidate evaluation objects before removing traces
from compact JSON. The restoration-versus-paper run records
`recorded_replay_equality_verified: true`; other comparisons record `false`
because equality was not requested. The simulator records a replay for the first
episode of each model, so this flag does not claim full trajectories for all eight
episodes. All eight episodes' metadata are still compared.

Three regressions cover equal traces, empty traces, and different actions despite
identical score/episode metadata. CI runs the real HTTP acceptance experiment on
Python 3.9 and 3.12, allocates a unique parent directory with a nonexistent `run`
child, and uploads that directory (including `server.log`) even on failure.
Experiment code is included in lint checks.

A fresh local follow-up run on 2026-11-09 passed all acceptance checks, with the
same fixed-seed scores above and automated replay equality verified. Its separate
evidence is at `/private/tmp/godseye-client-evidence.oDzmuA/run/`. At the time of
this check, the repository suite passed **21 tests** and Ruff passed. The prior
run IDs, cancellation timing, and committed JSON above remain historical evidence
and have not been replaced by this follow-up. CI configuration is added; a hosted
CI run has not been observed here.

## Unresolved limits

- Eight seeds/set, one known circuit, one environment, and one machine do not
  establish novel repair or broad generalization. There was no concealed
  corruption, repair search, or enforced agent probe-budget experiment.
- Heavy truncation means these are capped-horizon returns, not uncapped episode
  performance. The upstream 1,000-episode / 10,000-step benchmark was not replicated.
- The restoration comparisons reuse the same held-out seeds and policy; they
  are linked checks, not independent replications.
- Cancellation was tested before result publication. Late cancellation, worker
  isolation, distributed execution, transactional publication, multi-tenancy,
  and billing remain outside this acceptance experiment. The documented local
  security limits still apply.
- This was API testing, not visual browser or accessibility QA. Optional-token
  and other HTTP boundary checks were exercised by the repository suite.

## Exact reproduction commands

From the repository root, using the existing local environment:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m ruff check godseye/core.py tests/test_platform.py experiments/validate_client.py
git diff --check
.venv/bin/python -m experiments.validate_client --output /tmp/godseye-client-validation-20261109
```

The last command is the exact acceptance command used here. Its output directory
now exists and is protected against overwrite. To repeat safely with a new path:

```sh
validation_output="$(mktemp -d /tmp/godseye-client-evidence.XXXXXX)/run"
.venv/bin/python -m experiments.validate_client --output "$validation_output"
```

The script chooses the loopback port, sets its own temporary GODSEYE_DATA_DIR,
performs the Client checks, archives evidence, stops its own server even on
failure, and deletes the temporary workspace. IDs, timing, and ports vary;
fixed-seed scores should match with the recorded dependency/runtime versions.

## Per-episode results

Each row gives score / steps. “Capped” means truncated at 3,000 steps;
all other rows terminated normally. Full numeric records are in the JSON.

### ablation

Run `9736cafdb9ca4ddc`.

- Seed 1000: base 176 / 3000 (capped); candidate 0 / 6 (terminal); delta -176.
- Seed 1001: base 236 / 3000 (capped); candidate 0 / 6 (terminal); delta -236.
- Seed 1002: base 225 / 3000 (capped); candidate 0 / 6 (terminal); delta -225.
- Seed 1003: base 10 / 114 (terminal); candidate 0 / 6 (terminal); delta -10.
- Seed 1004: base 207 / 3000 (capped); candidate 0 / 6 (terminal); delta -207.
- Seed 1005: base 236 / 3000 (capped); candidate 0 / 6 (terminal); delta -236.
- Seed 1006: base 206 / 3000 (capped); candidate 0 / 6 (terminal); delta -206.
- Seed 1007: base 195 / 3000 (capped); candidate 0 / 6 (terminal); delta -195.

### restoration-held-out-parent

Run `517098adeb054b5c`.

- Seed 10000: base 0 / 6 (terminal); candidate 7 / 80 (terminal); delta +7.
- Seed 10001: base 0 / 6 (terminal); candidate 231 / 3000 (capped); delta +231.
- Seed 10002: base 0 / 6 (terminal); candidate 198 / 3000 (capped); delta +198.
- Seed 10003: base 0 / 6 (terminal); candidate 178 / 3000 (capped); delta +178.
- Seed 10004: base 0 / 6 (terminal); candidate 37 / 440 (terminal); delta +37.
- Seed 10005: base 0 / 6 (terminal); candidate 207 / 3000 (capped); delta +207.
- Seed 10006: base 0 / 6 (terminal); candidate 62 / 1056 (terminal); delta +62.
- Seed 10007: base 0 / 6 (terminal); candidate 183 / 3000 (capped); delta +183.

### restoration-held-out-paper

Run `2d69c48c143e48ca`.

- Seed 10000: base 7 / 80 (terminal); candidate 7 / 80 (terminal); delta +0.
- Seed 10001: base 231 / 3000 (capped); candidate 231 / 3000 (capped); delta +0.
- Seed 10002: base 198 / 3000 (capped); candidate 198 / 3000 (capped); delta +0.
- Seed 10003: base 178 / 3000 (capped); candidate 178 / 3000 (capped); delta +0.
- Seed 10004: base 37 / 440 (terminal); candidate 37 / 440 (terminal); delta +0.
- Seed 10005: base 207 / 3000 (capped); candidate 207 / 3000 (capped); delta +0.
- Seed 10006: base 62 / 1056 (terminal); candidate 62 / 1056 (terminal); delta +0.
- Seed 10007: base 183 / 3000 (capped); candidate 183 / 3000 (capped); delta +0.

## Follow-up: automated replay check and CI

On 2026-11-10 the acceptance helper was corrected to assert nonempty full
recorded-trace equality before removing traces from compact output. The earlier
script's final equality assertion compared only the compacted model records.
The new `recorded_replay_equality_verified` flag records this explicit check;
regressions verify that different actions fail despite matching episode scores.
The real HTTP acceptance experiment was rerun successfully after integration.

CI now runs this experiment for both supported test Python versions and uploads
its evidence and server log, including on failure when the directory exists.
It also runs the deterministic CPU repair-benchmark demonstration. These CI
changes were validated locally; no hosted CI execution is claimed here.
