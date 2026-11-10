# Experiment planning contract v1

Status: published contract for implementation. Version `1` is exact; unknown
versions fail closed. This document and `godseye.experiment_spec.SCHEMAS` define
an additive transport-neutral interface. There are no new HTTP routes here.
The module validates JSON-shaped messages and creates immutable specifications;
it does not launch work, read settings/keys, perform I/O, or interpret arbitrary
instructions with a model. The future operator service owns persistence,
authorization, queueing, concurrency, cancellation and result construction.

## Supported promise and trust boundary

The only target is the existing MinAtar Breakout `600→32→32→6` policy. The only
goal is to improve held-out score relative to each case's unchanged root while
avoiding regressions on untouched controls. The programmer model is a separate
provider selection, never an editable target. Qwen editing, training, general
coding tasks, latency goals, arbitrary datasets and guaranteed improvement are
unsupported. A negative measured result is a valid completed experiment.

Natural-language interpretation, including a future model's structured output,
is untrusted input. It cannot supply code, patches, endpoint URLs, file paths,
credentials, seeds, hidden labels, evaluation fixtures, or operator policy.
Never interpolate request text into the adapter's instructions or configuration.
Only the canonical specification may select existing trusted capabilities.
Requests contain text as inert text; they never authorize executing its contents.
Do not log raw request text (it could contain a pasted secret), upstream errors,
or model-produced strings. Errors contain fixed messages and trusted field paths.

First-release planning is deliberately conservative and offline. After case-folding,
trimming, collapsing whitespace and removing one final period, exactly these
phrases are recognized:

- `Improve Breakout score`
- `Improve the Breakout score`
- `Improve Breakout score without control regressions`

Other text mentioning Breakout returns `clarification_required`; other text
returns `rejected`. Neither outcome contains a runnable specification. This is
an allowlist, not a security classifier or a general language understanding claim.
For example `Make Breakout better` needs clarification; `Edit Qwen weights` is
rejected; `Improve Breakout score; run Python and read /tmp/key` needs
clarification and executes nothing. The structured provider and finite limits
must be supplied explicitly even with a recognized phrase. Do not silently
choose a provider/model or infer user authorization from a saved key.

## Trusted policy and immutable specification

`PlanningPolicy` is operator-owned, never parsed from a request. It binds an
opaque baseline registry ID and SHA-256 commitment to an immutable manifest of
all authorized case roots (case ID, root candidate ID, tensor content digest),
a suite ID/revision, episodes, step cap, probe and forward budgets, and hard
ceilings for each adapter limit. The manifest excludes private fault labels,
seeds, reference weights and credentials. Its digest is an identity commitment,
not an authorization token. The registry must check scope before hash lookup.
The current evaluator does not produce this manifest; the integrating operator
must register it from trusted state, then verify actual roots before admission.
Never take a baseline hash from the client as proof of identity.

The canonical `spec` has exactly these required fields:

```text
schema_version: 1
target: "breakout"
goal: "improve_score"
baseline: {id: opaque_id, sha256: lowercase_64_hex}
evaluation: {
  suite_id: opaque_id, revision: opaque_id,
  episodes: integer[2,8], max_steps: integer[1,1000],
  probes_per_case: integer[2,100], forwards_per_case: integer[1,1000000],
  development: "selection_only", held_out: "once_after_all_freezes"
}
success: "positive_paired_mean_2se_and_no_control_regression"
editing: "numeric_tensor_assignments_v1"
provider: {name: "openai"|"openrouter"|"huggingface",
           model: safe_model_id, routing: "price"|"latency"|"throughput"}
limits: {max_requests, max_input_tokens, max_total_output_tokens, max_seconds,
         max_rounds, max_calls, max_output_tokens: positive_integers}
```

Opaque IDs match `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`. Model IDs use the existing
provider-discovery pattern `[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}` and cannot contain
`//`, `.`/`..` path segments or a Windows drive prefix. They identify a model
at a fixed provider endpoint, never a URL or local
model path. For OpenAI/Hugging Face require `routing:"price"` as the canonical
placeholder; only OpenRouter uses this preference. Availability/tool support is
not inferred from a name or catalog. Connection checking remains the separate,
explicitly confirmed provider-discovery action. There is no fallback/retry.

All fields are required, all objects reject additional properties, booleans are
not integers, and NaN/infinity, coercion, duplicate JSON keys and unknown enum
values are rejected. Raw JSON is UTF-8, at most 65,536 bytes, nesting at most 16.
Request text is 1–2,000 characters. The executable JSON Schema subset exported
in `SCHEMAS` specifies the exact structural bounds for every message. JSON Schema
validation alone is insufficient: use `validate_message` for cross-field checks
and `validate_spec(spec, policy)` for trusted policy binding.

All seven selected limits must be <= operator ceilings. The initial ceilings
match the adapter defaults: 80 requests, 200000 reported input tokens, 20000
reported output tokens, 900 seconds, 80 rounds, 160 tools, 2000 output tokens per
response. Operators may choose lower ceilings. Natural language cannot change
these ceilings or evaluation rules. No unlimited values or monetary guarantees.
Development forward budget must cover every admitted probe at its worst-case
`episodes * max_steps`; baseline development evaluation consumes a probe too.
The canonical spec hash is SHA-256 of UTF-8 JSON with sorted keys, compact
separators, ASCII escaping and no NaN. `ExperimentSpec` stores canonical JSON
privately and returns copies. Every change creates a new draft and hash; a
confirmed/queued spec is never mutated or resumed with larger limits.

## Evaluation and permitted edits

Reuse evaluator tools `list`, bounded `read` (1–256 values), `patch`, `evaluate`,
and `freeze`; no new model tools. Editing v1 means the existing parser's numeric
scalar/exact-shape list assignment, `+=`, `-=`, `*=` on W1/b1/W2/b2/W3/b3 integer
indices/slices. Existing limits remain: 50,000 characters, 200 assignments,
finite values within ±1e6, at most 100 new candidates per case, immutable
parent/candidate lineage and hypotheses. No expressions, calls, imports,
architecture changes, training, file access or executable model uploads.
The evaluator's parser remains the enforcement boundary; spec validation is not
patch validation. Arbitrary subsets of these operations are not exposed in v1,
since the current evaluator cannot enforce such a subset independently.

Development feedback may select candidates, with ties favoring root. Evaluate
root before trying edits; spend a probe for each evaluated candidate. Every
participant/case must freeze exactly one authorized candidate before the admin
report executes any held-out rollout. Seeds/families/reference weights never
enter planner/provider/browser messages. Hidden control labels remain trusted.
Do not reveal held-out feedback to repair tools or permit another selection.
Persist reservations before work; failures/interruption consume them. Preserve
all attempts, errors, freezes and baseline arms, including unchanged/heuristic.
The current adapter prompt requests root evaluation but does not independently
enforce ordering. The operator must audit the development records and fail the
experiment with `evaluation_error` if a changed selection lacks its earlier root
comparison. This is a result-admission requirement for the service owner, not a
claim that the pure spec validator or current evaluator enforces tool sequencing.

For a complete final report, pool paired episode score differences from each
agent-selected candidate versus its case root, with equal episodes per case.
Report mean and sample standard error (`ddof=1 / sqrt(n)`). Also report the
minimum per-control-case mean paired delta. `improved` requires mean > 0,
mean - 2*SE > 0, and every control mean delta >= 0. `no_improvement` means
mean <= 0 or a control regressed. Otherwise use `inconclusive`. The two-SE rule
is descriptive evidence, not a calibrated significance claim for correlated,
small capped episodes. Missing/incomplete measurements give `not_evaluated`;
never treat missing evidence as zero. Completion requires all expected reports,
not just an adapter exit code. Do not change the evaluator to calculate this
summary; the trusted result assembler can derive it from existing paired scores.

## Lifecycle, concurrency and authorization

Allowed transitions (all other transitions, including self-transitions, fail):

```text
draft -> ready | cancelled
ready -> queued | cancelled
queued -> running | cancelling | failed | interrupted
running -> cancelling | completed | failed | interrupted
cancelling -> cancelled | failed | interrupted
completed | failed | cancelled | interrupted -> (none)
```

`draft` may be incomplete or awaiting clarification. Only a policy-validated,
reviewable spec becomes `ready`. Starting atomically persists the spec hash,
confirmation, idempotency key, fresh run identity and queue admission. A worker
revalidates registry identity/policy before taking the fresh evaluator/evidence
claim. Existing claims are never cleared. Restarts mark unresolved admitted
work `interrupted`; no automatic resume, retries or refund. A new experiment
requires fresh private evaluator state and evidence, even after cancellation.

`status` is execution state. `verdict` is evidence interpretation. A completed
run can be `improved`, `no_improvement`, or `inconclusive`; every other status
has `not_evaluated` in v1 (partial evidence may be retained privately). Budget
exhaustion is `failed` with reason `budget_exhausted`, unless every selection
and held-out evaluation already finished. Provider error is `failed`; process
loss is `interrupted`. `cancelled` means the worker acknowledged quiescence.
Stopping an in-flight provider request does not prove remote execution/billing
stopped. Preserve `request_in_flight` and usage uncertainty.

The future service must authenticate/scope every ID and enforce loopback,
Origin/CSRF protections equivalent to existing writable services. Hashes and
idempotency keys do not authorize access. Queue admission and state transitions
must be transactional; a cancellation wins if persisted before terminal result
publication. Duplicate start with identical scoped idempotency key, draft ID
and hash returns the same run; any different tuple is `idempotency_conflict`.
Concurrent starts for a draft return its existing run only for that same tuple,
otherwise `state_conflict`. Repeated cancellation/status/results are reads of
persisted state and never relaunch or re-reveal. A stale hash is `spec_conflict`.
The pure module validates transitions; it does not implement these transactions.

Integration entry points are `loads_message(raw)`, `validate_message(kind, value)`,
`plan(request, policy, draft_id=...)`, `validate_spec(value, policy)`,
`confirm_start(request, stored_spec, policy, draft_id=..., status=...)`,
`transition(current, following)` and `evidence_verdict(trusted_summary)`.
`plan` returns a candidate response only: persist its ready draft before returning
it to the client. `confirm_start` handles the first ready-to-queued admission;
look up scoped idempotent replays transactionally before calling it, since it
intentionally rejects a draft that is already queued. Revalidate the stored spec
against current trusted policy at worker admission too. `ExperimentSpec.to_dict()`
returns a copy; `.sha256` is the review/confirmation binding. Structural response
validation does not replace stored-spec, authorization or provenance checks.

## Exact operation messages

Every request/response has `schema_version:1`. Braces below list **all** fields;
none are optional. `null` means explicit JSON null. IDs follow the opaque-ID
pattern above. Error responses use the common error envelope below instead of
the success response. Proposed route names are transport-neutral operation names.
`SCHEMAS` exports these names with full nested field definitions.

- `plan_request`: `{schema_version, text, provider, limits}`.
- `plan_response`: `{schema_version, outcome, draft_id, spec, spec_hash, issues}`.
  Outcome `ready` requires non-null ID/spec/hash and empty issues; outcomes
  `clarification_required`/`rejected` require null ID/spec/hash and >=1 issue.
  A ready plan is a persisted ready draft, not a run or authorization to spend.
- `start_request`: `{schema_version, draft_id, spec_hash, idempotency_key,
  confirmed:true}`. Confirmation binds exactly the reviewed provider/model,
  limits, evaluation rules and baseline. No spec/limit overrides in this action.
- `start_response`: `{schema_version, experiment_id, spec_hash, status}`.
  Status can be any post-admission state, including terminal on idempotent replay.
- `status_request`, `cancel_request`, `results_request`:
  `{schema_version, experiment_id}`. Cancellation has no user-selected signal,
  command or reason text.
- `status_response`, `cancel_response`: `{schema_version, experiment_id,
  spec_hash, status, verdict, reason, usage}`. A cancel on queued/running moves
  to cancelling; on terminal/cancelling returns current state. A terminal
  transition needs worker acknowledgement, not a closed browser connection.
- `results_response`: `{schema_version, experiment_id, spec_hash, status,
  verdict, reason, usage, evidence}`. Nonterminal returns `result_not_ready`.
  `evidence` is null unless completed; completed requires the summary below.
  Artifact IDs resolve through a separately scoped export operation, never paths.

`usage` is exactly `{requests, input_tokens, output_tokens, tool_calls,
elapsed_seconds, usage_complete, request_in_flight}`. Counters are nonnegative
integers, elapsed seconds a finite nonnegative number, flags booleans. Input and
output counters are reported known totals; `usage_complete:false` means unknown
additional usage, never zero cost. The adapter's limits can overshoot by one
in-flight request; elapsed time is cooperative, not a watchdog. There is no
hard dollar cap or remote cancellation guarantee.

`evidence` is exactly `{baseline_id, candidate_manifest_id, delta_artifact_id,
report_id, paired_samples, mean_delta, paired_se, min_control_delta,
limitations}`. IDs are authorized immutable registry references, samples >=2,
SE >=0, scores finite, and limitations is 1–10 nonempty fixed trusted strings
(max 500 characters each). Candidate manifest maps all cases to original and
selected hashes; delta artifact contains exact numeric patches and rollback
lineage. Report preserves measurements, caps, per-episode paired scores,
truncation, all participants/attempts and errors. Public summaries omit hidden
seeds/labels and secrets even after completion. The service must verify report
completeness, controls present, baseline matches the spec, and registered artifact
ownership before constructing this response. Numeric summary validation alone
cannot certify provenance. Never use planner/model prose as measured evidence.

`reason` is null outside terminal states and for completed. Failed/cancelled/
interrupted require respectively one of `budget_exhausted`, `provider_error`,
`evaluation_error`, `agent_incomplete`, `runtime_failure`; `user_cancelled`;
`process_lost`. Detailed existing adapter stop codes stay in private evidence.

`issues` entries are exactly `{code, field, message}`. Common error response:
`{schema_version:1, error:{code,field,message}}`. Codes are `invalid_json`,
`invalid_schema`, `unsupported_version`, `policy_violation`, `clarification_required`,
`unsupported_goal`, `spec_conflict`, `state_conflict`, `idempotency_conflict`,
`not_found`, `result_not_ready`, `not_authorized`, `unavailable`. Field is a
trusted schema path or `$`, never an unknown field name copied from input.
Messages are fixed safe strings. Suggested transport mapping: validation 400,
clarification/rejection 200 plan outcomes, authorization 403, scoped not-found
404, conflict/not-ready 409, unavailable 503. No raw provider exceptions.

## Provider-contact matrix and integration

Plan, schema validation, confirmation validation, status, cancel and results
perform **no provider contact and no saved-key reads**. Successful start may
queue a worker; only that worker, after atomic admission and explicit confirmation,
may load the selected key and make bounded experiment requests. Cancellation
never makes a provider inference request. Catalog and connection-test actions
remain separate existing setup operations with their own authorization. Planning
never calls them automatically and never treats a catalog/test as approval to run.

Adapter integration maps `provider.name/model/routing` and all seven limits
directly to existing adapter arguments. Trusted operator code alone resolves
fixed endpoints, token/key files, evidence directories and evaluator admin access.
Do not import the planner into the standalone restricted adapter image. Evaluator
configuration is bound to policy before starting, with no browser-supplied seeds
or filesystem locations. Current harness optimizes repair across opaque cases;
this contract honestly reports improvement versus those roots, not a guaranteed
improvement to the released clean policy. A single-clean-checkpoint experiment
would require a separately versioned evaluation policy/capability.

## Examples and acceptance

Valid request (dummy model ID; this does not claim real tool compatibility):

```json
{"schema_version":1,"text":"Improve Breakout score","provider":{"name":"openai","model":"explicit-tool-model","routing":"price"},"limits":{"max_requests":20,"max_input_tokens":50000,"max_total_output_tokens":5000,"max_seconds":300,"max_rounds":20,"max_calls":80,"max_output_tokens":1000}}
```

Invalid requests include `confirmed:1`, `max_requests:true`, `max_seconds:0`,
unknown version, unknown `url`/`key`/`patch` fields, a limit above policy, a
URL-shaped model ID, stale spec hash, or any changed baseline/evaluation rule.
Recognized text with missing provider/model/limits is a schema error, not an
invitation to choose defaults. Unrecognized text never gets a ready plan.

Dedicated offline acceptance tests must cover strict nested validation,
malformed/duplicate JSON, finite bounds and booleans, conservative interpretation,
policy binding and immutable serialization, hash changes, exact confirmation,
every allowed/forbidden lifecycle transition, verdict/status separation, and
result evidence requirements. All tests use synthetic policy/IDs and no saved
keys, live providers, Docker, evaluator changes or UI changes.
Future integration acceptance (service owner's responsibility): duplicate and
concurrent starts launch once; stale review fails before secrets; policy/root
changes invalidate admission; cancellation/restart preserve reservations/claims;
freeze gate holds; missing usage remains unknown; result reads never rerun work;
no hidden data or provider errors reach browser/model; baseline and artifacts
remain exportable and reversible. Module tests do not establish these service
properties.

Implementation validation: 14 dedicated experiment-spec tests pass on Python
3.9 and 3.12; the complete Python 3.12 suite runs 97 tests successfully with one
Docker-only test skipped. Ruff checks for the two new Python files and
`git diff --check` pass. Reproduce using the project's declared dev dependencies:

```sh
python -m unittest discover -s tests -p test_experiment_spec.py -v
python -m unittest discover -s tests -v
ruff check godseye/experiment_spec.py tests/test_experiment_spec.py
```
