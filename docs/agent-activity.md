# Observed agent activity

This additive local feature records actual trusted worker/evaluator operations,
not model reasoning or intended next steps. It preserves experiment contract v1
and its browser validator unchanged. The new independent schemas live in
`godseye.activity_schema.SCHEMAS`. There is no provider/tool/browser write endpoint.

## Server attachment

`create_app` in `server.py` installs the router automatically:

```python
app.include_router(activity_router(orchestration, readonly=readonly))
```

For a separately constructed app/service the exact equivalent is
`app.include_router(activity_router(service))`. This factory is intended only for
`create_app`: it requires its existing `Boundary` middleware and writable job
state. Host, Origin, cross-site, bearer authentication, streamed 64-KiB body limits,
strict JSON and the common safe error envelopes apply. Readonly serving rejects
the operation even if the caller omitted the factory's `readonly` flag. A private
service database plus local server/token is the existing single operator scope;
run IDs, hashes, cursors and artifact IDs are never credentials.

POST `/api/v1/experiments/activity` accepts exactly
`{schema_version:1, experiment_id, spec_hash, after, limit}`. `after` is an integer
cursor from 0 to 2^53−1; `limit` is 1–100, with no implicit unlimited option.
Wrong/foreign run IDs and wrong reviewed hashes fail before journal access.
Activity/status/result reads share the existing read throttle. Success is HTTP 200
and includes exactly these fields:

- `schema_version`, `experiment_id`, `spec_hash`, `status` bind the snapshot.
- `available` distinguishes supported observations from missing instrumentation.
- `phase` follows v1; terminal execution always means unknown, with its retained
  sequence fence. Activity is never a verdict or completion percentage.
- `events` contains at most `limit` ordered records with `sequence`, `kind`,
  `operation`, `arm` and `count`. Names are fixed enums; the only measured
  metadata is a nullable bounded tensor read count (0–256). No private case IDs,
  tensors/values, seeds, labels, hypotheses, patches, references, paths, keys,
  provider bodies, usage-derived claims or held-out scores enter this endpoint.
- `next_cursor`, `high_water`, `has_more` support bounded pagination and replay.
  Repeating a cursor is a read of the same history, never a repeat operation.
- `gap` records lost or discontinuous observation. A gap consumes its returned
  cursor as unknown; a later contiguous trusted event can recover a live phase.
  Missing/wrong-scope/corrupt journals never synthesize successful events.

Every response is no-store. A fresh scoped journal has monotonic transactional
sequence allocation, starting at 1. SQLite `synchronous=FULL` commits reservations'
observations in the evaluator's private state; journal files are mode 600.
The admitted run/hash bind the journal before execution. The evaluator mounts
remain private and no RPC exposes the database. The browser loads 50 records at
a time and retains at most 200 loaded rows, with an explicit Load more action.
A reload reads the original admitted identity and history, without starting work.
Unsupported/missing routes and transport errors display Activity unavailable.

## Evidence and failure semantics

`RepairBenchmark` has optional trusted observer hooks. Probe events occur only
**after** its probe/forward reservation is durably saved; root identity comes
from the actual authorized case root, checked against the service's immutable
registration at admission. An edited candidate probe stays Trying an edit.
A numeric patch starts only after candidate membership and numeric patch
validation. A bounded read starts only after membership, tensor and slice checks.
A freeze event occurs only after its actual persisted selection. Authenticated
RPC requests can appear as requested/failed operations, but never as successful
inspections, edits or selections without completion evidence.

Only `Evaluator.report`, after checking **every** participant/case freeze, supplies
the observer used at persisted held-out reservations. Calling freeze/report alone
does not start Testing. All operations finish/fail before returning to the
adapter/provider. Unknown/provider-only intervals therefore remain unknown.
Overlapping observations are conservative unknown. Baseline and administrator
arms are named separately from agent operations.

Observer failure after a reservation cannot refund or redo it: the run fails,
the reservation remains consumed, and a durable loss marker makes the journal
unavailable. There is no recovery/resume/reset API for a broken writer. Reads
retain their last persisted fence on journal loss. Missing rows yield unknown,
never an invented intervening operation. After a gap is fenced, a later contiguous
observation can recover; the lost interval remains absent. Cancellation history
acknowledges local quiescence only; remote provider execution/charges may persist.

Worker terminal events fence out late observations and clear active operation
records. Restart recovery never resumes execution: it records process loss after
its existing local cleanup attempt and terminal status overrides the journal.
Old completed runs without journals remain empty/unavailable and unknown/null;
no history is reconstructed from provider evidence, usage, elapsed time or prose.
No new API fields were added to existing v1 responses: only their already-defined
`phase` values now reflect observed events.

## UI and offline evidence

Local live UI offers expandable observed history and an explicit Download
checkpoint action for a validated completed result manifest. Downloads use the
existing authorization header and one POST to `/api/v1/experiments/export` with
`{schema_version:1, experiment_id, artifact_id:candidate_manifest_id}`. Duplicate
in-flight clicks are disabled; failures retain the result and ask for an explicit
retry. The browser saves the JSON attachment without interpreting numeric data.
The exporter validates the artifact before returning it; the independent reload
path checks numeric data, delta preconditions and hashes. See [checkpoint export](checkpoint-export.md).

Recorded demo and mock controllers return before installing activity or download
handlers; their controls remain hidden/disabled. They make no added API calls.

Run with the existing offline dev environment:

```sh
python -m unittest discover -s tests -p test_activity.py -v
python -m unittest discover -s tests -v
python -m unittest discover -s tests/browser -p test_ui_contract.py -v
node --test tests/ui/*.test.cjs
PYTHONPATH=. python tests/browser/activity_backend.py
# Separate terminal, test fixture only (port 8881):
ego-browser nodejs < tests/browser/activity_journey.cjs
```

The activity tests execute the actual scripted adapter, real evaluator, development
reservations, all-freezes gate and tiny capped held-out rollouts. They check live
phase, finish reset, failed reads/patches, cancellation/provider failure, abrupt
subprocess exit after a persisted reservation, terminal replay fencing, retained
reservations, cursor gaps, later contiguous recovery, redaction/bounds, HTTP
boundary checks and old-run compatibility. The existing process-loss acceptance
also executes the service's restart/no-resume path with this instrumentation.
Temporary credentials only; outbound provider transport throws.

The browser fixture runs the real static app, service, journal and export route.
It checks history, pagination, terminal reset, reload without another worker/key
read, durable row loss, and explicit download errors caused by controlled fixture
manifest corruption. After restoration, it downloads four real checkpoint pairs
and independently reloads them, matching original and selected hashes against
both the artifact and fixture weights. Fixture-only routes never ship in production.
The browser fixture selects unchanged roots; changed selections are covered by
separate export tests. Neither demonstrates intelligent repair quality.

Integration validation on 2026-11-11: full Python discovery ran 193 tests with
17 opt-in skips; all 11 activity tests, 8 export tests and 48 Node UI tests passed.
The opt-in scripted DockerWorker suite ran separately: all 14 tests passed with
no skips, including scoped durable activity, private journal permissions,
reservation/freeze ordering, replay and terminal fences. Ruff, Python 3.9
compilation and whitespace checks passed. No saved operator keys or paid provider
calls were used. Test images were rebuilt through the controlled Docker setup.

Existing installations must rebuild evaluator images to obtain evaluator activity;
older images can show only observed worker lifecycle and unknown evaluator phases.
Real-provider compatibility and repair quality remain unverified. Temporary browser
servers and downloaded fixtures were cleaned up. No public deployment occurred.
