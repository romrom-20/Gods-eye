# Evaluator implementation and baseline-only observations

Completed: separate evaluator service, authenticated participant-scoped RPC,
container launch configurations, source-free restricted tool-calling agent
adapter, persistent budget/freeze enforcement, deterministic HTTP integration
and failure tests, preregistration, and retained baseline evidence.

Observed execution: [saved JSON](../experiments/evaluator-pilot-results.json)
comes from `experiments.evaluator_pilot` under the same OS user. It verifies the
protocol and runs actual CPU MinAtar episodes. It is **not** an isolated experiment.
No real agent ran in that baseline check: `OPENAI_API_KEY` was absent, and
Docker/Podman were not installed at the time.
The installed local Codex CLI was not granted source/host tools as a repair agent.
No provider request or compute purchase occurred. Container execution was unverified at that time. The later validation below
exercises the Compose boundary; the three-arm real-agent comparison remains
unexecuted.

The [plan](../experiments/isolated-pilot-plan.md) was written before the run and
its SHA256 is saved in the evidence. Both executed arms received the same 12
cases (three instances per fault family/control), seeds, and budgets. All 24
selections froze before held-out work. The absent agent was not registered in
this explicitly baseline-only experiment; full three-arm launch registers it
and requires all 36 selections to freeze.

The zero-output-bias heuristic proposed 12 patches and used 24 development probes.
None met its strict development improvement rule, so every selection stayed at
root. Held-out paired improvement was therefore zero for every case in both
arms. No control regression occurred; no selected weights changed. Each proposed
patch changed five or six nonzero biases; all proposals and rejected improvements remain in the
JSON. This run demonstrates no useful repair discovery.

For each arm, held-out selected mean scores for the three instances were 18 on
controls, 0 on sign inversion, 0 on channel ablation, and 0.5 on bias shift.
Unchanged used zero probes/development forwards. Heuristic reserved 9,600
forwards and actually used 1,532 in development. Each arm reserved 14,400 final
forwards and used 7,356 across reference, corrupted, and selected evaluations.
Development truncations: unchanged 0, heuristic 6 of 48 episodes. Each arm's final
truncations: 35 of 72 model-episodes, including 6 of 24 selected episodes.

Paired standard errors against root are zero because selections equal root;
this says nothing about general repair reliability. Three instances repeat the
same corrupted weights with different seeds, and only two episodes per case
were evaluated. Scores/caps, duplicated recipes, and model memorization sharply
limit generalization. The preregistered agent success criteria are unevaluable
without the real-agent arm. Existing source discloses the network and fault
recipes; filesystem isolation alone does not establish cognitive blindness.
Restoration of known reference weights must not be called novel discovery.

Reproduction and required secrets/configuration are in
[isolated-evaluator.md](isolated-evaluator.md). Existing website/API/lab code was
preserved; this work adds no deployment or public evaluator endpoint.

Original implementation validation: [saved full test output](../experiments/evaluator-test-results.txt)
records 42 discovered tests: 41 passed, one Docker boundary test explicitly
skipped because no container runtime was available. Ruff and Python compilation
also passed. Tests include successful numeric patch/evaluation/freeze through a
scripted model, rejected executable attempts, independent-process/concurrent
HTTP admission, process death, provider-error redaction, and deferred final
failure without retry. The [real adapter launch record](../experiments/real-agent-attempt.jsonl)
records configuration failure (exit 2), with no model request or selection.


## Subsequent Compose validation (2026-11-10)

Docker Engine 29.9.3 and Compose v5.7.0 were available and responding. The expanded
container test runs the actual configured evaluator, gateway, and agent services,
using temporary private state, a dummy provider key and a dummy model. Inherited
provider credentials/configuration are discarded. Only the provider transport is
scripted; agent secret loading, configured arguments, tool execution over HTTP,
and evidence persistence run inside the Compose agent. No provider network
request or paid model call occurs, and no held-out evaluation is requested.

The first live run exposed that this Docker host did not publish the evaluator's
requested loopback port while it was attached only to an internal network. The
fixed-destination HTTP gateway now publishes that port on a separate operator
network, forwarding only POST `/rpc` and `/report`. It has no credentials or
private mounts. The evaluator retains its internal-only network and its external
egress denial is tested. The agent retains its separate provider network.

The boundary checks cover non-root identities, read-only roots and secrets,
capability/no-new-privileges settings, CPU/memory/PID limits, exact host mounts,
loopback-only publication, network membership, filesystem denial, real HTTP
authorization/participant ownership, rejected executable patches and private
artifact requests, gateway route/framing restrictions, exhausted reservations
and freezes surviving restart, refused reinitialization, redacted evidence,
and the held-out reveal gate. The scripted agent completes all its selections;
the two baseline arms remain unfrozen, so this is a validation run rather than a
three-arm experiment. One-off agent containers are explicitly removed before
Compose teardown because profiled one-offs can otherwise survive `down`.

The [current full-suite output](../experiments/container-validation-results.txt)
records 42 tests passing with `GODSEYE_CONTAINER_TEST=1`, including the actual
Compose boundary test, with no skips. Ruff passes for the changed Python files.
The original baseline results above are unchanged and do not represent a real
repair agent's performance.

Before the real-agent experiment, configure an existing OpenAI API secret file
outside the repository (`REPAIR_AGENT_KEY_FILE`, mode 600, readable by the selected
non-root UID), an explicitly chosen function-capable model available to that
account (`REPAIR_AGENT_MODEL`), and account credits/billing caps. Create fresh
mode-700 private/evidence directories outside the repository and set
`EVALUATOR_PRIVATE_DIR`, `REPAIR_EVIDENCE_DIR`, `EVALUATOR_UID`, and `EVALUATOR_GID`.
Select a fresh private generation seed, initialize once, and retain the plan and
seed in the private evidence directory. Do not reuse this test state or revealed
baseline/pilot seeds. Run both baseline arms and the real agent with their scoped
tokens, then reveal only after all 36 selections freeze. Provider compatibility,
account access, and inference behavior remain unverified because no real provider
request has been made. Pinning base images and transitive dependencies remains
necessary before making stronger reproducibility/security claims.
