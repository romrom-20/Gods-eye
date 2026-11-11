# Prepare a local Breakout experiment without spending

This trusted operator flow prepares fresh external private evaluation data and
opens the existing isolated experiment service. Setup, readiness checks, opening
the browser, planning and reloading make **no provider requests**. Saving a key
is not approval to use it. Only the browser's explicit confirmation of a reviewed
provider, model, routing policy and all seven finite limits can admit execution.
The target is the supported Breakout policy, even if the programmer model is Qwen.

Requirements: a source checkout, Python 3.9–3.12, the project's server dependencies,
a working Docker Engine with Compose v2, and a non-root OS user. Install into your
own virtual environment, then prepare the existing images explicitly:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[server]'
EVALUATOR_PRIVATE_DIR=/tmp/godseye-build-placeholder docker compose --project-name isolation -f isolation/compose.yaml build evaluator agent gateway
```

Image building is an operator prerequisite, not part of bootstrap or launch.
Review the checkout and rebuild images when adapter/evaluator code changes.
Bootstrap never pulls/builds images, contacts a provider, reads a saved credential,
loads the provider environment file or performs a connection test. It checks only
profile file presence, size, ownership and permissions; presence does not establish
credential validity, account access, tool compatibility or model availability.

If needed, configure a provider separately using the loopback page:

```sh
.venv/bin/python -m godseye.provider_setup
```

Saving a profile is offline. Catalog loading contacts the provider; the separately
confirmed connection check can be billable. Neither action is needed for bootstrap.
Profiles stay in the existing `~/.godseye-secrets` directory. The setup checker
requires this directory to be owned by you with mode 700, and present profile/key
files to be regular owned files with no group/other access (normally mode 600).
It refuses symlinks, including private path ancestors, and does not silently fix
permissions or expose profile values. No secret directory is mounted during setup.

## One command before model/spend authorization

From the checkout, with dependencies and images already installed:

```sh
.venv/bin/python -m godseye bootstrap --root "$HOME/godseye-local-20261111-1" --launch --port 8789
```

Choose a different **new** root if that directory already exists. Do not point it
at any existing suite, copy a previous suite, remove claims, delete state, or reset
budgets. The parent must already exist. Bootstrap refuses an existing root even
when empty or partially initialized. All private state is external to the checkout
and web root; root and private evaluator/service directories use mode 700, and the
exclusive durable setup receipt/database use mode 600. No route serves them.

The initializer uses the existing evaluator image with a fresh random private seed
generated inside a network-disabled, non-root, read-only container, no capabilities,
no-new-privileges, and the existing evaluator CPU/memory/PID limits. It mounts only
the fresh private evaluator directory. The private seed is not printed or put in
process arguments. Initialization creates all three participants, with the existing
bounded suite settings: three instances per fault/control family (12 cases), two
probes and 800 development forwards per case, two episodes capped at 200 steps.
These settings are evaluator bounds, separate from the later approved AI limits.

Bootstrap registers the actual fresh roots/settings using the existing offline
registration contract, with a random durable baseline identity. It neither selects
an AI model nor submits a run. The launch listens only on `127.0.0.1:8789`, leaving
ordinary lab servers such as port 8788 untouched. Port conflicts fail clearly and
do not stop another server. No general shell/configuration/registration endpoint
is added. Keep the evaluator gateway port 8790 free before confirming an experiment;
the existing Docker worker supports one live evaluator at a time.

Open the printed local `/lab` URL and use the goal workspace. Enter the supported goal
`Improve Breakout score`. Before **Start**, explicitly choose:

- Provider, an exact tool-capable programmer model ID available to your account,
  and routing preference (`price`, `latency`, or `throughput`).
- `max_requests`, `max_input_tokens`, `max_total_output_tokens`, `max_seconds`,
  `max_rounds`, `max_calls`, and `max_output_tokens`.

Review the interpreted target, baseline, held-out evaluation and success criteria,
then approve the exact reviewed specification. All limits must be positive finite
integers within the registered ceilings. Saved profile defaults are not consent.
Request/token bounds are not dollar guarantees, and reported token totals can
overshoot by one response; retain unknown usage honestly. Set account-side spend
controls before approving an experiment. Unsupported goals remain rejected by the
existing allowlist; setup does not expand target/model-editing support.

## Relaunch, errors and another experiment

Stop your own service with Ctrl+C. Reopen its existing identities with:

```sh
.venv/bin/python -m godseye launch --root "$HOME/godseye-local-20261111-1" --port 8789
```

Relaunch never initializes, registers, resumes an agent or submits inference.
Browser reloads use the persisted draft/run identity and existing confirmation
protocol. An already admitted run may continue after a browser disconnect; use
its saved identity and status/cancellation controls. Restart interrupts unresolved
work, preserves reservations/claims, and performs only the worker's existing
local orphan-container cleanup. It never silently resubmits inference.

A registration permits one run, including a cancelled or failed run. For another
experiment, keep the old setup and bootstrap an entirely new external root.
An initialization failure leaves partial state for inspection; select a new root
rather than retrying initialization in place. No automatic repair, reset, deletion,
registration reuse, provider retry or spend occurs. Malformed receipts, unsafe
permissions, missing images/daemon/Compose, a busy service database or occupied
port fail with fixed errors rather than echoing raw private errors.

An optional read-only local prerequisite check is:

```sh
.venv/bin/python -m godseye readiness
```

`provider_profiles_present: []` means a profile is absent; it does not prevent
preparing the browser/service, but execution needs a saved key for the explicitly
chosen provider. `provider_verified: false` and `inference_authorized: false` are
intentional. Setup makes no claim about model quality, compatibility or progress.

## Verification

```sh
.venv/bin/python -m unittest discover -s tests -p test_local_setup.py -v
GODSEYE_SETUP_DOCKER_TEST=1 .venv/bin/python -m unittest discover -s tests -p test_local_setup.py -v
```

The offline tests use temporary dummy profiles, a real evaluator/registration and
actual FastAPI experiment routes, replacing only Docker initialization. They guard
against any provider file opens or credential loads during setup, plan, reload and
invalid confirmation; they check durable identity, refused reuse, partial failures,
private permissions, occupied ports and redacted errors. The opt-in check runs
actual existing Docker images, fresh initialization and the actual service through
two openings, plus the real CLI, Uvicorn and loopback HTTP across restart; it never builds images, starts an agent or contacts a provider.
These setup checks complement the separate isolation and Docker-worker tests;
they do not establish intelligent repair or authorize a real-provider run.

Validation on November 11, 2026: Python 3.12 / Docker Engine 29.9.3 ran all eight
setup checks, including both real-Docker scenarios, successfully. The full offline
suite passed 174 tests (17 opt-in skips), and all 28 existing orchestration tests
passed. Ruff, Python 3.9 compilation and `git diff --check` passed. No real provider
request, saved operator credential read, image build or real-agent experiment was
performed; the existing port-8788 service was left unchanged.
