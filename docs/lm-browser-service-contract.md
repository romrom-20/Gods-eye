# Local Qwen browser contract v1

This interface is implemented by the [local service](local-lm-service.md) and
[browser workspace](lm-browser-workspace.md), with real integration evidence.
It requires an operator-configured local source checkout. The existing Breakout
routes, static export and operator harness keep their contracts. No remote compute,
paid provider, arbitrary model/dataset or general-language editing is added.

## Setup and boundary

The operator explicitly sets GODSEYE_LM_CACHE (existing verified pinned weights),
GODSEYE_LM_PYTHON (absolute isolated Python interpreter), and GODSEYE_LM_DIR
(private persistent job/evidence directory) before starting the local server.
The browser cannot supply filesystem paths, interpreter commands, provider keys,
model revisions or executable operations. Base-package imports and ordinary lab
startup must not import Torch or download anything. Missing configuration produces
an actionable unavailable state. Readiness checks are bounded and cached; no model
load/inference/download happens on page open or preview. Full model hash checks run
inside the execution deadline before inference. The service is loopback-only and
uses existing Host/Origin, cross-site, JSON-body and optional bearer-token checks.
It is not a hosted security boundary or an OS sandbox.

All routes below live under /api/v1/lm. JSON body fields are exact; reject unknown,
duplicate or wrongly typed fields. Body and response sizes are bounded. Non-2xx
responses contain an `error` string; LM-domain errors also contain `code` and
`schema_version:1`. UI must tolerate existing boundary errors with only `error`.
Codes: unavailable (503), readonly (403), invalid_request (422), not_found (404),
conflict (409), plan_expired (409), busy (429), storage_full (507), internal (500).
Messages must not echo secrets, command output or arbitrary local paths.

## Capability and plan

GET /capabilities returns:

    {schema_version:1, available:bool, readonly:bool, reason:string|null,
     model:{id:string,revision:string}, execution:"local_cpu",
     supported_goal:"correct_bounded_json",
     sample_request:"Improve JSON schema adherence",
     limits:{max_attempts:126,max_new_tokens:96,max_worker_seconds:1800,max_concurrency:1}}

`available` means configured dependencies/cache metadata allow admission, not that
weights have already passed the execution-time hash check. An old server's 404
is an unsupported/setup state. Static exports never request this endpoint.

POST /plan body: {schema_version:1, request:string}
Response: {schema_version:1, outcome:"ready"|"unsupported"|"clarification_required",
message:string, plan_id:string|null, expires_at:string|null,
spec_sha256:string|null, spec:object|null}.

Use the existing fixed TaskSpec and finite phrase parser, pinned runtime revision
and target-only prompt prefix. Do not mutate candidate selection, fixtures or
thresholds. The server persists a short-lived (10 minute) opaque plan ID and exact
spec before returning a ready preview. It stores no raw user request. Bound plans
and expire unused ones. Review must show local CPU, fixed Qwen target, public
28-case fixture, two predefined edits, prompt/decoding alternatives, unchanged
original, maximum 126 attempts / 96 output tokens each / 30 minutes total, and
no provider fee. These are ceilings, not a time estimate or an improvement promise.

## Admission and reconciliation

POST /jobs body: {schema_version:1,plan_id:string,spec_sha256:string,idempotency_key:string}
Response HTTP202 for first admission, HTTP200 for identical prior admission:
{schema_version:1,job:Job}. Keys are browser-generated UUIDs, not credentials.
Persist exact plan/spec/key binding transactionally before starting a child.
A repeated identical tuple returns the original job even after plan expiry;
changed tuple under the same key conflicts. First admission requires unexpired
plan and readiness. Never retry an uncertain start automatically.

POST /resolve body: {schema_version:1,spec_sha256:string,idempotency_key:string}
Returns {schema_version:1,job:Job} if admitted; 404 if no such admission, 409 if
that key belongs to another spec. This is a read-only reconciliation operation.
The UI retains the exact pending tuple across reload in sessionStorage (no keys,
raw prompts or model outputs), resolves before offering an explicit same-tuple
retry, and never generates a fresh key to resolve an unknown start outcome.

GET /jobs returns {schema_version:1,jobs:[Job]} newest first, at most20.
GET /jobs/{job_id} returns {schema_version:1,job:Job}.
POST /jobs/{job_id}/cancel body {schema_version:1} returns the same envelope;
repeated cancellation is idempotent. Status remains cancelling until the owned
process has exited and been waited. Terminal jobs are stable.

Job has these fields (nullable values remain null, never guessed):

    {id:string, spec_sha256:string, created_at:string, updated_at:string,
     status:"queued"|"running"|"cancelling"|"completed"|"failed"|"cancelled"|"interrupted",
     reason:string|null,
     phase:"queued"|"verifying"|"development"|"freeze"|"heldout"|"finalizing"|"unknown",
     progress:{reserved_attempts:int,finished_attempts:int,max_attempts:126},
     result_available:bool,selected_delta_available:bool}

One active model worker, no execution backlog; excess starts return busy without
creating new executions. Retained-job admission is bounded (initially20 runs and
256MiB evidence); refuse full storage rather than delete evidence. Never scan
or include the weight cache in the evidence quota. Use an exclusive service/worker
ownership guard: restart must not admit a second model while an orphan may still
run. Reconcile abandoned jobs as interrupted with no automatic resume. Do not kill
unverified PIDs. Keep states conservative if cleanup cannot be established.

## Results and downloads

GET /jobs/{job_id}/result returns
{schema_version:1,job:Job,report:object|null,attempts:[Attempt],interrupted_attempts:int}.
HTTP409 while nonterminal; a stopped run can return partial evidence and null
report. Attempt matches task_suite.validate_record's public fields exactly.
Do not expose raw filesystem paths, commands, environment, worker logs or secrets.
`report` is the existing recomputed evaluation report where safely available;
strip internal paths if needed without changing scores, counts, verdict or data
identity. Incomplete usage stays unknown. Job state and evidence verdict are
separate: token-limited development is failed/reason budget_limited with partial
result and verdict not_evaluated, never completed/improved. A complete negative or
inconclusive evaluation is completed with that honest report verdict.

POST /jobs/{job_id}/export body
{schema_version:1,kind:"evidence"|"selected_delta"} returns a bounded JSON attachment.
Evidence is available for terminal runs with recorded evidence, including failures.
Selected delta requires completed run, frozen actual selection and verified
independent reload/rollback; no delta when unchanged won, execution stopped or
checks failed. Do not expose an unused candidate as a selected result. Provide
reload/rollback instructions referring to the pinned local delta loader.

## Browser behavior and acceptance

Use an explicit Qwen entry at /lab#language-model; preserve Breakout views and
recorded demo. Qwen view may use a full-width workspace instead of squeezing its
workflow into the Breakout inspector. No model graph nodes or success indicators
without actual jobs/checkpoints/evidence. Show original vs candidate responses,
valid JSON vs correct answers, regression counts and dev/heldout distinction.
Interrupted/token-limited states explain the next action without automatic retry.
Render model outputs as text, never HTML; keyboard and mobile use must work.

Static export shows a clear local-only setup explanation for this entry, performs
zero /api requests even with mock query flags, and exposes no Start/Cancel/export
execution actions. No new recorded Qwen fixture is fabricated or silently added.

Backend and UI tests use this exact contract. Mock transport is only
for labeled deterministic tests. Real service/browser integration was verified
on a dedicated port, preserving the earlier experiment evidence.
Future sandbox/remote workers implement the same lifecycle behind an adapter;
this phase neither provisions infrastructure nor grants paid-execution authority.
