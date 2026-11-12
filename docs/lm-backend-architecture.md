# Language-model backend: local first, replaceable workers

Decision: build one narrow, auditable JSON task journey before accepting arbitrary
natural-language model edits. The implemented planning/scoring slice is described
in [lm-task-contract.md](lm-task-contract.md); the interfaces below are a proposed
integration architecture, not existing LM browser routes or runner support.
Keep the Qwen3.5 CUDA toy pilot separate from the Qwen2.5 local task.

## Four boundaries

**Browser/request planner → trusted local control service → replaceable execution
worker → immutable artifacts and evaluator evidence.**

The browser submits inert goal text, receives a conservative interpreted spec
and finite limits, and lets the user review model, dataset, edit search and
privacy choices before starting. Preview performs no inference, experiment,
download, credential access or charge. Arbitrary requests get useful unsupported
or clarification responses. A coding-agent model may later suggest bounded
candidate operations, but its prose is untrusted and never an execution command.

The trusted control service owns authorization, policy, model registry, admission,
idempotency, job state, cancellation and evidence publication. Local writable
access remains loopback-only with Origin/CSRF protections; a hostile website
must not be able to operate a logged-in local agent. Local trusted-operator
assumptions do not extend to a hosted multiuser service. Auth and tenant scope
belong here, before any model/artifact/hash lookup, including cache hits.
A content hash is not a bearer credential or cross-tenant deduplication oracle.

The worker owns the actual cached model and tokenizer, verified tensor mutation,
generation, usage measurements and cleanup. It accepts only the canonical spec,
approved content identities and bounded operation IDs. No Python/shell snippets,
arbitrary paths/URLs, pickle uploads, remote code or automatic model fallback.
Registry-owned paths resolve approved content. Loading is explicit, checks
capabilities before execution, and reports unsupported revision/device/operation
without silently changing model, dtype or goals. Capabilities include model and
architecture identity, safe artifact formats, device/dtype, supported operation
and generation limits. A provider used by a coding agent is distinct from a
compute operator with access to target model weights.

Artifacts are immutable, content-addressed model manifests, original/delta
identities, candidate lineage, canonical task specs, ordered attempted-output
journals, frozen selections, evaluation reports and reload/rollback evidence.
Use atomic writes/rename and unique create; never replace an old run's evidence.
Store a job-to-artifact authorization reference separately from content identity.
A hash detects tampering, not malicious fabrication by a trusted local operator.
The evaluator recomputes scores from raw outputs and strict known schemas;
worker/provider self-reported success never determines the verdict.

## Small local implementation

Start with one CPU worker process, one resident model and serialized generation
and mutation. Explicit load reports load duration, resident/peak memory and
identity; unload releases resources. Cache pinned safe files, tokenizer/config
manifests and verified base tensors by content identity; don't reload the whole
model after each small edit or clone it for every candidate. Check original
hash preconditions; apply one bounded edit; generate; restore in `finally`;
verify exact rollback before next work. Failed rollback poisons the worker:
stop admission, tear it down and reload a verified original. Independent delta
reload/reapply/rollback evidence is required before claiming a usable artifact.

A small SQLite/local-journal control store is sufficient now; do not ship a
queue cluster, distributed database, billing system or object store. Proposed
service seams (transport-neutral, not current endpoints):

- `capabilities()` / `load(model_content_id)` / `unload()` on the worker.
- `preview(text, approved_model_revision)` returns spec/hash and interpretation.
- `start(spec_hash, scoped_idempotency_key)` atomically admits one immutable job.
- `status(job_id)` / `cancel(job_id)` / `result(job_id)` read scoped persisted state.
- `execute(job_id, spec, approved_artifact_refs, deadline)` returns/journals attempts.
- `ArtifactStore.put_immutable(content, expected_hash)` and authorized `get(ref)`.

A reused idempotency key with the same spec returns the same job; a changed spec
conflicts. Job IDs are stable across client disconnects. Retries of result/status
never rerun inference; no automatic model-generation or candidate retries.
Reserve finite attempt/token/time/storage allowances before admission. A bounded
queue plus one active job is enough initially; reject excess demand with a useful
busy result. Tokenize before generation to enforce input caps; cap generated
tokens, candidates and attempts; apply an independent process wall deadline that
includes load, hashing and cleanup. Output-record accounting is a cross-check,
not enforcement of actual compute time.

Worker cancellation is cooperative first, then terminate the process at an outer
short grace deadline and clean resources. The parent supervisor must survive
blocked native code, OOM and worker loss. A client HTTP timeout does not prove
execution stopped. Persist `cancelling` until quiescence is acknowledged; use
`interrupted`/unknown cleanup on loss, retaining all available attempts and
reservations. Restart reconciles unresolved jobs as interrupted, without silent
resume, refund or new execution. States: draft/ready, queued/running/cancelling,
completed/failed/cancelled/interrupted. A budget stop is an explicit reason;
execution completion and evidence verdict are separate. `completed` can mean
no improvement or inconclusive, never guaranteed improvement.

Freeze all development selections durably before heldout dispatch. Worker output
records use the exact interface in the task contract; the trusted control journal
preserves rejected malformed envelopes as failures as well. Compare unchanged,
fixed prompt and decoding alternatives and selected edit using equal case/token/
time budgets. Keep all unsuccessful candidates. No heldout feedback may reach a
selector; viewing heldout is terminal for that experiment's search. Public test
fixtures offer engineering guardrails, not concealed-test protection.

## Migration after measurements justify it

Keep `execute`, capabilities, artifact references and job IDs stable. Later swap
the local process adapter for a Modal or other GPU worker adapter and the local
artifact store for private object storage. No remote infrastructure or provider
selection buffet is needed now. Remote admission must add a tenant-scoped lease,
heartbeat, signed job/spec binding, bounded egress, isolated resource limits,
transactional reservations, one result-publication key and explicit teardown.
Duplicate lease delivery must not double-run or double-publish; ambiguous remote
execution needs reconciliation before retry. Billing requires real usage/cost
reconciliation and user-approved finite spend, rather than assuming a client
cancellation ended charges. Never put control credentials in the worker or browser.

The public hosted static demo remains read-only recorded evidence with no
execution. A hosted multiuser control service requires real tenant auth, private
artifact access, CSRF/session protection, sandboxed worker isolation and quotas;
it must not proxy or publicly expose a user's loopback server or inherit local
trusted-operator privileges. Validate those boundaries before public writes.

## Privacy and resources

The default is local cached execution and local artifacts. No task/model data
leaves the machine through this slice. An explicit remote-compute choice must
show which artifacts leave: approved model weights or their downloadable content
identities, tokenizer/config, bounded delta, task prompts/schema/labels, generated
outputs, metrics and required usage metadata. If a coding-agent provider is chosen
separately, disclose its development prompts/tensor summaries/output feedback;
never include credentials, private heldout labels or unrelated local files.
Remote workers, logs, caches and object storage have retention/deletion policies;
opt-in telemetry must exclude secrets and raw private prompts by default. Local
artifact deletion/retention should be explicit too.

Local operation incurs no inference-provider fee when using approved cached
weights, but needs disk, RAM, CPU time and power. Full precision weights need
roughly parameter-count × four bytes before tokenizer/runtime/work buffers and
KV cache; actual task peak RAM and throughput must be measured on the chosen
machine, dtype and limits. Small direct edits do not shrink the model or imply
faster inference. Do not promise fast, unlimited or free hosted execution: model
load, resident RAM, idle time, GPU/CPU, storage and network all cost resources;
unknown charges remain unknown. First acceptance is an honest bounded local run
with measured memory/time, full evidence and verified rollback, not a cloud launch.
