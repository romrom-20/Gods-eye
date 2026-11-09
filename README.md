# God's Eye

A local workbench for **direct weight-space programming**. Inspect an actual
neural network, edit its tensors, branch checkpoints, compare gameplay, and
replay the decisions. No training loop, API key, or remote compute required.

The starting network is the released Breakout policy from
[Sparks of Weight-Space Programming](https://rikiyat.github.io/blog/weight-space-programming/).
It is a 600 → 32 → 32 → 6 tanh MLP with 20,486 parameters. Attribution and
licenses are in [fixtures/breakout/PROVENANCE.md](fixtures/breakout/PROVENANCE.md).

## Run

Python 3.9+:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m godseye serve
```

Open **http://127.0.0.1:8787**. The Overview opens a recorded experiment with
paired gameplay, action probabilities, and neuron activations. Use the sidebar
to move between **Tensor lab**, **Evaluations**, and **Run history**.

In **Tensor lab**, select **Ablate a circuit**, create a checkpoint, and use
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
