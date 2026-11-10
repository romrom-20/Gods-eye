# Tasks for another coding agent

Open this repository in an agent that can read files and run shell commands.
The weight-space engine runs locally on CPU. The coding agent itself still needs
its own existing subscription, credentials, or local model; God's Eye does not
supply an LLM. A cloud agent must clone the repository and start its own server:
your laptop's `localhost` is not reachable from its environment.

## Verify the current product

Copy this task into the agent:

> Read README.md, docs/security.md, and docs/roadmap.md. Independently test the
> product through godseye.client.Client, using a temporary GODSEYE_DATA_DIR and
> a server on an unused loopback port. Preserve all existing repository edits.
> Run the test suite. Inspect the paper checkpoint, preview and ablate the four
> left-action connections, evaluate against the parent, restore on a new branch,
> and verify the restored tensor hash equals the original. Evaluate restoration
> on seeds disjoint from the ablation test; report per-episode results, caps,
> paired mean differences, and standard errors. Verify executable patches are
> rejected without saving a checkpoint, and that cancellation stops a live job.
> Distinguish a known-circuit mechanics test from discovery of a novel repair.
> Fix reproducible bugs with focused regression tests. Report evidence, changed
> files, unresolved limits, and exact reproduction commands. Clean up your own
> server. Do not publish, purchase compute, or access external model services.

Setup:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m unittest discover -s tests -v
```

The service starts with `.venv/bin/python -m godseye serve --port PORT`.
Set `GODSEYE_DATA_DIR` to your temporary workspace before starting it. Connect
using `Client("http://127.0.0.1:PORT")`. Both checkpoints and evaluation evidence
remain in that workspace until you deliberately delete it.

## Build the next milestone

After verification, give the agent this separate task:

> Implement Milestone 1 in docs/roadmap.md: a reproducible repair benchmark for
> small networks. Start by proposing a concrete evaluation contract, then build
> it and test it. Generate several corruption families and untouched controls;
> keep corruption labels and expected repairs outside the repair agent's view.
> Separate development and held-out seeds. Enforce probe and forward-pass budgets
> in the evaluator, retain unsuccessful attempts, and report target improvement
> plus regressions. Keep the existing API and demo working. Use CPU only and
> existing dependencies where practical. Do not assume a second LLM API key:
> provide a manual/external-agent protocol and deterministic test participants.
> Document that hiding labels in files accessible to the same OS user is not a
> security boundary; use a separate evaluator process/environment when claiming
> genuinely blind results. Deliver runnable code, focused tests, example evidence,
> and updated docs. Preserve other edits; do not deploy or rent compute.

An agent can build and exercise the harness. Claims that it discovered useful
repairs still require actual controlled experiments; a successful test run does
not establish general-purpose weight-space programming.
