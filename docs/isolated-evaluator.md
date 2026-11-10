# Isolated repair evaluator and restricted coding agent

This adds a separate container evaluator and a Responses API tensor-programming
agent. It does not modify the website, web API, local lab, or legacy benchmark
CLI. The model writes numeric tensor patch programs through five custom function
tools; it has no shell, code interpreter, browser, filesystem, or repository tool.
The adapter follows [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling).
A local Codex CLI installation is not automatically a suitably restricted runtime,
and this project does not read or reuse its sign-in credentials.

Read [the preregistered plan](../experiments/isolated-pilot-plan.md) and
[observed results and limits](evaluator-pilot-report.md) before interpreting runs.
The evaluator **must** run in its container for an isolated experiment. Running
`python -m godseye.evaluator` directly is only protocol testing. Docker's daemon
and host administrators are trusted and can read private data; do not give the
model Docker control, a host shell, or source mounts. Do not run the repairing
model in this repository through a general-purpose coding assistant.

## Configure and launch (trusted operator)

Requirements: Docker Engine/Compose v2, Python 3.9–3.12 for baseline adapters,
an existing OpenAI API credential and an explicitly chosen function-capable model
for the real agent. No compute rental or service purchase is needed by these
commands. Provider inference can use account credits; do not run with an account
that would require a purchase. Provider billing caps remain the operator's duty.
No requests were made with paid credentials during implementation.

Use fresh private/evidence directories outside the repo. On Linux the container
UID/GID must own the bind mounts. The commands below use your non-root host UID;
if operating as root, use a dedicated non-root UID and chown both directories.
Keep the key file owned/readable by the same UID, with mode 600. Never put keys
in the repo, command arguments, stdout, JSON evidence, or shell tracing.

```sh
export EVALUATOR_PRIVATE_DIR="$HOME/godseye-private-fresh"
export REPAIR_EVIDENCE_DIR="$HOME/godseye-evidence-fresh"
export EVALUATOR_UID="$(id -u)" EVALUATOR_GID="$(id -g)"
mkdir -m 700 "$EVALUATOR_PRIVATE_DIR" "$REPAIR_EVIDENCE_DIR"
# Set these to an EXISTING secret file and an available model in your account:
export REPAIR_AGENT_KEY_FILE="$HOME/.secrets/openai-api-key"
export REPAIR_AGENT_MODEL='YOUR_FUNCTION_CAPABLE_MODEL'

docker compose -f isolation/compose.yaml build evaluator agent gateway
# Select a fresh private seed before initialization; never reuse revealed pilot seeds.
export REPAIR_GENERATION_SEED="$(python3 -c 'import secrets; print(secrets.randbelow(2**31))')"
docker compose -f isolation/compose.yaml run --rm --no-deps evaluator --initialize-only --seed "$REPAIR_GENERATION_SEED"
docker compose -f isolation/compose.yaml up -d evaluator gateway
cp experiments/isolated-pilot-plan.md "$REPAIR_EVIDENCE_DIR/plan.md"
printf '\nFull-run private generation seed: %s\n' "$REPAIR_GENERATION_SEED" >> "$REPAIR_EVIDENCE_DIR/plan.md"
```

Initialization exclusively creates private state and scoped participant/admin
credentials. It refuses repeat or partial initialization. Never delete state to
resume a failed probe. Ordinary `up`, `restart`, `stop`/`start` preserve the bind
mount and its reservations; never use `--initialize-only` again for that run.
Settings match the preregistration except for the fresh private generation seed: 12 cases, 2 probes/800
reserved development forwards per case, 2 episodes, 200 steps, CPU only.

Run the deterministic participants from the trusted host. They use the same
narrow authenticated service as the agent, distinct participant tokens, identical
weights and seed ranges. Do not hand their tokens to the model.

```sh
.venv/bin/python isolation/agent_adapter.py --participant unchanged \
  --token-file "$EVALUATOR_PRIVATE_DIR/unchanged.token" \
  --evidence "$REPAIR_EVIDENCE_DIR/unchanged.jsonl"
.venv/bin/python isolation/agent_adapter.py --participant heuristic \
  --token-file "$EVALUATOR_PRIVATE_DIR/heuristic.token" \
  --evidence "$REPAIR_EVIDENCE_DIR/heuristic.jsonl"
docker compose -f isolation/compose.yaml --profile agent run --rm --no-deps agent
```

The agent image contains **only** Python and the standalone adapter, with only
its participant token and provider key mounted as secrets. Its sole writable
host mount is the dedicated evidence directory. The evaluator has the private
weights/recipes/state, a read-only root, no capabilities, a non-root UID, a 512 MiB
memory cap, one CPU, and no external network. Agent provider egress is separate;
only its five custom tools are advertised to the remote model.
A separate minimal gateway publishes `127.0.0.1:8790` for trusted host
participants and reports. It forwards only POST `/rpc` and `/report` to the fixed
evaluator destination, with no credential or private mounts and no retries.
The evaluator itself remains on the internal network only. This avoids relying
on published ports of internal-only containers, which did not work on the tested
Docker Engine 29.9.3 host. The gateway's operator network is separate from agent
provider egress. Do not add source,
home, daemon socket, or evaluator-volume mounts to the agent service. No arbitrary
Python or patch execution occurs inside the evaluator.

No automatic retries or silent fallback selection occur. Agent exit 1 means
incomplete, exit 2 means missing configuration. Evidence files are exclusive and
incrementally flushed/fsynced, including rejected patches, provider failure and
budget exhaustion. A provider disconnect might have spent a probe; list remaining
budgets before manual recovery. An incomplete agent leaves the reveal gate closed.
A later real-agent replication must use fresh state if any feedback was revealed.

Only after **all 36 selections** freeze, the trusted operator can request the
report, without putting the admin token into arguments or logs:

```sh
.venv/bin/python - <<'PY'
import json, os
from pathlib import Path
from isolation.agent_adapter import post
private = Path(os.environ['EVALUATOR_PRIVATE_DIR'])
output = Path(os.environ['REPAIR_EVIDENCE_DIR']) / 'held-out.json'
with output.open('x') as stream:
    result = post('http://127.0.0.1:8790/report', (private / 'admin.token').read_text(), {})
    json.dump(result, stream, indent=2, allow_nan=False)
    stream.write('\n')
PY
docker compose -f isolation/compose.yaml stop
```

The report is idempotent: completed, failed, or interrupted final evaluations
are never rerun for better scores. If a crash interrupts reveal, request the
report again with a new output path; remaining frozen cases can finish, and the
interrupted work stays visible. Before reveal even freeze responses contain no
held-out results, and no held-out rollouts execute.

## Interface and persistence

`POST /rpc` uses `Authorization: Bearer PARTICIPANT_TOKEN`, JSON content type,
and at most 65,536 request bytes. Exact operation/argument fields are required:

- `list`, `{}`: opaque cases, candidate IDs, tensor shapes, remaining budgets.
- `read`, `{case_id,candidate_id,tensor,start,count}`: flattened row-major slice;
  integer start/count, 1–256 values, within tensor bounds.
- `patch`, `{case_id,parent_id,patch,hypothesis}`: validated numeric assignments,
  immutable new candidate, hashes/difference. No executable expressions.
- `evaluate`, `{case_id,candidate_id}`: development feedback only, no seeds.
- `freeze`, `{case_id,candidate_id}`: irreversible selection, no final scores.

`POST /report`, `{}` requires the separate admin token and refuses until every
registered participant freezes every case. There is no read-file, download,
private-state, reference-weight, create-suite, or arbitrary-execution route.
Each participant workspace authorizes case/candidate membership before opening
any tensor file. IDs from other cases, participants, or experiments fail.

The serial HTTP server bounds concurrent execution; POSIX file locks also
serialize independent evaluator processes. The entire probe holds its lock.
Worst-case forward calls and a probe slot are atomically persisted before
execution. Failures and process death keep reservations; the next operation marks
reserved work interrupted without replay. Final selections persist before any
held-out execution. No budget refunds or HTTP retry automation exist.

## Reproduce validation

```sh
.venv/bin/python -m unittest discover -s tests -v
# Requires a working local Docker daemon; uses loopback port 8790:
GODSEYE_CONTAINER_TEST=1 .venv/bin/python -m unittest discover -s tests -p test_evaluator_container.py -v
# Fresh, baseline-only, non-isolated protocol/evaluation check:
.venv/bin/python -m experiments.evaluator_pilot --output /tmp/baseline-http-fresh.json
```

Container tests build all three images and run the actual Compose services with fresh
private/evidence directories, a dummy provider key, and an explicit dummy model.
They discard inherited provider credentials and configuration. Tests inspect the
running containers' users, capabilities, resource limits, mounts, loopback port
binding, and network separation; probe evaluator egress denial and agent filesystem
write/read restrictions; and exercise real HTTP authorization, participant ownership,
private-artifact/executable-patch rejection, exhausted budgets, persistent freezes,
and refused reinitialization after restart. A scripted provider replaces only the
provider transport inside the Compose agent while its configured adapter command,
secret loading, evidence writes, and evaluator HTTP tools execute normally. No
provider network requests are made. All agent selections freeze, but the other
arms stay unfrozen and the held-out reveal gate remains closed. Tests clean up
containers, networks, and temporary data. They are skipped explicitly without Docker.
Interface tests independently cover auth, private-artifact requests, experiment
and participant ownership, slice limits, executable patches, immutable lineage,
concurrency, failure/process-death recovery, frozen selections, reveal gating,
and a scripted agent driving actual HTTP tools. Scripted responses verify the
adapter, not intelligent repair. Docker image bases/dependencies should be pinned
to audited digests before stronger reproducibility or security claims.

This is research infrastructure, not production security. Container escapes,
malicious host operators, network denial of service, durable disk loss, model
memorization, and inference-provider behavior are outside these tests. The repo
already publishes the network and recipes; source familiarity limits blindness
claims even when filesystem isolation works. Known-weight restoration is not
novel repair discovery. Two capped episodes provide very weak uncertainty estimates.

## Easy local OpenAI key setup (macOS)

Double-click `scripts/Configure-OpenAI.command` in Finder, or run:

```sh
.venv/bin/python -m godseye.provider_setup
```

A loopback-only page opens with a masked key field and optional model ID. It
stores the key at `~/.godseye-secrets/openai-api-key` (mode 600), in a directory
with mode 700, outside the repository. This is a plaintext local secret protected
by OS permissions, not encryption or Keychain. The page never returns a saved key to the browser and uses no browser storage.
Opening or saving makes no external API requests. Explicit model loading and
confirmed connection checks read the selected key server-side to contact that
provider. Saving does not validate credentials or authorize an experiment. Setup exits after
30 minutes or Ctrl+C; reopen the launcher to edit configuration again.

Before using the launch commands above, load the generated configuration:

```sh
set -a
. "$HOME/.godseye-secrets/provider.env"
set +a
```

This exports the file path and selected model, not the secret value. Skip the
manual `REPAIR_AGENT_KEY_FILE` and `REPAIR_AGENT_MODEL` assignments in the earlier
example. If you left model blank, choose it before launching the real agent.
Never mount this whole directory into the repair container: keep using the
existing single-file Compose secret. The setup page now supports OpenAI,
OpenRouter and Hugging Face, each with a separate key and saved model setting.
It exports `REPAIR_AGENT_PROVIDER` and `REPAIR_AGENT_ROUTING` as well.

### Provider routing

Reopen `scripts/Configure-OpenAI.command` to load the updated setup page (an
already running setup process must be restarted). Select a provider and enter an
explicit tool-capable model ID. Saving switches the active configuration without
removing other providers' keys. Blank key preserves only the selected provider's
key. Existing OpenAI settings migrate when saved; no key migration is needed.
Rebuild the agent image after changing adapter code.

OpenAI uses its Responses endpoint. OpenRouter and Hugging Face use their fixed
chat-completions endpoints. The adapter preserves assistant tool-call groups and
reasoning metadata across chat turns. Model capability and account access are
not inferred from a model name, and saving settings makes no network requests.

OpenRouter supports price, latency, or throughput preference. Requests require
parameter support, deny provider data collection, and disable provider fallback.
These constraints may make a route unavailable. Hugging Face performs its own
routing; its privacy policies are separate from OpenRouter's controls. Routing
preferences are not price guarantees or dollar caps. Set account spend controls.
No adapter retries or cross-provider/model fallback are performed.

Evidence records the selected endpoint/policy and returned model/provider when
available, alongside usage. Missing upstream identity is not inferred. Existing
round, tool, time, output-token and evaluator budgets remain in force. Cumulative request and reported-token limits now also apply; see
[agent budgets](agent-budgets.md) for configuration, overshoot, and restart rules.
These controls are not a dollar spending cap.

Validation uses dummy transports and credentials. Live provider compatibility,
including provider-specific reasoning models, must be tested separately with an
explicitly bounded run. Opening setup and saving settings make no provider requests. Explicit catalog
loading contacts the selected provider; a separately confirmed connection test
makes one potentially billable request. See [provider discovery](provider-discovery.md).
Unit tests use dummy credentials and mocked providers.

References: [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling),
[OpenRouter routing](https://openrouter.ai/docs/guides/routing/provider-selection),
[Hugging Face chat completions](https://huggingface.co/docs/inference-providers/en/tasks/chat-completion).
