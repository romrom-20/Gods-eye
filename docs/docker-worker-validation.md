# DockerWorker container validation

This validation exercises `godseye.orchestration.DockerWorker` through a real
`Orchestrator`, Docker Engine and Compose. It is separate from the older
`test_evaluator_container.py`, which launches Compose directly. Read
[experiment orchestration](experiment-orchestration.md) and
[evaluator isolation](isolated-evaluator.md) for the trust boundary and operation.

## Reproduce

Use a non-root operator, Python 3.9–3.12 with `.[dev]` installed, a running local
Docker daemon and an unused loopback port 8790. Do not run another evaluator or
worker suite concurrently. The explicit opt-in builds the three `isolation-*`
images and a separate `godseye-worker-scripted:validation` image. Build dependencies
may use the network; provider inference does not.

```sh
GODSEYE_CONTAINER_TEST=1 python -m unittest discover -s tests -p test_docker_worker.py -v
# Also exercise the older Compose boundary and all offline regressions:
GODSEYE_CONTAINER_TEST=1 python -m unittest discover -s tests -v
ruff check godseye/orchestration.py tests/test_orchestration.py tests/test_docker_worker.py tests/fixtures/docker_worker/scripted_provider.py
git diff --check
```

Without `GODSEYE_CONTAINER_TEST=1`, live worker tests skip. With opt-in, daemon or
build failures are failures, rather than evidence of isolation. Root operators
skip because the production worker refuses root. Tests use fresh temporary
private suites (four cases per participant, two one-step episodes), service
databases, evidence and dummy credentials. No saved operator credential is read;
`DummySettings` supplies only a hard-coded dummy value. Test containers, networks,
temporary key files and private data are removed. Built images/build cache remain
available locally, as in the existing Compose test.

## Scripted provider boundary

The only worker customization is a trusted Python subclass overriding `_images()`
to select the separate test agent image. Production selects `isolation-agent`;
neither the production image nor its adapter contains the fixture script. No
test-provider environment variable, request option, provider endpoint, source
mount or server route is introduced. Unknown public plan fields for worker,
image, provider URL, script and Compose configuration are rejected by the exact
contract. A model name such as `scripted-complete` has no special meaning in the
production adapter.

The test image derives from the actual agent image, adds the fixture entrypoint,
replaces only `adapter.post` for provider URLs, then calls the existing
`adapter.main()`. Argument parsing, key loading, routing, budgets, evidence and
claim persistence, evaluator HTTP tools and worker result assembly remain real.
An additional `urlopen` guard rejects every network request except the fixed
evaluator RPC URL. The script checks the dummy key, configured output ceiling,
tool allowlist and absence of secrets in model input. It lists cases and freezes
each root. It demonstrates protocol completion, not intelligent repair.

## Coverage and fixes

The 14 dedicated tests cover:

- Actual worker admission and launch, deterministic run/project identity, pinned
  evaluator/gateway images and selection of the separate test agent image. A
  deliberately absent evaluator image fails under `--pull never` without agent
  evidence, and cleanup removes the temporary key.
- Non-root UID/GID, read-only roots, dropped capabilities, no-new-privileges,
  memory/CPU/PID configuration and no-exec scratch mounts on all three services.
  Agent mounts consist only of evidence and two read-only single-file secrets;
  evaluator private state is separate and gateway has no mounts. In-container
  writes to code/secrets fail and private state/admin token/socket paths are absent.
- Internal evaluator networking, separate agent provider and gateway operator
  networks, loopback gateway publication, and denied evaluator external TCP egress.
- Removal of inherited provider/Compose overrides; mapping of all seven confirmed
  limits into the actual container; per-response output ceiling in provider input;
  real adapter stops for requests, input tokens, total output tokens, tools and
  rounds. The worker deadline stops a provider blocked inside the agent container.
- Full baseline/agent freeze, trusted held-out evaluation, result assembly and
  durable claims. Temporary provider keys are mode 600 within a mode-700 run
  directory. Preserved run artifacts contain neither the dummy key nor participant
  or admin tokens.
- Cancellation while a provider request is blocked, terminal acknowledgement only
  after container/network removal, no held-out report, and durable uncertainty
  (`request_in_flight=true`, `usage_complete=false`). Missing usage and scripted
  provider exceptions also stop and clean up without leaking exception secrets.
- Abrupt service-process kill with the real agent/evaluator/gateway left running.
  Startup removes the orphans and key without a key read, provider resubmission or
  reveal; status becomes `interrupted/process_lost`. The agent evidence is unchanged
  and both one-use claims survive.
- Injected cleanup timeout after cancellation produces `interrupted/process_lost`,
  retains the key pending quiescence and fences admission. A subsequent service
  startup performs real Docker cleanup and removes the retained key.

Live testing found two operational issues, now fixed. The worker's daemon health
probe used `docker info`, which hung probing unrelated CLI plugins on this host;
`docker version --format '{{.Server.Version}}'` checks daemon availability without
that scan. Recovery used Compose `down` without the agent profile, leaving the
provider network behind even after the named agent was removed. Recovery now
enables the agent profile, and tests require zero containers **and** networks for
the run before accepting cleanup.

## Observations and limits

Validation recorded on 2026-11-11: macOS arm64, Python 3.12, Docker Desktop 4.99.0, Engine 29.9.3
(Linux arm64), Compose v5.7.0. The dedicated worker suite passed all 14 tests after
the fixes. The initial failing runs exposed the leftover provider networks; those
test-owned networks were explicitly removed. A macOS `/var` versus `/private/var`
path alias in a test assertion was also corrected by resolving fixture paths.

Final verification ran `GODSEYE_CONTAINER_TEST=1 python -m unittest discover -s
tests -v`: **165 tests passed in 86.412 seconds, no skips**, including all 14 new
worker tests and the older Compose container test. The 27 offline orchestration
tests also passed separately before the final full run. Ruff on the four changed
Python files and `git diff --check` passed. The Python files compile with Python
3.9 as well; their runtime tests used Python 3.12. Final `docker ps -a` was empty
and `docker network ls` contained only Docker's built-in bridge, host and none
networks. Static UI files were not edited.

No real provider compatibility, remote cancellation/billing behavior, intelligent
repair quality or production-scale evaluation is established. The test output
ceiling is checked as a request parameter; no remote provider enforces it here.
Cumulative token stops retain the adapter's one-response overshoot semantics.
Resource caps are inspected in Docker configuration, not stress-tested with OOM,
CPU saturation or PID exhaustion. Linux bind-mount ownership outside Docker
Desktop, malicious images/operators, container escape, daemon/host reboot,
disk/power loss, and network partitions are unverified. Cleanup failure is an
injected control-command timeout; abrupt service death is real SIGKILL. Existing
offline tests cover queue/concurrent admission and contract behavior; this live
suite serializes runs to preserve the fixed-port boundary.
