# God's Eye

[![Validate lab and static demo](https://github.com/romrom-20/Gods-eye/actions/workflows/ci.yml/badge.svg)](https://github.com/romrom-20/Gods-eye/actions/workflows/ci.yml)

**Edit a neural network's weights. Run both versions. See what changed.**

God's Eye is an open-source weight-space programming workbench with a browser UI,
Python API, and isolated AI repair harness. Start with a tiny Breakout-playing
network on your CPU. Preserve the original, make an explicit edit, and compare
measured behavior.

[Recorded demo](https://romrom-20.github.io/Gods-eye/) · [Quick start](#try-a-real-experiment-no-api-key) · [Install a package](docs/install.md) · [Agent setup](docs/experiment-orchestration.md) ·
[Roadmap](docs/roadmap.md) · [Report a problem](https://github.com/romrom-20/Gods-eye/issues)

## Try a real experiment — no API key

Requires Python 3.9–3.12. On macOS or Linux:

```sh
git clone https://github.com/romrom-20/Gods-eye.git
cd Gods-eye
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[server]'
.venv/bin/python -m godseye serve
```

Open **http://127.0.0.1:8787/lab.html#overview** and click
**Try the four-number change**. It saves an edited copy and plays four games per
version, capped at 1,000 steps each. Compare scores and replay the gameplay.
The original remains unchanged. No Docker, GPU, provider key, or paid call is
needed for this example.

Use **Edit weights** for your own numeric changes, **Compare** for paired
evaluations, and **History** to revisit results. The known four-weight edit tests
the mechanics; it is not an AI-discovered improvement or a new research result.

The connected workspace shows saved originals, edited checkpoints, and measured
comparisons. Select a checkpoint to inspect its tensors and saved patch; select a
comparison to replay both versions. **List** provides keyboard-friendly navigation.
Lines represent recorded parentage and comparisons, not inferred model circuits.
See [workspace behavior and limitations](docs/experiment-workspace.md).
For a repeatable tester or coding-agent handoff, use [Try the product](docs/test-the-product.md).

## Bring your own Breakout checkpoint

In **Edit weights**, choose **Import checkpoint** and select a compatible `.npz`.
Give it a name and optional source/license notes. The app preserves it as an
imported original; edit a copy, compare both, and revisit the saved results.
Importing does not run a model or start AI repair.

This supports the fixed 600 → 32 → 32 → 6 Breakout architecture and the documented
finite float32 archive format, up to 128 KiB. It does not load arbitrary language
models. See [accepted format, CLI and API](docs/checkpoint-import.md).

## What works today

- **CPU workbench:** inspect tensors, preview numeric patches, save immutable
  checkpoints, compare versions, and replay results.
- **Goal-driven experiment UI and API:** review a supported Breakout goal and
  finite limits, explicitly start, follow status, cancel, and inspect evidence.
  This requires the separately configured experiment service below.
- **Isolated repair worker:** Docker execution, persistent budgets, duplicate-start
  protection, crash recovery, and tested cleanup. Provider adapters support
  OpenAI, OpenRouter, and Hugging Face; real-provider compatibility and repair
  quality are not established by scripted tests.

The current planner recognizes a small set of Breakout phrases, including
“Improve Breakout score.” It does not understand arbitrary requests or edit Qwen.
Completed trusted runs support [checkpoint download and verified reload](docs/checkpoint-export.md),
with rollback to the original. [Observed activity](docs/agent-activity.md) records
actual operations and reports unknown phases when evidence is unavailable.
Hosted multi-user access remains unfinished. No quality improvement or
inference-cost saving is promised.

An optional [Qwen intervention pilot](docs/language-model-pilot.md) is available
as a separate experimental CLI. Its offline checks pass; pretrained checkpoint
loading, GPU execution, and improvement remain unverified. It is not integrated
into the browser or goal planner. The Modal runner requires explicit execution
and a reviewed spending budget.

## Run an AI-guided experiment

The AI programmer proposes edits to the Breakout model; its own weights are not
modified. This path requires Docker, a fresh registered private evaluation suite,
a configured provider key, an explicit model selection, and reviewed limits.
Start with the [local setup and launch guide](docs/local-operator-setup.md).
The [experiment service contract](docs/experiment-orchestration.md) explains
registration, isolation, cancellation, and results in detail.

Starting the ordinary lab alone does **not** configure that service. If the goal
screen reports “Experiment service is unavailable,” use the CPU example above or
complete the service setup. Saving a provider key alone does not launch anything.
Provider requests may incur charges; token limits are not hard dollar caps.

The [mock walkthrough](http://127.0.0.1:8787/lab.html?goalMode=mock#goal) is available
while your local server runs. It is explicitly labeled and runs no experiment.
Local links work only on the machine running the server; there is no public
multi-user instance yet.

## Research and project direction

The starting network is the released Breakout policy from
[Sparks of Weight-Space Programming](https://rikiyat.github.io/blog/weight-space-programming/):
a 600 → 32 → 32 → 6 tanh MLP with 20,486 parameters. See
[provenance and licenses](fixtures/breakout/PROVENANCE.md).

Our goal is to turn a supported request into a tested, reversible model change—or
an honest report that no improvement was found. Next: a bounded real-provider
baseline, clearer setup, and independent user testing. An invite-only hosted beta
with user isolation and spending controls follows evidence of value. See the
[roadmap](docs/roadmap.md).

## Share a demo without hosting compute

```sh
.venv/bin/python -m godseye export-demo --output dist/demo
python3 -m http.server 8080 --directory dist/demo
```

Open **http://localhost:8080**. The export contains the product website, developer
guide, real tensor data, and two bundled recorded comparisons. Visitors can
inspect and replay; mutation and evaluation controls are disabled and labeled.
Upload the directory contents to any static host. Relative links also work under
a subdirectory. No Python server or GPU is needed on that host. The export never
reads your private `.godseye/` workspace and refuses to overwrite a nonempty folder.

See [public demo preparation and approval steps](docs/public-demo.md) for the
subdirectory preview, artifact audit and gated Pages workflow. The recorded demo is now deployed on GitHub Pages; no live hosted API is supplied.

Alternatively, `godseye serve --demo` serves the bundled data read-only through
Python. The GitHub Actions workflow tests the project and builds a downloadable
`godseye-static-demo` artifact; deployment requires successful main CI and an environment review.

## Python API

Install the package with `pip install -e '.[server]'`. In a **separate terminal**,
run `godseye serve` and leave it running while you use the client below.
`Client()` only stores connection settings; the first method call contacts the
server. Its default URL is `http://127.0.0.1:8787`; use `Client(url=...)` if the
server prints another address or port.

```python
from godseye.client import Client

lab = Client()
patch = "W3[0:8:2, 1] = 0"
hypothesis = "Removing the left circuit reduces score."
preview = lab.preview("paper", patch, hypothesis)
branch = lab.patch("paper", patch, hypothesis,
                   expected_parent_sha256=preview["parent_sha256"])
job = lab.evaluate("paper", branch["id"], episodes=8, seed=1000,
                   max_steps=3000, idempotency_key="first-ablation")
result = lab.wait(job["id"])
print(result["paired_mean_delta"], result["paired_se"])
```

The API returns a job immediately. Poll it, cancel with `lab.cancel(job["id"])`,
or use `wait`. A wait timeout does not cancel the job. Jobs survive page reload;
restart marks unfinished jobs interrupted. See `/api.html` for the developer
guide and `/api/v1/openapi.json` for the typed schema. The former synchronous
`POST /api/compare` route is replaced by `POST /api/v1/jobs`.

Connection failures raise `godseye.client.TransportError` with setup guidance and
safe `reason`/`errno` classification. The client does not automatically retry.
A write that loses its response has an unknown outcome: inspect jobs/state before
submitting again and retain the original idempotency key. A transport failure
does not prove that work stopped or was never admitted.

For the same no-key workflow using raw HTTP, see the short
[preview → checkpoint → job → result example](docs/http-example.md).

One CPU worker executes at a time, with four admitted jobs and a 250,000 maximum
forward-call budget per job. The CLI permits larger bounded local experiments.
Artifacts use the current directory's `.godseye/`, or `GODSEYE_DATA_DIR`.

The writable server is loopback-only. Optional `GODSEYE_API_TOKEN` protects the
API; supply it through the lab's Connection settings or `Client(token=...)`.
This is a single-user tool, not production multi-tenant hosting. Read the
[security contract](docs/security.md) before changing the deployment boundary.

## Use from an agent or terminal

```sh
.venv/bin/python -m godseye inspect paper
.venv/bin/python -m godseye compare --base zero --candidate paper --episodes 8 --seed 1000 --max-steps 3000
```

To create a checkpoint, put numeric tensor assignments in a text file:

```text
# Erase the left-action output connections.
W3[0:8:2, 1] = 0
```

```sh
.venv/bin/python -m godseye patch --base paper --file edits.txt --hypothesis 'Removing left-action connections should reduce the score'
.venv/bin/python -m godseye compare --base paper --candidate CHECKPOINT_ID --episodes 8 --seed 1000 --max-steps 3000
```

The edit parser accepts numeric assignments and slices, plus `+=`, `-=`,
`*=`. It rejects executable Python and validates the entire patch before saving
anything. It applies changes to a copy and preserves the original checkpoint.

Models, parent hashes, hypotheses, exact patches, per-episode scores, replay
frames, forward counts, and settings persist in `.godseye/`. The UI can reopen
saved runs and download their JSON. CLI comparisons also print the artifact path.

## Evaluation contract

MinAtar **1.0.15**, Breakout, official six actions, softmax sampling,
sticky-action probability **0.1**. Both models use the same episode seeds,
with separate environment and policy random streams. The observation channel
mapping follows the authors' released prompt. Capped episodes are marked as
truncated. The UI reports mean score, standard error, and the mean and standard
error of paired score differences; these are not confidence intervals.

The one-click example uses four episodes and a 1,000-step cap; the advanced comparison defaults to eight episodes and a 3,000-step cap. The upstream
evaluation uses 1,000 episodes and a 10,000-step cap. The CLI caps a run at 64
episodes per model; full benchmark replication is outside this first version.
Using the same random seeds does not force identical environment trajectories
after policies choose different actions. There is no PPO checkpoint included.

## Validation

```sh
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m experiments.reproduce
```

See [docs/design.md](docs/design.md) for the Tinker capability boundary, the
research limitations, and the next experiments. This application uses a local
NumPy backend; it does not call Tinker or automatically call another LLM.

`experiments.reproduce` reruns five comparisons, including restoration on a
disjoint seed range, and writes a compact evidence record to
[experiments/first-session-results.json](experiments/first-session-results.json).
Full traces stay in `.godseye/`. The evidence includes the patches and hashes
needed to reconstruct the three candidate checkpoints.

## Continue building

Start with the [implementation roadmap](docs/roadmap.md): validate a concealed
repair task, add one small language-model backend, then add remote execution
with tenant isolation and transactional spending limits. The static demo and
local CPU lab are usable today. General autonomous repair quality, remote workers,
accounts, and billing remain future milestones.

## Agent repair benchmark

A separate CPU benchmark now provides three fault families and an unchanged
control, opaque case IDs, persistent probe budgets, frozen final selections,
and delayed held-out reports. Run the deterministic baseline demonstration:

```sh
.venv/bin/python -m experiments.benchmark_demo --output /tmp/repair-demo.json
```

Choose a new output filename for each run. See [the benchmark protocol](docs/repair-benchmark.md)
for coding-agent CLI commands and budget semantics. This is a local protocol,
not an isolated blind evaluator; same-user access to private files and the
reference fixture can reveal answers. The demo makes no autonomous repair claim.

A separate [container evaluator and restricted coding-agent adapter](docs/isolated-evaluator.md)
now provide scoped authenticated tools, bounded tensor slices, and an experiment-wide
held-out gate. [Saved baseline-only observations](docs/evaluator-pilot-report.md)
include three instances per fault family and controls. The real-agent experiment
remains unexecuted; container validation with a scripted provider has passed.
The report separates those limits from real-provider repair evidence.

## Add your model API key locally

On macOS, double-click `scripts/Configure-OpenAI.command`, or run
`.venv/bin/python -m godseye.provider_setup`. The setup page stores separate provider
keys outside the repo in `~/.godseye-secrets/`, with owner-only permissions.
Model choice can wait. Saving performs no provider requests and starts no jobs.
See [the launch guide](docs/isolated-evaluator.md#easy-local-openai-key-setup-macos)
for loading the saved configuration into the isolated experiment.


### Choose a provider and bound an agent run

The local setup page supports OpenAI, OpenRouter, and Hugging Face. Load a
searchable model catalog, keep a manual model ID, or explicitly confirm a
one-request tool-calling check. Saving settings never starts a request or experiment.
See [provider discovery](docs/provider-discovery.md).

The isolated agent enforces request, reported-token, elapsed-time, and tool limits.
Missing usage stops the run, and resuming an existing agent evidence directory is
refused. Configure limits before launch; these are not dollar spending caps.
See [agent budgets](docs/agent-budgets.md).

See [Contributing](CONTRIBUTING.md) and [Changelog](CHANGELOG.md). Current package
version: **0.3.0**; preparing this demo does not publish a versioned release.
