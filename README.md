# God's Eye

A website, local CPU lab, and API for **direct weight-space programming**. Inspect an actual
neural network, edit its tensors, branch checkpoints, compare gameplay, and
replay the decisions. No training loop, API key, or remote compute required.

The starting network is the released Breakout policy from
[Sparks of Weight-Space Programming](https://rikiyat.github.io/blog/weight-space-programming/).
It is a 600 → 32 → 32 → 6 tanh MLP with 20,486 parameters. Attribution and
licenses are in [fixtures/breakout/PROVENANCE.md](fixtures/breakout/PROVENANCE.md).

## Where we’re going

Describe a supported improvement in natural language, review the experiment limits,
and receive a tested, reversible model change—or a clear report that it did not
improve. The current release is a local Breakout workbench with a separate agent
harness; the natural-language workflow and editable language-model backend are
next. Better quality or lower cost must be demonstrated, not assumed.

See the [prioritized roadmap and release criteria](docs/roadmap.md).

## Run

Python 3.9–3.12:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m godseye serve
```

Open **http://127.0.0.1:8787** for the website or **http://127.0.0.1:8787/lab**
for the lab. Existing experiments appear in Overview with paired gameplay,
action probabilities, and neuron activations. A new workspace starts empty;
create your first comparison in Evaluations. Use the sidebar to move between
**Tensor lab**, **Evaluations**, and **Run history**.

In **Tensor lab**, select **Ablate a circuit**, preview the changes, create a checkpoint, and use
**Compare this checkpoint** to run an evaluation. Then select **Restore it**,
branch from the ablated checkpoint, create a checkpoint, and compare again.
The original checkpoint remains available for rollback.

The presets remove and restore four known output connections. The observed
score change tests this workbench's mechanics; it is not a new scientific
result or an independent replication of the full paper.

**Write a reactive policy** starts from zero weights and loads
[experiments/ball-chaser.edits](experiments/ball-chaser.edits), a small controller
authored for this project. Its first hidden unit computes the difference
between ball and paddle columns; the next layers turn that into movement
logits. It has no velocity prediction. Compare it with zero initialization
and with the released policy, and inspect its much sparser tensors.

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

Alternatively, `godseye serve --demo` serves the bundled data read-only through
Python. The GitHub Actions workflow tests the project and builds a downloadable
`godseye-static-demo` artifact; it does not deploy automatically.

## Python API

Install the package with `pip install -e '.[server]'`, then run `godseye serve`.

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

The quick default uses eight episodes and a 3,000-step cap. The upstream
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
local CPU lab are usable today. Autonomous LLM editing, remote workers,
accounts, and billing are future milestones.

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
and container verification remain unexecuted on the implementation host; the
report separates those limits from completed code and deterministic tests.

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
