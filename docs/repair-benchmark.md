# Repair benchmark: local agent protocol

This CPU-only harness presents four opaque cases: one unchanged control and
three fault families (output sign inversion, action-channel ablation, output
bias shift). The agent reads candidate tensors, branches numeric patches, probes
on development episodes, and freezes one candidate per case. Only after every
selection is frozen can the administrator reveal held-out results and labels.

This is a protocol boundary, not a security boundary. The same OS user can read
`private-state.json`, the bundled reference model, or this implementation and
bypass the protocol. Genuine blinded experiments require a separate evaluator
account/environment and restricted agent access. The deterministic demonstration
is not evidence of autonomous discovery. This implementation uses POSIX file
locks and supports macOS/Linux.

## Run a complete example

From the repo with dependencies installed:

```sh
.venv/bin/python -m experiments.benchmark_demo --output /tmp/repair-demo.json
```

The output must not exist. This compares an unchanged participant with a simple
heuristic that zeros output biases, selecting it only when development score
improves. Both get the same generated cases and evaluation seeds. The output
retains probes, selected candidates, failures to improve, controls, and final
scores. No external model, API key, GPU, or web server is needed.

## Give a coding agent a suite

```sh
.venv/bin/python -m godseye.benchmark_cli --workspace /tmp/repair-suite create
.venv/bin/python -m godseye.benchmark_cli --workspace /tmp/repair-suite list
```

Copy a case `id` and its `root_id` from the JSON. Replace CASE and ROOT below:

```sh
.venv/bin/python -m godseye.benchmark_cli --workspace /tmp/repair-suite inspect CASE W3
.venv/bin/python -m godseye.benchmark_cli --workspace /tmp/repair-suite probe CASE ROOT
```

Write numeric assignments into an edits file, then branch:

```sh
.venv/bin/python -m godseye.benchmark_cli --workspace /tmp/repair-suite patch CASE --parent ROOT --file candidate.edits --hypothesis 'Explain the intended behavioral change'
```

The returned `id` is the candidate. Use `inspect CASE W3 --candidate CANDIDATE`
or `probe CASE CANDIDATE`. Candidate IDs cannot be used across cases. Original
weights remain intact, and each candidate records its patch, hypothesis, parent,
diff, and hashes. A case accepts at most 100 edited candidates.

Finish each case, even if the best candidate is the unchanged root:

```sh
.venv/bin/python -m godseye.benchmark_cli --workspace /tmp/repair-suite finalize CASE CANDIDATE
.venv/bin/python -m godseye.benchmark_cli --workspace /tmp/repair-suite report
```

`finalize` freezes selection before executing held-out work and returns no
scores. Further edits or probes for that case are rejected, including after
failure. `report` refuses until every case is frozen. Its final records compare
the selection with both the corrupted root and unmodified reference on matching
held-out seeds; they include per-episode scores/steps, truncations, forward
counts, paired differences, and standard errors. A failure/interruption remains
visible and cannot be silently retried for a new selection. These tiny capped
runs are exploratory; a positive difference is not statistical proof of repair.

After reinstalling `pip install -e '.[dev]'`, `godseye-benchmark` is an equivalent
console command. This benchmark is separate from the website's existing API;
there are no new HTTP benchmark routes yet.

## Budgets and recovery

`create` accepts `--seed`, `--probes`, `--forward-budget`, `--episodes`, and
`--max-steps`. Defaults are four probes, 8,000 reserved development forward calls,
two episodes, and a 200-step cap per case. Each probe reserves the worst case
`episodes × max_steps` before execution. Failures and interruptions consume the
reservation; unused steps are not refunded. Probe and forward limits both apply.

Held-out evaluation has a separate fixed allowance of
`3 × episodes × max_steps` per case for reference, corrupted, and selected
models. It does not consume or extend the development allowance. Public case
metadata exposes these limits. The final report distinguishes reserved and
actual usage. POSIX locking serializes access across processes, and atomic state
writes persist the reservation. Incomplete reserved work becomes `interrupted`
on the next operation, preserving its charge and frozen selection.

Do not grant a repair agent direct private-file access when assessing blindness.
Do not expose the administrator report while any selection remains open. Do not
claim the deterministic baseline knows how to repair arbitrary networks.

## Continue from here

Run actual external-agent participants, expand fault types and instances,
separate evaluator permissions, and increase held-out sample counts. Compare
against unchanged and simple heuristic baselines, preserving regressions and
failed attempts. Slice/top-k tensor tools, checkpoint lineage UI, and benchmark
HTTP endpoints remain future work.

## Isolated evaluator and actual model adapter

The legacy commands above remain a local protocol. A separate container service,
restricted coding-agent adapter, and experiment-wide freeze gate are now available:
see [isolated-evaluator.md](isolated-evaluator.md). Its tests and baseline-only
observations are documented in [evaluator-pilot-report.md](evaluator-pilot-report.md).
Container and real-agent execution remain unverified in the implementation
workspace because Docker/Podman and the adapter API credential were unavailable.
