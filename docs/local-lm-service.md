# Trusted local Qwen browser service

Implemented against `docs/lm-browser-service-contract.md` v1. This is a trusted
loopback service for the existing fixed JSON TaskSpec, with a replaceable process
adapter; it is not an OS sandbox or a hosted multiuser boundary. No remote
backend, paid provider, download, credentials or arbitrary executable operations
are exposed. The static export and existing Breakout APIs keep their behavior.

## Operator setup

Use a source checkout containing `experiments/local_lm_task.py`. The inference
adapter sets its working directory to that checkout and invokes the explicitly
configured interpreter with `-m experiments.local_lm_task --execute --worker`.
This source-discovery arrangement is tested; wheel-only execution is not claimed.
The web server can use its existing base/server environment, without Torch.

Before starting the server, set all three operator-only variables to absolute
paths. The evidence directory must be private (0700), persistent, and disjoint
from the weight cache. Keep the same evidence directory when restarting: changing
it to bypass a live ownership fence is not supported.

```sh
# Replace these paths with existing operator-owned locations; this downloads nothing.
export GODSEYE_LM_CACHE=/absolute/existing/pinned-qwen-cache
export GODSEYE_LM_PYTHON=/absolute/existing/isolated-env/bin/python
export GODSEYE_LM_DIR=/absolute/private/lm-browser-evidence
mkdir -m 700 "$GODSEYE_LM_DIR"
python -m godseye serve --host 127.0.0.1 --port 8797
```

The interpreter needs Python 3.9–3.12 and the existing pinned local runtime:
Torch 2.6.0, Transformers 4.51.3, safetensors 0.5.3, numpy 2.2.6,
huggingface-hub 0.30.2 and tokenizers 0.21.1. Dependencies are inspected through
`importlib.metadata` in a bounded three-second isolated interpreter probe, cached
for 30 seconds. Readiness stats allowlisted cache files and reads only bounded
source metadata. It never reads/hashes model weights, imports Torch, downloads,
loads a model or generates text. The actual worker verifies every pinned file
hash within the execution deadline before loading. Consequently `available:true`
is admission readiness, not a claim that the full weight hashes already passed.
Missing configuration or dependencies produce sanitized, actionable errors.

Open `/lab#language-model` with the UI slice installed. Start requires an explicit
reviewed preview. Page load, preview, status, reconciliation and server restart
start zero inference jobs. Existing Host/Origin/cross-site/JSON-size checks and
optional `GODSEYE_API_TOKEN` run before the LM router. Read-only mode disables
preview, admission, cancellation and export; `/resolve` remains read-only.

## API and persistence

All routes use `/api/v1/lm` and version 1 JSON:

- `GET /capabilities`: configuration readiness, fixed model/revision and ceilings.
- `POST /plan`: finite phrase parser and a durable opaque ten-minute preview.
- `POST /jobs`: transactional exact plan/spec/key admission; 202 initially, 200
  for identical previous admission, even after preview expiry.
- `POST /resolve`: exact key/spec lost-ACK reconciliation; 404 means no admission,
  409 means a key/spec conflict. It never starts a process.
- `GET /jobs`, `GET /jobs/{id}`: persistent newest-first history and exact Job schema.
- `POST /jobs/{id}/cancel`: idempotent request; stays cancelling until exit/wait.
- `GET /jobs/{id}/result`: terminal evidence only, otherwise 409.
- `POST /jobs/{id}/export`: bounded attachment, `kind:evidence|selected_delta`.

Requests reject duplicate keys, unknown fields, incorrect types (including boolean
versions), invalid UUIDs, nonfinite JSON and oversized payloads. Public responses
are capped at 4 MiB; journals at 16 MiB/1024 events; individual journal events at
256 KiB; model output bounds remain those of `task_suite.validate_record`.
Unused previews are bounded at 64 and expire. Admitted preview/spec bindings remain
durable. History/admission is capped at 20 runs and 256 MiB in the evidence directory,
with a 32 MiB admission reservation for a new run, no silent evidence deletion
and no execution backlog. The monitor preserves room for bounded final snapshots
and transactional writes before the hard quota. Weight-cache bytes are
excluded, including rejecting overlapping cache/evidence configuration. A monitor
also stops a worker at the evidence quota. This is a trusted local filesystem quota,
not adversarial OS disk isolation; approved output is independently bounded.

SQLite FULL synchronous transactions commit the job ID, exact preview/spec/key
binding and reservation before launching. Concurrent identical starts launch once;
changed tuples conflict. No automatic retry or resume occurs. Plans and jobs are
separate so expiry never loses an admitted idempotency binding. Raw user request
text is not stored. The process adapter seam consists of metadata `readiness()`
and `launch(output, stage, guard_fd)` returning an owned process; a future sandbox
adapter must preserve these lifecycle and publication guarantees rather than
merely replace the command. No such remote adapter exists in this slice.

## Process ownership and evidence

The service bypasses the CLI's outer supervisor and launches its leaf task process
directly. The first model process is exited and waited before a selected-delta
fresh-model verification process is launched, with no extra generations. There is
one resident model, two intra-op threads and one inter-op thread. The existing
runner owns attempts, baselines, exact rollback, durable freeze and heldout order;
the service never implements a different score or selection recipe.

A POSIX exclusive flock fences the service/evidence directory. Each leaf process
inherits the open lock descriptor. If the server is killed, that descriptor keeps
replacement admission blocked while its worker survives. Recovery never signals
stored PIDs, guesses exit from a PID lookup or automatically resumes. After the
fence can be acquired, abandoned reservations become interrupted; partial journal
records remain readable. Keep the private directory/lock in place while anything
may own it. An operator must investigate an ownership-unknown state; moving the
directory or deleting the lock is not a safe workaround.

The aggregate limit is 1800 seconds from worker preparation through verification
and cleanup, including loading and hashes. The monitor reserves two seconds for
cleanup, requests SIGINT, allows at most one second, then kills and waits with a
one-second bound. Cancellation wins over completion until terminal publication.
Shutdown uses the same cleanup. If cleanup cannot be established, the job is
interrupted with `cleanup_unknown` and admission is fenced, never acknowledged as
successfully cancelled. A process can survive only under this explicitly unknown,
blocked state; it cannot cause a second service worker to be admitted.

The control service validates the journal hash chain and reservation/result
bindings, recomputes evaluation with the existing scorer, verifies freeze ordering
and durable identity, matches the final report digest, and checks original
rollback boundaries. It exposes only validated public Attempt fields and recomputed
report fields plus safe freeze/selection hashes. It never exports worker commands,
environment, logs, exception text or local paths. A malformed report fails closed,
retaining valid journal-prefix attempts. Unknown usage stays unknown.

`completed` means a complete valid evaluation, including `no_improvement` or
`inconclusive`; it is not a quality promise. Token-capped development is
`failed/budget_limited` with `not_evaluated`, never a heldout success. Other public
reason codes distinguish `deadline_exceeded`, `worker_failed`, `worker_crash`,
`evaluation_incomplete`, `rollback_failed`, `invalid_evidence`, `storage_full`,
`cancelled_by_user`, `service_shutdown`, `service_restarted`, `worker_launch_failed`
and `cleanup_unknown`. These codes are safe for UI explanations; raw exceptions
are intentionally not returned.

Selected-delta export additionally requires a completed run, a frozen actual
weight selection, the exact approved candidate operation, a validated numeric
delta/content hash, matching task reload/rollback evidence and matching independent
fresh-model verification hashes. Unchanged winners and unused candidate files
never produce selected exports. Attachments include the pinned local delta-loader
reload and context-manager rollback instructions. Filesystem paths from HTTP are
never used to select artifacts; job identity authorizes a fixed stored artifact.

## Verification recorded for this slice

All new acceptance uses explicit **synthetic** worker processes and temporary
service/cache directories. Synthetic sparse cache files are metadata fixtures,
never weights. Synthetic selected-delta hashes are test identities, not pretrained
verification or an inference-quality result. No pretrained execution, downloads,
provider calls, dependency changes or access to running user servers occurred.
The earlier scientific run and its artifacts remain unchanged.

Commands executed in the existing isolated server environment:

```sh
/tmp/godseye-goal-contract-venv/bin/python -m unittest discover -s tests -p test_lm_service.py -v
/tmp/godseye-goal-contract-venv/bin/python -m unittest discover -s tests -p test_platform.py -v
/tmp/godseye-goal-contract-venv/bin/python -m unittest discover -s tests -p 'test_lm_local*.py' -v
/tmp/godseye-goal-contract-venv/bin/ruff check godseye/lm/service.py godseye/lm/service_api.py godseye/lm/service_worker.py godseye/server.py tests/test_lm_service.py tests/fixtures/lm_service/worker.py
```

Service tests cover exact capability/preview/job/result schemas, duplicate
simultaneous starts, changed plan/spec conflicts, lost ACK, expiry, bounded preview
and history admission, evidence quota, strict JSON, readonly/Host/Origin/token/body
protections, actual SIGINT-resistant child kill-and-wait on cancel/deadline,
shutdown, crash/restart inherited-lock fencing, partial reservations, launch and
unknown-cleanup failure, sanitized errors, complete negative/no-selection,
incomplete development, rollback failure, malformed results and independently
verified selected-delta fixture paths. A real uvicorn server binds an OS-selected
loopback port and uses HTTPX for concurrent starts, exact resolution and actual
child cancellation; it never binds the user's existing service ports.

Core server/platform tests: 10 passed. Existing local-runner/runtime tests: 24
collected, 16 passed and eight optional Torch numeric tests skipped in the base
server environment. Focused service tests: 14 passed (including all seven evaluation fixture modes).
Lint and `git diff --check` passed. The server environment emits a pre-existing Starlette
HTTPX deprecation warning; no environment modifications were made.

Remaining integration: the coordinator must merge the independent UI slice and
perform its separately labeled browser/service integration check on a dedicated
port. This slice establishes control-plane behavior with synthetic evidence; it
does not rerun, improve or replace the earlier incomplete Qwen quality experiment.
