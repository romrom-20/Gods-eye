# Repair pilot preregistration

Written before executing `experiments.evaluator_pilot`. This is a bounded CPU
pilot, with no rented compute, GPU, training, or service purchases.

The full comparison has unchanged, existing zero-output-bias heuristic, and a
real tool-calling tensor repair coding agent. Each receives identical generated
weights, fault order and development/held-out seed sets, with distinct opaque
IDs and scoped credentials. Three instances of each of sign inversion, action
channel ablation, output bias shift, and untouched control: 12 cases per arm.
Instances currently repeat the same corruption weights with different evaluation
seeds; they are not 12 independent model architectures or diverse fault recipes.
Generation seed 71; development seeds are below 16,000,000, held-out seeds above
100,000,000. Two episodes, 200 steps maximum, softmax policy, sticky actions 0.1.
Each case has two development probes and 800 reserved forward calls; each
request reserves 400 even on failure. Fixed final budget: 1,200 per case.
Maximum environment forwards for three arms: 72,000 (development + final).

Unchanged freezes root without probing. Heuristic probes root, patches `b3[:] = 0`,
probes candidate, and selects it only on strict development improvement. Retain
failed/no-change patches and losses. The agent receives only the adapter prompt
and five tools, at most 80 model rounds, 160 tool calls, 2,000 output tokens per
round, and 900 seconds between calls. Network timeouts can extend wall time by
one in-flight call. No automatic provider or evaluator retries. No fallback to a
heuristic or fabricated agent selection on agent failure.

Freeze every case in every registered arm BEFORE any held-out evaluation or
feedback. Administrator report is a separate credential, absent from model
context. If the real runtime/credentials or container engine are unavailable,
run a separately labeled baseline-only protocol check. It has two registered
arms, never pretends to include an agent, and is NOT an isolated-agent experiment.
A subsequent real-agent comparison MUST use fresh evaluator state and all three
arms; do not reuse revealed baseline seeds for an ostensibly blind agent run.

Exploratory success criterion: agent improves mean held-out score over unchanged
on at least two of three corrupted families, exceeds heuristic aggregate mean
paired improvement over the nine corrupt cases, and has no negative aggregate
paired delta on the three controls. Report per-instance results and all failed
attempts regardless of outcome. Count selected changed weights relative to root,
probes, reserved and actual forwards, and truncation for every arm. Report paired
standard errors; with two episodes and duplicated fault recipes these cannot
establish statistical significance or broad generalization. Severe truncation
can hide both useful repairs and regressions.

Existing network and recipes are in the public repo. Container files and private
state are outside model tools; source familiarity and model memorization can
still defeat claims of blindness. Restoring known reference weights is not novel
repair discovery. Host/daemon administrators are trusted. No production security
claim is made. The baseline-only check does not test container isolation.
