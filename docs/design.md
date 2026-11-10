# What God's Eye is becoming

The product separates responsibilities: a powerful coding agent reasons about
a target network; a service holds that network,
applies explicit edits, and executes measurements. The target can be much
smaller than its programmer. The agent in the current session can already use
the CLI; no second model subscription or API key is needed for this experiment.

The first implementation is that service running locally, plus a browser UI.
It has no autonomous model loop. The paper's released network is the starting
artifact, not an accomplishment of this project. Its architecture and fixed
observation mapping are part of the experiment contract.

## The primitive is a measured patch

A patch needs a parent checkpoint, an explicit tensor change, and a hypothesis.
Its evaluation needs fixed environment settings, seeds, sampling settings,
actual forward counts, and per-episode evidence. A new checkpoint never
overwrites its parent. The tensor bytes have a reproducible hash; checkpoint
identifiers are unique, so two identical tensors can still have different
experimental histories.

Do not equate a weight difference with a capability improvement. The local
left-action ablation has a known structure; restoring it is a mechanics test.
Discovering an unknown bug requires a separate task whose answer is concealed
from the agent. Repeatedly choosing edits on the same seeds overfits those
seeds; use a disjoint seed range for final assessment and retain failed edits.
Short runs are exploration. They do not support claims against unpublished
PPO checkpoints or reproduce the paper's full evaluation.

## Relationship to Tinker

Checked November 8, 2026 against the official
[SDK overview](https://tinker-docs.thinkingmachines.ai/tinker/) and
[TrainingClient API](https://tinker-docs.thinkingmachines.ai/tinker/api-reference/trainingclient/).
Tinker provides LoRA training, forward operations, sampling, and checkpoint
management. The documented TrainingClient surface does not expose arbitrary
tensor reads and writes. Exporting a checkpoint is not itself an API for
changing arbitrary base-model parameters and hot-loading those edits.

Our inference: a Tinker-like service for direct weight programming needs
tensor access and patch execution beside its sampling service. Full weight
edits, adapter edits, and activation interventions have different semantics;
backends should declare which they support. This version supports direct
local tensor edits only. It has no Tinker adapter and incurs no Tinker charges.

## Next experiments, in order

1. Run the ablation and restoration on development seeds, then test restoration
   on a separate seed range. Verify byte equality with the original network.
2. Give an agent a concealed corrupted checkpoint and a limited probe budget.
   Measure successful repairs, weights changed, probes, and regressions across
   multiple corruption types. Run all evaluations through the harness; merely
   reporting forward counts does not enforce a budget or sandbox an agent.
3. Add a local safetensors/PyTorch or MLX backend with selected tensor reads,
   rank-one edits, rollback, and reproducible text generation. Start with an
   existing small model. Run behavioral regressions beyond the target task.
4. Explore a persistent target worker so a small edit does not require loading
   the entire model again. Measure checkpoint load time, patch transfer time,
   sampling latency, and memory before deciding whether remote infrastructure
   offers an advantage.

The product question to resolve is whether making a reasoning agent's changes
cheap to apply and easy to assess produces useful, repeatable improvements.
The current version gives us somewhere to begin collecting that evidence.
