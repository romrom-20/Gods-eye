# Build God's Eye from here

## Product aim

Build an excellent open-source workbench that turns a supported natural-language
improvement request into a reversible model change and trustworthy evidence.

**Promise to work toward:** Describe one supported improvement. Get a tested model
change—or an honest explanation that no improvement was found.

The initial audience is researchers and developers working with small, accessible
models. Start with one complete Breakout workflow, then one small language model.
Do not imply arbitrary model support or guaranteed improvement. The programmer
model and the target model are separate roles: selecting Qwen as a provider does
not give the application access to Qwen's weights or make Qwen an editable target.

Our quality bar is ease of use, reproducibility, useful results, and sound
engineering. “Best” is an ambition to earn through independent use and evidence,
not a claim supported by a polished demo or a single benchmark.

## Release order and immediate priorities

Integrated on 2026-11-11: completed-run checkpoint export with independent reload
and rollback, and trusted activity history with explicit unknown/gap states.
Combined browser download and scripted Docker journal checks passed. This closes
those implementation gaps; real-provider compatibility and repair quality still
need the bounded baseline below.

### Next release: a goal-driven Breakout experiment

1. **Establish the real-agent baseline.** Choose an explicit compatible programmer
   model and user-approved request/token/time limits. Run the existing isolated
   experiment against unchanged and heuristic baselines. Preserve every attempt,
   stop, control regression, and failed repair. Use held-out evaluation only after
   freezing selections. Publish a redacted report with limitations, never secrets
   or unrevealed future test cases. A negative result is valid evidence.
2. **Define the goal contract.** Introduce a versioned experiment specification:
   supported target, requested improvement, measurable success criteria,
   regression checks, permitted edits, development/test split, and limits.
   Translate a natural-language request into this constrained specification;
   reject unsupported goals clearly rather than promising arbitrary execution.
   The UI must distinguish an AI suggestion from a measured result.
3. **Connect the browser to the isolated harness.** Add a trusted operator service
   for launch, status, cancellation, and result retrieval. The browser must never
   receive provider keys, evaluator admin tokens, or hidden evaluation data.
   Persist run identity and decisions. Integrate cancellation without weakening
   reservations, freeze gates, or the current refusal to resume agent runs.
4. **Ship the complete user journey.** Request → review interpreted goal and
   limits → start → visible progress → result → compare/export/keep original.
   Show “checking the original,” “trying an edit,” and “testing the result,” with
   advanced detail expandable. Keep the no-key guided example as onboarding.
5. **Return a useful result.** Include original and edited versions, exact delta,
   interpretation of the measurements, sample counts and uncertainty, regression
   results, known limitations, recorded usage, and export/rollback instructions.
   Distinguish improvement, inconclusive/no improvement, budget stop,
   cancellation, and execution failure. Never label an untested edit a success.

Release acceptance:

- A new user can complete the supported journey without a terminal or tensor
  syntax, understand which model was changed, and find the original version.
- A small first usability study: at least four of five new participants complete
  the journey without coaching; record time, confusion, and failure points.
  This is an initial product check, not statistical proof of broad usability.
- At least one bounded real-provider experiment is reported transparently;
  reliable improvement remains a research gate, not a required fabricated outcome.
- Tests cover launch authorization, duplicate submissions, cancellation, provider
  errors, missing usage, reload/restart behavior, and hidden-data separation.
- The local/no-key path stays usable. Public writable hosting stays disabled.

### Following release: one editable small language model

The first measured local target is a pinned Qwen2.5-0.5B-Instruct revision,
implemented as a separate CPU CLI. Its [JSON-task evaluation](local-lm-task-validation.md)
was incomplete after a development token cap; neither fixed edit improved the
observed counts. General model compatibility and useful repair remain unproven.
The [local service and browser](lm-browser-workspace.md) now connect this runtime
and evaluator; a real browser run reproduced the incomplete result without retry.
Next, improve the editing method and setup experience, then test with outside users.
Support one narrow goal with examples
and a held-out test set. Preserve original weights, tokenizer/model revisions,
patches, and sampling settings. Export a usable model or delta with a verified
reload path; a text explanation alone is not the model artifact.

Acceptance: a targeted change can be inspected, applied, reversed, reloaded, and
compared on both target and unrelated capabilities within documented resources.
Do not promise laptop execution until that exact model/configuration is measured.

### Then: demonstrate value before expanding infrastructure

Compare against the unchanged model, improved prompting, and an appropriate
conventional adaptation baseline. Evaluate quality, regressions, latency, memory,
and total cost under the same task definition. Include editing, evaluation,
deployment, and recurring inference costs; report assumptions and any break-even
volume. Sparse edits alone do not imply smaller models or faster inference.
Unknown charges remain unknown rather than being recorded as zero.

Only then prioritize rented/customer-owned workers, deployment, collaboration,
and managed services. Larger model support is not a substitute for a useful,
reproducible workflow on one model.

## How we operate

- Maintain one prioritized release backlog. Every item has an owner, user
  outcome, dependencies, acceptance checks, and an evidence/demo link when done.
- Work in small reviewable branches. Use two implementation agents in parallel
  for independent areas and one coordinating reviewer. Agree shared interfaces
  first; assign file ownership and reconcile integration tests before merging.
- A practical next split: one agent owns the experiment specification and API
  contract; another owns the guided UI using that agreed contract and mock data.
  The coordinator owns harness integration and end-to-end verification. Do not
  advertise a mocked UI as a live agent experiment.
- Review actual user behavior and a working demo each iteration. Change the plan
  when evidence shows confusion, poor repair quality, or unfavorable economics.
- Ask the user at milestone, model/spend, deployment, and material scope decisions.
  Continue routine implementation and test fixes autonomously within authorization.
  No paid experiment starts merely because a credential has been saved.
- Definition of done: reviewed implementation, meaningful tests, combined CI,
  documented limitations, usable error states, and a reproducible demonstration.
  Do not close a task just because its unit tests pass or its agent reports done.
- Measure time to first result, unassisted completion, reproducibility, held-out
  improvement and regressions, failure rates, latency, and cost per successful
  improvement. Do not optimize stars or signups instead of usefulness.

## Open-source release quality

Add a contributor guide, issue templates with acceptance criteria, a security
reporting policy, changelog, and versioned releases. Keep installation and a
no-secret smoke test reproducible. Document stable interfaces and migration notes
when contracts change. Supply small datasets/examples with provenance and licenses.
Use release evidence and independent reproduction to support scientific claims.

Contributions must not contain credentials, private user data, provider error
bodies, or concealed evaluation fixtures. Add automated secret/dependency checks
and pin release dependencies/images with a documented update process. Keep
telemetry opt-in, explain its contents, and provide local artifact deletion.

## Adjacent directions to validate later

Small classifiers, document extraction/routing models, and simulation/game policies
may be useful extensions. Each needs an explicit task, evaluator, regression suite,
license review, and actual user demand before implementation. Keep direct weight
editing, adapter training, activation interventions, and prompt optimization
clearly distinguished. None is a universal replacement for the others.

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
  a wheel and a static website artifact. An approval-gated Pages workflow is
  deployed for this repository's recorded demo, with environment approval required;
  see [public demo](public-demo.md).

Also implemented: a separate restricted tool-calling programmer harness; validated
Docker evaluator isolation; provider profiles, model discovery, and confirmed
connection checks; cumulative request/reported-token limits and no-resume claims.
The simplified local UI includes a guided fixed four-weight experiment.

A constrained browser goal review/start/status/cancel journey and operator service
are implemented with scripted acceptance evidence; real-provider discovery and
repair quality remain unproven. A separate local Qwen2.5 CPU runner now supports
fixed column edits, verified rollback/reload and a public JSON fixture. It is
connected to an operator-configured local browser/HTTP service, with real
budget-limited integration evidence, and has not demonstrated improvement.
There is no verified remote GPU execution, account system, paid service, or production multi-tenant
isolation. Real-agent repair quality and cost savings remain unproven. Docker
boundary tests with a scripted provider do not establish intelligent repair.

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
selections, and deterministic baseline participants. The separate Docker evaluator
boundary has passed integration tests. Real-provider repair evidence remains outstanding.

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

The first runtime lives in `godseye/lm/local_runtime.py`, separate from the
Breakout-specific Store/backend protocol. Follow the
[local-first backend boundaries](lm-backend-architecture.md) when connecting it
to a trusted control service; do not force language-model weights through the
Breakout archive format. Support one small model and fixed architecture first.
Prefer a safe tensor format; never accept
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
[baseline-only report](evaluator-pilot-report.md). Container validation and
the real-agent comparison have different statuses: container validation passed
with dummy credentials and a scripted provider; the real-agent comparison remains
unexecuted. Neither baseline nor scripted-agent tests establish discovery.


## Provider platform follow-up

Implemented: local provider profiles for OpenAI/OpenRouter/Hugging Face, explicit
model IDs, fixed-endpoint adapters, OpenRouter preference/privacy controls,
no automatic fallback, usage and returned route metadata, offline contract tests.

Integrated: explicit model catalog loading with conservative capability labels,
a confirmed one-request tool probe, cumulative request/reported-token admission
limits, and refusal to resume an existing agent evidence directory.

Next: dated catalog snapshots and provider-reported cost reconciliation; immutable run manifests including resolved route and code
version; latency/usage comparison on identical development cases; encrypted OS
keychain integration and key deletion. Only introduce fallback with explicit
allowed destinations, independent budgets, and visible experiment lineage.
Avoid claiming SOTA repair quality until blinded real-agent results support it.
