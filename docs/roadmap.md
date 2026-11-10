# Build God's Eye from here

The wedge is a trustworthy experiment loop for direct weight edits: inspect,
preview, branch, evaluate, retain evidence. A generic inference wrapper cannot
provide this because it does not own the model tensors. The first customer is a
researcher or coding agent investigating a small, accessible model.

## What exists in this repo

- Product website, visual tensor lab, branching, paired evaluation, replay,
  per-episode scores, and run export.
- NumPy/MinAtar execution of the released Breakout policy. This is actual CPU
  computation, not a simulated inference response.
- FastAPI v1 contract and Python HTTP client; CLI for direct local experiments.
- Patch preview and optional parent-hash precondition. Bounded numeric patch
  language; no remote code execution or executable model uploads.
- One evaluation worker, a bounded queue, progress, cooperative cancellation,
  persisted status, restart interruption detection, and evaluation idempotency.
- Static export of two bundled recorded runs and four inspectable checkpoints.
  Static visitors can inspect and replay; they cannot execute experiments.
- Automated core, API, security-boundary, queue, and export tests. CI builds
  a wheel and a static website artifact. It does not publish the site.

There is no autonomous LLM programmer, remote GPU worker, user account system,
paid service, or production multi-tenant isolation. Those are not implied by
having an API or a bearer token.

## A practical first week

1. Run `pip install -e '.[dev]'`, `godseye serve`, and open `/lab`.
2. Preview and ablate four left-action connections. Evaluate against `paper`.
   Restore them on the new branch and verify the restored hash matches `paper`.
3. Repeat on held-out seeds. Save failures and report scores, paired standard
   error, caps, and sample count. Avoid selecting edits on the held-out set.
4. Export with `godseye export-demo --output dist/demo`. Upload those files to
   a static host, or share the CI artifact. No application server is required.
5. Ask five researchers to complete one novel edit without assistance. Observe
   where tensor context, patch syntax, uncertainty, or lineage is confusing.

Success criterion: a new user can independently explain a change and reproduce
its measured effect. Track time to first completed experiment, failed patches,
reproducible runs, and the proportion of edits evaluated on held-out seeds.
Do not use signups or a dramatic single replay as the only signal.

## Milestone 1: make repair a measurable task

The first local harness is implemented: see [repair-benchmark.md](repair-benchmark.md).
It includes three fault families, controls, persistent reservations, frozen
selections, and deterministic baseline participants. Genuine evaluator isolation
and evidence from external repair agents are still outstanding.

Continue expanding the corruption harness with concealed faults, separate development and test
seeds, and explicit probe budgets. Include several fault families, untouched
controls, and unsuccessful attempts. Let a human or external coding agent use
the same API. The evaluator must enforce the budget; reporting forward counts
alone does not enforce an agent's total access to the environment.

Add selected tensor slices, top-k magnitudes, row/column statistics, and tensor
coordinate search before attempting to dump large networks into a prompt.
Add a checkpoint lineage view and side-by-side tensor differences. Keep the
current immutable patch + evidence contract.

Acceptance: repairs generalize across held-out seeds and more than one fault
family; controls detect regressions. This establishes usefulness beyond a known
ablation/restoration recipe.

## Milestone 2: one small language-model backend

Implement a trusted local `Backend` in `godseye/backends.py`, initially for one
small model and fixed architecture. Prefer a safe tensor format; never accept
pickle or enable remote model code for public jobs. Verify model source,
license, revision, tensor schema, dtype, hashes, and parameter count.

Implement bounded slice reads, explicit slice edits, and rank-one updates.
Keep full-weight edits, adapter edits, and activation interventions distinct.
Store model/tokenizer revisions, prompts, sampling settings, and evaluation
harness versions. Use checks for unrelated capabilities as well as the target
behavior. Define numerical tolerances across hardware rather than promising
bitwise-identical text generation.

The current browser and `Store` backend seam do not make arbitrary models
plug-and-play. The UI and evaluation request schema still assume Breakout;
introduce model capability and environment schemas alongside this backend.

Acceptance: one targeted intervention can be inspected, applied, reversed,
and evaluated without reloading the model after every small change. Measure
load time, patch latency, peak memory, and quality before buying compute.

## Milestone 3: remote execution without owning hardware

Keep the public website static. Put a small control plane in front of workers
provided by the customer or rented per job. Prefer an outbound worker agent:
no public inbound port on the customer's machine. The worker claims a signed,
tenant-scoped lease for a known model and a bounded operation; it does not
receive arbitrary user Python.

The intended flow is:

    Browser / SDK
        → authenticated control plane
        → PostgreSQL (tenants, checkpoints, jobs, reservations, audit records)
        → durable queue (leases, heartbeat, cancellation, retries)
        → isolated worker (verified base + validated patch + evaluator)
        → private object store (weights, deltas, evidence)
        → authorized result reads

Separate checkpoint identity from tensor content identity. Authorize the
lineage and artifact reference before deduplicating or looking up content;
a content hash must never become a cross-tenant access token.

Start with one worker provider. Introduce a provider interface for launch,
lease, cancel, usage report, and teardown. Require explicit user-supplied
credentials or an approved spending limit. Store provider credentials only
in the control plane's secret manager. Add idle shutdown and hard ceilings.

Budget reservation must happen transactionally before admission. Reserve the
worst-case charge, enforce a worker wall-clock/resource ceiling, reconcile
measured usage, and release the unused reservation. Retries need idempotent
result publication and billing keys. A cancelled HTTP request is not evidence
that the remote worker stopped or that billing ended.

Acceptance: a worker crash, duplicate delivery, disconnect, or cancellation
cannot double-publish a result or double-charge a user. Restore and disaster
recovery exercises precede billing real users.

## Milestone 4: public beta security and operations

- Tenant-scoped authorization on every model, tensor, checkpoint, job, and
  artifact; expiring API keys with scopes, revocation, rotation, and hashed
  storage; browser sessions with CSRF protection and secure cookies.
- One isolated process/container or stronger boundary per untrusted job.
  Read-only root filesystem, non-root execution, resource/time limits,
  restricted egress, and no cloud metadata or control-plane credentials.
- No arbitrary URLs fetched by workers. An artifact registry resolves approved
  sources; validate paths, size, shape, dtype, compression expansion, and hash
  before allocation. A safe serialization format alone is not a resource limit.
- Durable admission quotas, per-user rate limits, storage retention and deletion,
  cancellation acknowledgments, audit events, and private artifact URLs.
- Structured logs and traces without tokens, raw prompts, private tensors, or
  signed URLs; metrics for queue age, job failures, cost, worker memory, and
  artifact publication. Backups and documented recovery objectives.
- Dependency scanning, pinned release images, a model-license inventory,
  disclosure channel, and regression tests for tenant isolation.

The local server intentionally refuses non-loopback writable binding. Do not
remove that guard and call the result a production platform.

## Product and commercial direction

First sell clarity and repeatability: explainable edits, reliable evaluation,
and an artifact history a collaborator can reproduce. A later paid service
could charge for managed workers, team workspaces, private artifact storage,
and reproducibility infrastructure. Validate demand before building billing.

A public static demo incurs no model-execution cost. A live small-model demo
still needs CPU/RAM and storage somewhere; a large-model service needs a
provider or customer worker. Free hosting allowances change and are not a
business model. Choose a provider after measuring actual workloads.

## References and boundaries

The design borrows the small composable developer surface from
[Tinker](https://thinkingmachines.ai/tinker/). Its documented
[TrainingClient](https://tinker-docs.thinkingmachines.ai/tinker/api-reference/trainingclient/)
exposes training, forward, and checkpoint operations; the listed surface does
not expose the arbitrary tensor patch API proposed here. This is an inference
from the documented API, not a claim about all internal capabilities.

[Sparks of Weight-Space Programming](https://rikiyat.github.io/blog/weight-space-programming/)
motivates direct edits. The included policy is an upstream artifact, and this
project's known-circuit demo does not independently verify the paper's broader
claims. References checked November 9, 2026.

### Repair evaluator implementation update

The separate container evaluator, restricted tool-calling model adapter,
experiment-wide freeze gate, and deterministic HTTP/failure tests are implemented.
See [launch instructions](isolated-evaluator.md) and the
[baseline-only report](evaluator-pilot-report.md). Actual container validation and
the real-agent comparison are still pending on a host with Docker and an existing
provider credential. Neither baseline nor scripted-agent tests establish discovery.


## Provider platform follow-up

Implemented: local provider profiles for OpenAI/OpenRouter/Hugging Face, explicit
model IDs, fixed-endpoint adapters, OpenRouter preference/privacy controls,
no automatic fallback, usage and returned route metadata, offline contract tests.

Next: an opt-in one-request tool-capability probe; a dated model catalog with
capability filtering; cumulative token admission limits and provider-reported
cost reconciliation; immutable run manifests including resolved route and code
version; latency/usage comparison on identical development cases; encrypted OS
keychain integration and key deletion. Only introduce fallback with explicit
allowed destinations, independent budgets, and visible experiment lineage.
Avoid claiming SOTA repair quality until blinded real-agent results support it.
