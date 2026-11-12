# Bounded language-model pilot

This independent CLI pilot is based on main `8694007`. It does not integrate with
Store, the Breakout API, backend protocol, or UI. **Real pretrained model/GPU
execution and the Modal image are unverified.** No model weights, provider calls,
credentials, Modal run/deploy/image build, or Volumes were accessed for development.
Only public metadata/configuration/source retrieval and local dependency installs
were used. Offline synthetic numerics cannot establish model quality or GPU compatibility.

## Fixed model and runtime

The public [Qwen model API](https://huggingface.co/api/models/Qwen/Qwen3.5-0.8B)
returned immutable revision `2fc06364715b967f1860aea9cf38778875588b17`, verified
2026-11-12. The [pinned config](https://huggingface.co/Qwen/Qwen3.5-0.8B/blob/2fc06364715b967f1860aea9cf38778875588b17/config.json)
defines 24 text layers, hidden size 1024, MLP size 3584 and tied embeddings.
The [public blob metadata](https://huggingface.co/api/models/Qwen/Qwen3.5-0.8B/revision/2fc06364715b967f1860aea9cf38778875588b17?blobs=true)
reports the 1,746,942,600-byte safetensors shard SHA256
`04b1c301231dd422b8860db31311ab2721511346a32cb1e079c4c4e5f1fe4696`.
Execution verifies that hash before loading. The checkpoint contains vision and MTP
weights too; the text class skips them, but the full shard must be downloaded.

[Transformers native documentation](https://huggingface.co/docs/transformers/model_doc/qwen3_5)
explicitly supports `Qwen3_5ForCausalLM` and `Qwen3_5TextConfig` for text-only use.
The [pinned 5.22.2 implementation](https://github.com/huggingface/transformers/blob/v5.22.2/src/transformers/models/qwen3_5/modeling_qwen3_5.py)
and [loader](https://github.com/huggingface/transformers/blob/v5.22.2/src/transformers/modeling_utils.py)
are the compatibility basis. The pilot explicitly remaps `model.language_model.`
to `model.`, refuses missing/mismatched text weights, uses float32/eager attention,
safetensors, `token=False`, `trust_remote_code=False`, and no Hub kernels. Hybrid
DeltaNet uses the slower reference Torch path; short limits do not guarantee
completion. There is no fallback model or automatic retry if loading is unsupported.

Direct runtime pins are in `requirements-lm-optional.txt`: Python 3.12,
Torch 2.15.0, Transformers 5.22.2, safetensors 0.8.0, Modal 1.6.4, NumPy 2.2.6.
Transitive dependencies are resolved during installation and every installed
version is recorded in `runtime.json`; this is not a hash-locked supply-chain file.
[Qwen's pinned license](https://huggingface.co/Qwen/Qwen3.5-0.8B/blob/2fc06364715b967f1860aea9cf38778875588b17/LICENSE)
is Apache-2.0. Transformers and safetensors are Apache-2.0; Torch is BSD-3-Clause,
NumPy BSD-3-Clause, Modal SDK Apache-2.0 (see upstream package license metadata).
Repository code remains under the repository MIT license; the tiny authored
fixture in `spec.py` is offered under CC0-1.0.

## Experiment and evidence

This is an openly specified smoke fixture, not a standard benchmark. Train, dev,
and heldout each contain two distinct repeated-word completions and two distinct
exact-answer addition questions. Vocabulary and number identities are disjoint.
Train is disclosed but unused; it is not used to claim learning. Smoke takes the
first completion and first addition per split. Pilot uses all four.

Four arms share case identities, float32, greedy decoding, seed 1729 and output
caps: unchanged; a fixed concise-answer prompt prefix; repetition penalty 1.15;
and a reversible weight edit. This decoding baseline is a conventional
non-weight intervention, not fine-tuning or an adaptation-quality claim.
The only search candidates scale column 0 of layer 0's MLP down projection to
zero or column 1 by 0.5. They are deliberately narrow engineering candidates,
not a discovered repetition neuron or a published neuron-edit replication.
No Beaker/article neuron finding is claimed or transferred across architectures.

Select the highest exact-match dev mean only if it strictly exceeds unchanged
and all relevant generations terminate normally; ties use the lowest candidate
index. Otherwise the weight arm explicitly keeps the original. Save every
candidate and dev outcome, then write `frozen.json` containing configuration,
data digest, selection rule and selected-delta hash **before** any heldout call.
Heldout cannot select, revise, or retry candidates. The prompt and decoding
baselines are fixed in advance. Raw text is scored by whitespace-stripped exact
match; additional explanation fails. A truncated correct answer can score, but
termination cause remains visible. This is an intentionally limited proxy for
completion/repetition, not an open-ended repetition benchmark.

The CLI refuses an existing output directory. It persists plan/runtime identity,
every output and exact prompt/answer, generation settings, seed, errors,
termination, token counts, latency, GPU allocated/reserved peak memory, frozen
selection, all candidate artifacts and aggregate heldout paired differences,
improvement/regression counts. Errors and cap exhaustion score zero and mark the
run incomplete; they are retained rather than silently discarded. Tiny samples
always receive an inconclusive verdict. No significance, quality, inference
speedup, price improvement, or laptop support is inferred.

Each `godseye-lm-column-v1` JSON artifact contains the base model revision, exact
base projection hash/shape/dtype, bounded column, scale, original/replacement
column values and content hash. The independent loader checks schema, size,
duplicate keys, finite values, identities, operation bounds and exact current
preconditions. Reapplication verifies the replacement operation and restores the
original in `finally`, including errors; exact projection hashes verify rollback.
Only a single 1024-element column is preserved for the edit, no full parameter or
model copy. Chunked hashing reads only the projection. Model identity also binds
the public full checkpoint shard hash. Hashes establish integrity, not authorship.
The selected delta is exported only after heldout plus file reload/reapplication
and rollback checks. Unchanged selection has no selected delta. No pretrained
checkpoint export occurs. To reload independently on a freshly loaded pinned model:

```python
from godseye.lm.delta import applied, load_delta
with applied(runtime.model, load_delta('lm-result/selected-delta.json')):
    # Run the fixed evaluator/generator here. Exiting restores the original.
    pass
```

## Offline commands and future launch prerequisites

From repository root, no optional packages are needed for planning:

```sh
python3 -m experiments.lm_pilot --profile pilot
python3 -m experiments.modal_lm_pilot --profile smoke
python3 -m unittest discover -s tests -p test_lm_pilot.py -v
```

Numerical tests require local Torch and NumPy. They create an independent random
Torch module with only the matching MLP projection; no pretrained weights. The
synthetic generator is explicitly marked fixture-only and tests dev freeze,
negative heldout regressions, retained errors, tampering and rollback.

For a later user-approved GPU smoke, first approve an explicit dollar amount,
verify the workspace/account spending controls and actual available credits,
install the optional pins in an isolated Python 3.12 environment, authenticate the
Modal SDK through the operator's usual setup, and check the dry-run plan. Neither
the credit amount mentioned in conversation nor the estimate authorizes execution.
Run exactly one smoke before considering a separate pilot:

```sh
python -m experiments.modal_lm_pilot --profile smoke --output lm-result-smoke --execute
# Only after review and separate approval:
python -m experiments.modal_lm_pilot --profile pilot --output lm-result-pilot --execute
```

Local CUDA execution uses `python -m experiments.lm_pilot --profile smoke
--output lm-local-smoke --execute`. There are no arbitrary model paths, uploaded
code, evaluation scripts, cloud shell endpoints, web endpoints or service APIs.
An operator executing this trusted local repository can of course edit Python;
this CLI is not a sandbox for malicious local operators.

## Resource proposal, spending controls and cleanup

Proposed approval envelope: **one L4, 2 physical CPU cores, 16 GiB RAM, one
container, no warm containers/buffer, retries=0**, 180-second startup timeout,
600-second invocation timeout, and client result wait of 800 seconds. Both
profiles keep this startup/download allowance; smoke caps evaluation at 120
seconds/18 generations/8 new tokens, pilot at 480 seconds/36 generations/24 new
tokens. Every prompt is capped at 512 characters and 128 tokens; per-case
cooperative generation deadline is at most 15 seconds. The full pretrained shard
is approximately 1.75 GB; CPU/GPU memory and fallback-kernel performance are
unmeasured. CUDA work or model downloading can exceed cooperative case deadlines;
Modal's invocation timeout provides an outer execution stop, not a monetary cap.

[Modal pricing](https://modal.com/pricing), retrieved 2026-11-12, lists L4
$0.000222/s, CPU $0.0000131/physical-core/s, RAM $0.00000222/GiB/s.
Estimated allocated compute for 780 seconds is
`780 * (0.000222 + 2*0.0000131 + 16*0.00000222) = $0.221302`.
This is a planning estimate, **not billed cost or a hard $0.23 cap**: image builds,
startup, idle scale-down, downloads, actual resource use, network, storage and
taxes can change cost. Startup/download/model load happen before evaluation and
consume invocation time. Credits eligibility and account remaining balance are
unknown. Modal prices/billing must be rechecked before authorizing execution.
No per-token economics or total-cost claim is made.

[Budgets](https://modal.com/docs/guide/budgets) describes Workspace-wide and
Environment compute controls; an account owner/manager should verify them in the
actual account before launch. [Timeouts](https://modal.com/docs/guide/timeouts)
are per attempt and can overrun slightly. [Scaling controls](https://modal.com/docs/guide/scale)
explain max/min/buffer containers. The adapter sets all explicitly; there is one
spawn, no map, no nested model load, automatic retry, schedule, deployment or
persistent endpoint. [Images](https://modal.com/docs/guide/images) supports the
explicit local-file allowlist: only pilot Python plus the inert package initializer
are uploaded, never workspace directories, `.env`, homes, keys or repo data.

The SDK [FunctionCall cancellation](https://modal.com/docs/reference/modal.FunctionCall)
path cancels and terminates the container on interruption/client wait failure.
If the client dies, use the Modal dashboard to stop the ephemeral app and confirm
it is stopped; a disconnected client alone does not prove cancellation. The
`app.run()` context normally tears it down. No Volume is created: model cache is
ephemeral `/tmp`, so future invocations may download again. Images/build caches
and any separately created storage may persist: review and remove unwanted
resources through the account dashboard. Modal pricing lists Volume storage at
$0.09/GiB-month with an included allowance; eligibility is account-specific.

Cases are flushed locally and emitted to container logs as they complete. A
normal remote return copies the allowlisted evidence files home even for caught
Python failures. A hard timeout, OOM, preemption, or process death can prevent
returning files: preserve Modal logs/call ID and classify the run incomplete,
never claim complete evidence or automatically retry. Metering and actual billed
cost require separate account-side inspection; the pilot does not read billing
credentials or make a billed-cost assertion.

Acceptance for a future real run: complete runtime identity and all expected
case records; verified safetensors/base schema; no missing text weights;
durable freeze preceding heldout; inspectable all-arm outcomes and regressions;
valid delta reload and exact rollback (or explicit unchanged selection); measured
latency/memory/load/edit overhead and account-side billed usage. A negative or
unchanged result is valid, but no broad model-improvement claim is supported by
this fixture. On runtime incompatibility stop, report the exact error, and seek
approval for a revised pinned runtime or different model; never substitute silently.

## Development validation (2026-11-12)

An isolated local Python 3.12 environment with the exact optional pins passed
**7 dedicated offline tests**. This includes real Torch column arithmetic and
hash restoration, artifact tampering/precondition rejection, a native tiny
Qwen text model safetensors reload with exact key/tensor equality and finite
forward logits, a frozen dev selection followed by two synthetic heldout
regressions, and 18 retained synthetic generation failures. These are fixture
outcomes only. Both CLI dry runs, Python compilation and `git diff --check` passed.
The system Python 3.9 standard-library suite also passes its planning/scoring
checks, skipping optional numerical tests. The pinned Modal SDK's actual callable
signatures were inspected locally; no app or image was constructed or executed.

Validation metadata is recorded in `experiments/lm_offline_validation.json`.
Pretrained weights, CUDA execution, Modal image/build/run, billing and full-model
runtime behavior remain unverified. This work implements the reproducibility
harness, not completion of the roadmap's measured small-model acceptance gate.
