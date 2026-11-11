# Goal experiment acceptance

This suite owns new acceptance files only. It follows
[experiment-contract.md](experiment-contract.md) and
[goal-experience.md](goal-experience.md). Backend, evaluator, adapter, existing UI,
and existing tests are unchanged.

**Release acceptance is incomplete.** This checkout has the pure v1 contract and
mock UI. The provisional service can be exercised separately in the backend
owner's worktree. The real browser-to-service journey and trusted live phase
journal remained blocked in this initial suite. Backend checkpoint download now
has independent acceptance coverage in [checkpoint-export.md](checkpoint-export.md);
browser download UX is separate. A passing mock or contract test must not be
reported as a passing real experiment journey.

## What executes

- `tests/test_goal_journey_acceptance.py`: pure planning, exact review/confirmation,
  unsupported requests, evidence interpretation and retry/phase semantics. Runs
  today; synthetic summaries are schema fixtures, not measured results.
- `tests/ui/goal_acceptance.test.cjs`: executes the existing mock controller with
  minimal DOM/tab-storage adapters. Network, saved-key access, timers and downloads
  throw. Checks the entire sample journey, all option/limit review invalidation,
  duplicate Start, failures, reload and inert markup. Runs today; not browser QA.
- `tests/test_goal_service_acceptance.py`: independent HTTP/service tests with
  actual assertions. Each explicitly skips with `BLOCKED: godseye.orchestration
  not integrated` when the backend module is absent. Once present, incompatible
  APIs and failed assertions fail; they are not silently converted to skips.
- `tests/goal_acceptance_support.py`: acceptance-owned scripted worker. Uses the
  real adapter and evaluator, temporary fake provider settings, one instance per
  fault family, two episodes, one step, two development probes and four reserved
  development forwards per case. Includes unchanged/heuristic arms and the global
  freeze gate. This deliberately tiny run checks mechanics, not research quality.
  Root selection gives an actual zero paired difference and `no_improvement`.
  No successful repair is fabricated.

All service state, keys, evaluator data and claims are in temporary directories.
Provider callbacks are scripted; outbound HTTP/socket paths throw. No default
provider settings, user's saved keys, paid calls, Docker, or provider discovery
are used. The crash subprocess has the same outbound-transport prohibition and
exits deliberately after a real development probe persists. Temporary data is
cleaned on success and failure. This in-process worker does not prove production
container isolation, remote billing cessation or real-provider compatibility.

## Acceptance scenarios

### A01 — Describe, review, explicitly start

Given `Improve Breakout score` and an explicit programmer selection and all seven
finite limits, planning returns a server-issued ready draft/spec/hash. Review
shows Breakout as the editable target, registered roots as baseline, held-out
rules, regression criteria, provider/model/routing and every selected limit.
Planning and review make no provider contact and read no credentials. Neither
navigation, saved keys nor a ready plan is authorization to launch.

Only `confirmed: true` with the exact reviewed draft/hash and a retained
idempotency key may admit work. False/numeric confirmation, changed limits,
stale hash, changed roots or changed policy fail before a key read. Editing any
choice requires a new review and confirmation. Tests: contract
`test_supported_goal_review_exact_limits_and_explicit_start`; service
`test_stale_review_unconfirmed_and_changed_limits_fail_before_secrets`,
`test_root_mutation_after_review_invalidates_admission`; mock A01/A02.

### A02 — Follow actual progress

After admission, status and usage come from one durable run. Before reliable
observations exist, show execution status and “Activity unavailable”. A provider
request starting, narration, elapsed time or budget consumption cannot establish
“Checking the original”, “Trying an edit” or “Testing the result”. Never estimate
completion percentages.

The contract projection test checks root reservation, operation finish, authorized
edit admission and held-out reservation, with sequence fencing on observation
loss and terminal state. Existing contract tests additionally cover gaps,
replays and wrong-run/spec events. The service reconnection test currently
asserts `phase: {name: unknown, event_sequence: null}`. **Known live phases remain
blocked on trusted worker/evaluator instrumentation and a durable journal.**
Then test one real event at a time: duplicate/older sequences do not regress;
a gap/lost observation becomes unknown while retaining its fence; a contiguous
later event can recover; terminal state overrides stale phase. Freeze calls alone
must never advertise testing. These scenarios have no fabricated service pass.

### A03 — Inspect an honest outcome

Complete measurements for every expected participant/case and all controls must
precede `completed`. Every changed selection needs an earlier root comparison.
Freeze all selections before any held-out rollout. Derive paired mean/sample SE,
minimum control mean delta and verdict from complete trusted measurements;
retain limitations, attempts, errors and baseline arms privately. Completion does
not guarantee improvement. Repeated results/status reads do not rerun work or
reveal held-out feedback to the provider.

The scripted supported journey checks actual tiny rollouts and `no_improvement`,
nonempty evidence IDs, baseline identity and immutable roots. Tests:
`test_supported_journey_review_start_actual_measurement_and_keep_original`,
`test_held_out_report_is_blocked_until_every_selection_freezes`. Pure tests
exercise improved/inconclusive/control-regression rules using synthetic summaries;
those cases do not establish service report provenance or an improved experiment.

### A04 — Keep original or obtain an available edited checkpoint

Keeping the original must leave both the public `paper` checkpoint and every
registered root byte/content identity intact. No repair, cancellation, export,
reload or failure may overwrite them. Service tests compare tensor digests before
and after the supported journey, budget stop and cancellation. Mock A01 checks
its honest acknowledgment that it changed nothing.

**Backend checkpoint export is implemented and independently tested** in
[checkpoint-export.md](checkpoint-export.md) and `tests/test_checkpoint_export.py`.
The separate authorized endpoint returns bounded usable numeric artifacts for
completed trusted selections. Its scripted changed selection passes actual
root-before-candidate development comparisons, fresh-process reload, hash checks,
paired held-out evaluation equality and rollback. Root selections are explicitly
unchanged. Browser download integration remains a separate acceptance gate; public
evidence IDs alone are not downloads or authorization.

The export checks require an authorized numeric edit that meets selection rules
or an independently registered immutable completed-run fixture, with:

1. Comparison identifies original and selected hashes for every case; exact patches
   and immutable parent lineage are available, even for a negative measured result.
2. The selected checkpoint or a losslessly reconstructable numeric delta downloads
   through a scoped operation. Reload it independently and verify shape, finite
   values, content hash and declared base. A report JSON alone is insufficient.
3. Applying the delta to the authorized original reproduces the selected hash;
   rollback returns the original hash; the stored original remains untouched.
4. Missing/tampered/foreign artifact IDs fail safely without path disclosure,
   baseline fallback, checkpoint fabrication or execution. Repeated downloads are
   reads; another authorization scope cannot retrieve the artifact.
5. Exported model/delta/report omits credentials, seeds, hidden families/labels,
   reference weights, private paths and raw provider text, including on errors.

Do not implement a fake export in the acceptance fixture to turn this gate green.

### A05 — Unsupported or malicious requests

Qwen editing, training and unrelated targets are rejected. Ambiguous Breakout
wording and appended instructions require clarification. No runnable draft/hash
is returned and no inference/key read occurs. Missing selection/limits and added
credential/path/seed/patch fields fail strict validation. The browser preserves
its draft; markup remains inert. Tests: contract unsupported test, service
`test_unsupported_requests_missing_selection_and_injected_fields_spend_nothing`,
mock A03/A06.

### A06 — Double-click Start

Two clicks or sixteen concurrent identical admissions yield one run and one
worker. Replaying after completion returns that same run. A different key for
an admitted draft is `state_conflict`; reusing a key for another draft/hash is
`idempotency_conflict`. No second spend and no automatic fallback. Test:
`test_double_click_start_and_concurrent_replays_admit_once`; mock A01.

### A07 — Service/provider rate limits

Service throttling returns 429, `Retry-After: 5`, and the exact fixed retry envelope
with at most three same-request attempts. It reads no key and admits nothing.
A provider 429 is an execution failure after a consumed request, never permission
to repeat inference or switch provider/model. Raw upstream text stays private.
The existing adapter can redact the HTTP status, so generic `provider_error` is
accepted when no trusted 429 signal remains. Test both rate-limit service tests;
mock A03 only illustrates the message. **A real browser's bounded retry loop and
unknown-admission reconciliation remain blocked on browser integration.** A lost
start response must retain its original tuple, never silently create a new key.

### A08 — Exhausted budgets and unknown usage

A scripted endless list request stops at its one-request ceiling with
`failed/budget_exhausted/not_evaluated`, retained usage, null evidence and unchanged
roots. Missing usage causes the existing adapter to stop; known totals stay known
and `usage_complete` stays false. Zero known tokens never means zero charges.
Tests: service budget/missing-usage tests. All seven limits are reviewed exactly;
existing adapter-budget tests exercise the underlying cumulative limits. No hard
dollar cap, watchdog or remote cancellation guarantee is implied.

### A09 — Cancel, queued and in flight

Queued/running cancellation first becomes `cancelling`. While a scripted provider
request is held behind a barrier, repeated cancel remains cancelling with an
in-flight request and unknown usage. Only after local quiescence acknowledgment
may it become `cancelled/user_cancelled`; evidence is null and requests are not
refunded. Claims remain consumed. A queued cancellation reads no second key;
replaying that admission does not recycle it into a new run. Tests: both cancel
tests; mock A04 illustrates cancellation but does not acknowledge a real worker.

### A10 — Browser reload/reconnection

Mock A05 restores text, programmer preferences and numeric limits, discards
confirmation (including forged saved confirmation), marks an active walkthrough
interrupted and never resumes. The service test creates another HTTP client and
reads the same active run without relaunching, then reads the persisted result.
**This is API reconciliation, not a real browser reload test.** Once connected,
reload an actual page at review, queued, running, cancelling and terminal states;
verify retained run identity, exact start tuple and safe status/results reads,
with no inference retries or renewed consent. Simulate lost start acknowledgment.
Real browser storage/reconciliation behavior is still blocked.

### A11 — Server restart

A child process exits abruptly with a distinctive exit code after the first real
root probe has persisted. A new service must report
`interrupted/process_lost/not_evaluated`, no evidence or known phase, and identical
probe/forward reservations and evaluator claim. Idempotent start replay returns
the interrupted identity with no key read or worker execution. Test:
`test_abrupt_server_process_loss_interrupts_without_refund_or_resume`. This proves
local service recovery with the scripted worker; production container recovery
and a browser reconnecting after restart remain separate gates.

### A12 — Missing evidence/provider failure

Missing selections, a removed final score array and an upstream exception all
produce terminal failure with `not_evaluated` and null evidence. No missing value
is filled with zero. The upstream exception contains a fake credential and private
marker, neither of which may reach a response. Tests: incomplete selections,
missing final scores, provider exception and contract evidence tests. Artifact
loss after completion must also fail safely when export exists (A04).

### A13 — Credentials/private data stay server-side

Every experiment HTTP success/error response used by the suite is checked with
the exact v1 validator and scanned across body and headers. Canaries include the
temporary provider credential, all real temporary evaluator tokens, private case
IDs, an injected private-state marker, upstream error marker and temporary root
path. Forbidden private keys are checked recursively. Scripted provider contexts
are separately checked for credentials, private marker/path and seed/reference
fields; opaque case IDs are permitted only in evaluator tool contexts.

Auth, Host, Origin, cross-site and nonexistent scoped-ID failures are also checked.
This verifies the tested experiment routes, not every legacy API or a formal
noninterference proof. Scoped export responses now have separate HTTP and
redaction checks in `tests/test_checkpoint_export.py`; a connected browser's actual
network/storage remains a separate acceptance gate. A public token/hash/ID is
never treated as authorization by the acceptance scenarios.

## Commands and evidence

From this checkout with the project's dev dependencies installed:

```sh
python -m unittest discover -s tests -p 'test_goal*acceptance.py' -v
node --test tests/ui/goal_acceptance.test.cjs tests/ui/goal_experience.test.cjs
ruff check tests/goal_acceptance_support.py tests/test_goal_journey_acceptance.py tests/test_goal_service_acceptance.py
```

Use the backend owner's implementation without copying/editing its files:

```sh
# Run outside either source root to avoid mixing editable-install import paths.
cd /tmp
PYTHONPATH=/Users/samanseshadri/orca/workspaces/Gods-eye/experiment-orchestration \
  /tmp/godseye-orchestration-venv/bin/python -m unittest discover \
  -s /Users/samanseshadri/orca/workspaces/Gods-eye/experiment-acceptance/tests \
  -p test_goal_service_acceptance.py -v
```

These are local verification paths, not test requirements. After merging the
backend, ordinary discovery runs the same service tests automatically. CI currently
names only the existing UI test file; explicitly include the new UI command when
integrating (no existing workflow was edited here).

Recorded observations and source fingerprints are in
[experiment-acceptance-results.txt](experiment-acceptance-results.txt). The API
coordination request, inspected provisional interface and unacknowledged message
limitation are in [acceptance-api-coordination.md](acceptance-api-coordination.md).
No live-provider result, deploy, formal new-user study or full browser acceptance
is claimed. Those are outside this no-paid-calls verification.
