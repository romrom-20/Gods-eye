# Acceptance/API coordination

Acceptance owner: `experiment-acceptance`; backend owner:
`experiment-orchestration`. Acceptance changes are new files only. Backend and
existing UI files remain owned by their respective agents.

On 2026-11-10, attempted Orca `orchestration send` to the backend workspace and
its structured chat handle. Both returned `terminal_not_found` (no live pane or
Run/Dispatch mailbox). Native chat fallback could not run because Accessibility
permission is absent. **No reply/acknowledgement was received.** This is an open
coordination limitation, not agreement from the backend owner.

Read-only inspection of the backend owner's in-progress files established this
provisional integration surface (not yet merged into this checkout):

- `godseye.orchestration.Orchestrator(directory, worker=..., settings=...,
  limits=..., clock=...)`; `register(directory, baseline_id=..., suite_id=...,
  revision=...)`, `plan`, `start`, `status`, `cancel`, `results`, `close`.
- Injected worker: `capacity`, `available()`, `recover(row, registration,
  directory)`, `execute(row, registration, directory, settings, check, accounting)`.
  Execution must acknowledge quiescence before returning; `check()` observes
  cancellation. `accounting()` consumes the existing adapter evidence journal.
- `create_app(Store(tempdir), orchestration=service, token=...)`;
  POST `/api/v1/experiments/{plan,start,status,cancel,results}` carries exact v1
  messages, with the common contract error/retry envelope.
- `AdmissionLimits` permits a fake clock and low throttle ceilings.
- Status currently returns `phase: {name: unknown, event_sequence: null}`;
  there is no authenticated durable phase journal yet. Do not fabricate phases.
- No scoped checkpoint/artifact download operation was found. Public evidence
  IDs alone do not establish that a usable edited checkpoint can be obtained.

Request to backend owner: confirm this interface, notify acceptance of changes,
provide a durable trusted phase-event hook and scoped immutable artifact export
with a verified reload/rollback path when implemented. Acceptance provides its
own scripted worker and never imports the backend owner's test fixtures. The
scripted worker is an in-process test fixture, not production isolation evidence.

Independent verification subsequently passed all 18 service acceptance tests on
Python 3.9.6 and 3.12.14 against backend commit
`3f5ce3933a78febfb42146ef115d34a62eaf433f`. Its inspected source hashes remained
unchanged during verification. A backend worktree comment points to this request
and the test suite; comment updates succeeded, but chat delivery and owner
acknowledgment remain unproven. No backend files were copied or edited.
