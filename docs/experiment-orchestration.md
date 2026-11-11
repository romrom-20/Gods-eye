# Trusted local experiment orchestration

`godseye.orchestration` implements the reviewed
[experiment contract v1](experiment-contract.md). It adds five JSON POST operations
under `/api/v1/experiments/`: `plan`, `start`, `status`, `cancel`, and `results`.
Their exact messages, error codes, HTTP statuses and retry metadata are the
contract's messages; every response is `Cache-Control: no-store`. All operations
return HTTP 200 on success, including an idempotent start returning a terminal run.
The existing UI is unchanged.

This is a single local operator service. The OS user, filesystem, Docker daemon,
registered evaluator state, adapter image and worker implementation are trusted.
It does **not** provide production multi-user security. Keep writable serving on
loopback; Host, same-origin/cross-site checks, optional API bearer authentication,
JSON content type, and streamed body limits remain in the existing server boundary.
There is no CORS permission. A separate private database and local server/token
form the ID authorization scope. Hashes and idempotency keys are never credentials.

## Operator configuration

Live execution is opt-in. With no injected service or
`GODSEYE_ORCHESTRATION_DIR`, the experiment routes return `unavailable`; existing
lab routes continue to work. A configured service without a worker returns
`worker_unavailable` before start admission. Planning requires a registered policy.

Use Python 3.9–3.12 and the project's `server` dependencies. The production
`DockerWorker` requires a source checkout and the existing Docker Engine/Compose
setup described in [isolated-evaluator.md](isolated-evaluator.md). Build the three
existing images ahead of time with project name `isolation`:
`docker compose --project-name isolation -f isolation/compose.yaml build evaluator agent gateway`.
Run the service as a non-root OS user; root execution is refused. The worker never builds or pulls images. Do not
replace the agent image with a general coding agent. Its only tools remain the
existing evaluator `list`, bounded `read`, numeric `patch`, `evaluate`, and `freeze`.

Initialize a fresh private evaluator using the existing container initialization
flow with a fresh private generation seed. The directory must contain **all three**
participants (`unchanged`, `heuristic`, `agent`), with no probes, edits, freezes,
held-out reservations or prior orchestration claim. The policy is derived from
actual roots and evaluator settings; no client supplies it. Register it offline,
using operator-controlled absolute directories outside the repository and web root:

```python
from godseye.orchestration import Orchestrator

service = Orchestrator('/absolute/private/orchestration')
try:
    service.register('/absolute/private/fresh-evaluator',
                     baseline_id='pilot-001', suite_id='breakout-pilot', revision='v1')
finally:
    service.close()
```

Registration commits a manifest of participant/case/root identities and actual
tensor digests, excluding seeds, private labels, reference weights and credentials.
The manifest commitment binds the immutable policy. A separate private integrity
commitment also detects changes to seeds, labels, references and evaluator
configuration; it never enters the public spec or model context. Registration is operator-only;
there is no browser registration/configuration/command/path/endpoint operation.
Registering another fresh baseline selects it for subsequent plans. Earlier
registrations remain immutable and scoped. Duplicate IDs are rejected. One
registration admits **one run**, even if cancelled before execution. A new attempt
requires a new baseline ID and fresh private suite; never copy a revealed suite,
clear claims, or reset budgets. Register fresh suites before starting the service;
the database's lifetime OS lock prevents a second service owner.

Save the provider key through the existing `ProviderSettings` setup. Planning
requires an explicit provider/model/routing and all seven finite adapter limits;
saved defaults and available keys do not authorize spending. To serve:

```sh
export GODSEYE_ORCHESTRATION_DIR=/absolute/private/orchestration
# Optionally set GODSEYE_API_TOKEN for the existing local API boundary.
python -m godseye serve --host 127.0.0.1
```

The existing CLI's default host is also loopback. Alternatively, trusted Python
code can inject `Orchestrator(..., worker=DockerWorker(checkout),
settings=ProviderSettings(private_settings_directory))` into
`create_app(orchestration=service)`. The FastAPI lifespan owns service shutdown.
Operator paths and worker injection are never parsed from request bodies.
The existing Compose gateway binds port 8790, so `DockerWorker.capacity` is **one**;
do not run another evaluator gateway on that port. Compatible injected trusted
workers can advertise larger capacity, up to the service's limit of eight.

## Admission, identity and persistence

`AdmissionLimits` defaults are one running worker, four waiting admissions,
30 planning attempts/minute, ten new start attempts/minute, 120 status/result reads/minute,
128 unexpired ready drafts, and a 900-second review lifetime. Planning and start
counters are separate, persisted and scoped to the service, never chosen by a
prompt. Cancellation remains accessible when read/start throttles are exhausted.
Every request is at most 65,536 bytes; strict JSON rejects duplicate keys,
non-finite numbers, nesting beyond 16, unknown properties and boolean integers.
Goal length is at most 2,000 characters. The offline allowlist interprets goals;
raw text is neither persisted nor interpolated into the adapter's fixed prompt.

SQLite `synchronous=FULL` transactions bind canonical spec/hash, explicit exact
confirmation, idempotency tuple, fresh run ID, single-use baseline claim and queue
admission before scheduling. Unique key, draft and baseline constraints prevent
concurrent duplicate work. Repeating the identical start tuple retrieves its
persisted run even when throttled, full, expired or terminal. A changed tuple is
an idempotency/state/spec conflict. Ready drafts expire; review and plan again
explicitly. Expired unadmitted drafts may be removed during later planning.

Actual roots and evaluation configuration are verified both at start admission
and again at worker admission. Changed or used evaluator state fails before keys.
No provider or saved-key reads occur in plan, confirmation validation, status,
cancel or results. Start admission itself reads no key; only its confirmed worker
loads the selected saved credential. Queue exhaustion/worker unavailability admits
no run and reads no secret. `rate_limited` is HTTP 429;
`queue_full`/`worker_unavailable` are HTTP 503. Each has exactly the contract's
5-second retry guidance and `Retry-After: 5`. Other errors have no such header.
There are no backend inference retries, provider fallbacks, refunds or resume.

The service directory is mode 700 and its database is mode 600. It persists
spec/limits, confirmation, identity, execution state, accounting and private artifact
references. Every run has a dedicated evidence directory. The worker permanently
fsyncs an evaluator `.orchestration.claim`; the unchanged adapter independently
fsyncs `.agent-run.claim` and exclusively creates evidence. Preserve all of these.
Filesystem/Docker administrators can bypass local controls; this is not a
tamper-resistant spending boundary.

Browser reloads and result/status reads perform no execution. A connection lost
before complete body receipt admits nothing. A disconnect after admission can
lose the response while work continues. Preserve the original start tuple and
explicitly reconcile with that tuple/status; never generate another key or infer
that work did not start. Service shutdown stops further scheduling and requests
worker stop. Startup never submits persisted runs: it stops deterministic orphan
containers, marks unresolved runs `interrupted/process_lost`, reconciles durable
accounting and preserves claims/reservations. If local stop cannot be established,
new starts are fenced with `worker_unavailable`; retrying startup can attempt
cleanup again, without inference, key reads or reveal.

## Execution, cancellation and accounting

The worker reuses the unmodified Compose services, their networks, non-root users,
read-only roots, resource limits, secret mounts and narrow RPC gateway. It clears
inherited Compose/provider overrides, maps the confirmed provider/model/routing
and all seven limits directly to the adapter environment, and uses fixed argument
lists without a shell. A temporary mode-600 provider key is mounted as the existing
secret, never placed in command arguments, model input or browser output. It is
removed after local quiescence. Private evaluator state and admin tokens remain
outside the agent container. Host-side deterministic baselines run the existing
baseline adapter with separate participant tokens. Only trusted admin code
requests the held-out report, after every participant/case freeze and selection
audit. The repairing model never sees that report.

Provider requests/tokens/time/rounds/tools/per-response output ceilings retain
[the adapter's existing semantics](agent-budgets.md): reported cumulative token
limits can overshoot by one response, and these are not monetary guarantees.
Missing usage stops tools and further inference, retaining earlier known totals
with `usage_complete=false`. A durable unanswered request preserves
`request_in_flight=true`; counters never imply zero unknown consumption. The
Docker worker additionally stops the agent at its elapsed execution deadline.
Evaluator probe/forward reservations remain independent and failures consume them.

Cancellation commits `cancelling` and closes subsequent cooperative admission
checks. Queued work never starts its adapter. A running Docker agent is stopped
when its monitor observes the signal (50ms polling between bounded control calls).
A host baseline or held-out RPC already in flight can finish before the worker
acknowledges. `cancelled/user_cancelled` is published only after local work and
container cleanup are quiescent. Until then status stays `cancelling`; failed
cleanup becomes `interrupted`, never a false stopped acknowledgement. A
cancellation committed before final result publication wins, even if measurements
have finished. Provider execution/billing may continue remotely after local stop;
retain in-flight/usage uncertainty. Disconnecting the browser is not cancellation.

Phase is always `{name:"unknown",event_sequence:null}`. The existing evaluator
and adapter do not supply the contract's authenticated live reservation journal.
Neither provider prose, tool text, counts, elapsed time nor a report call is used
to invent a phase or percentage.

## Results and artifacts

Completion requires every expected case and participant report, all three final
arms with finite per-episode measurements, matching registered roots/settings,
controls present, and a selected candidate authorized in each case. A changed
selection requires a completed root comparison **before** its completed candidate
probe, with improvement over the root (ties retain root). The audit runs before
production reveal and again during result construction. Partial, failed or
interrupted measurements never become zero-score evidence or a completed verdict.

The trusted assembler pools agent-versus-case-root paired episode differences,
computes their mean and sample SE (`ddof=1 / sqrt(n)`), and takes the minimum
per-control mean difference. It uses the contract's `improved`, `no_improvement`,
and `inconclusive` rules. All other statuses have `not_evaluated` and no public
evidence. A valid negative result is completed. Summaries omit seeds, hidden
labels, paths, credentials and raw provider/tool errors.

Artifact IDs are scoped to their persisted run. Private manifest artifacts retain
original/selected IDs and tensor hashes; delta artifacts retain exact numeric
patches and parent lineage for rollback. Reports retain all participant state,
baseline arms, reservations and attempts. Adapter evidence references persist even
for failed/interrupted runs and preserve malformed/rejected tool attempts. No
browser export route is added: resolve artifacts only through a separately
authorized export facility, never expose paths or private reports wholesale.

## Offline verification

```sh
python -m unittest discover -s tests -p test_orchestration.py -v
python -m unittest discover -s tests -v
ruff check godseye/orchestration.py godseye/server.py tests/test_orchestration.py
git diff --check
```

Dedicated service tests use synthetic providers and temporary `ProviderSettings`
credentials, with the actual adapter and evaluator for budget/freeze behavior.
They exercise duplicate and concurrent starts, worker/queue bounds, immutable and
stale plans, root/configuration changes, missing usage, provider 429/disconnect,
cancellation acknowledgement, result completeness, private artifact references,
HTTP admission errors/retries, browser reconciliation and restart interruption.
The existing adapter redacts HTTP exception details; a provider 429 therefore
remains the safe terminal `provider_error`, without retries or leaked headers.
Specific provider reasons require trustworthy metadata unavailable in its evidence.
Offline tests do not establish Docker/OS isolation; the existing opt-in
`test_evaluator_container.py` remains the live isolation check.

Implementation validation: Python 3.12 ran 27 dedicated orchestration tests and
128 tests in the full suite successfully (one Docker-only test skipped). Ruff and
`git diff --check` pass; the new Python files also compile with Python 3.9. Live
Docker isolation was not exercised during this implementation.
